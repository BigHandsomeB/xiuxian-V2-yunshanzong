"""@module Asset catalog; @purpose One metadata owner, safe files and explicit runtime publication.
@depends sqlite3, model, images, prompts; @usedBy web and tests; @see asset-pipeline.md
"""
import copy, hashlib, io, json, os, sqlite3, uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from PIL import Image
from .model import AssetError, require, identifier, templates, grid, rectangle, mapping, REVIEW, INTERIOR_REVIEW
from .images import decode, png, crop, runtime
from .prompts import compile_prompt, project_rules
from .specs import freeze_spec, grid_regions, resolve_template, export_spec, default_export_policy
from .sheets import scope, canonical_spec, freeze_container, regions as sheet_regions, FRAME_SEMANTICS, cell_key, grid_options
from .selection import validate as validate_selection, intersect as selections_intersect, crop_region
from . import appearance
from .sets import creation_spec, static_spec, static_regions, available_id, suggested_id

PROJECT = Path(__file__).resolve().parents[2]

def now():
    return datetime.now(timezone.utc).isoformat()

def uid():
    return uuid.uuid4().hex

class Catalog:
    def __init__(self, root, template_file=None, seed_file=None, merge_runtime=False):
        self.merge_runtime = merge_runtime
        self.root = Path(root).absolute()
        require(self.root.resolve().is_relative_to(PROJECT), "Asset workspace must be inside V2")
        require(not self.root.is_symlink(), "Symlink workspace forbidden")
        self.root.mkdir(parents=True, exist_ok=True)
        self.template_file = Path(template_file or PROJECT / "assets/templates/templates.json")
        self.templates = templates(json.loads(self.template_file.read_text()))
        self.path("registry/catalog.sqlite3").parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS metadata(kind TEXT NOT NULL, id TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY(kind,id))")
            conn.execute("CREATE TABLE IF NOT EXISTS schema_version(version INTEGER NOT NULL)")
            row = conn.execute("SELECT version FROM schema_version").fetchone()
            require(row is None or row[0] == 1, "Unsupported asset catalog schema")
            if row is None:
                conn.execute("INSERT INTO schema_version VALUES(1)")
        os.chmod(self.path("registry/catalog.sqlite3"), 0o600)
        if not self.path("manifest.json").exists():
            self.atomic("manifest.json", b'{"schema_version":1,"assets":{}}\n')
        seed = json.loads(Path(seed_file or PROJECT / "assets/registry/asset-registry.json").read_text())
        require(seed.get("schema_version") == 1 and isinstance(seed.get("sets"), list), "Unsupported bootstrap Registry schema")
        for value in seed["sets"]:
            if not self.get("set", value["set_id"], missing=True) and not self.get("deleted_set", value["set_id"], missing=True):
                self.create_set(**value)

    def path(self, relative):
        require(isinstance(relative, str) and not Path(relative).is_absolute() and ".." not in Path(relative).parts, "Unsafe asset path")
        target = self.root / relative
        require(target.resolve().is_relative_to(self.root.resolve()), "Asset path escapes workspace")
        for part in [target, *target.parents]:
            if part == self.root.parent:
                break
            require(not part.is_symlink(), "Symlink asset path forbidden")
        if target.exists():
            require(target.is_file() and target.stat().st_nlink == 1, "Unsafe existing asset file")
        return target

    def atomic(self, relative, data):
        path = self.path(relative); path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path(relative + "." + uid() + ".tmp")
        mode = 0o644 if relative == "manifest.json" or relative.startswith("runtime/") else 0o600
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), mode)
        try:
            with os.fdopen(fd, "wb") as out:
                out.write(data); out.flush(); os.fsync(out.fileno())
            require(relative == "manifest.json" or not self.path(relative).exists(), "Immutable asset file already exists")
            os.replace(temp, self.path(relative))
        finally:
            if temp.exists():
                temp.unlink()

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path("registry/catalog.sqlite3"), timeout=5)
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback(); raise
        finally:
            conn.close()

    @contextmanager
    def transaction(self):
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            yield conn

    def get(self, kind, key, conn=None, missing=False):
        if conn is None:
            with self.connection() as connection:
                return self.get(kind, key, connection, missing)
        row = conn.execute("SELECT body FROM metadata WHERE kind=? AND id=?", (kind, key)).fetchone()
        if row is None:
            require(missing, "Unknown " + kind + " reference")
            return None
        return json.loads(row[0])

    def put(self, kind, key, body, conn, new=False):
        if new:
            require(self.get(kind, key, conn, True) is None, "Duplicate " + kind + " ID")
        conn.execute("INSERT INTO metadata VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body", (kind, key, json.dumps(body, ensure_ascii=False, sort_keys=True)))

    def list(self, kind):
        with self.connection() as conn:
            return [json.loads(r[0]) for r in conn.execute("SELECT body FROM metadata WHERE kind=? ORDER BY id", (kind,))]

    def create_asset(self, asset_id, name_zh, template_id, set_id=None, state=None, tags=None, family=None):
        with self.transaction() as conn:
            return self._create_asset(asset_id, name_zh, template_id, set_id, state, tags, conn, family)

    def _create_asset(self, asset_id, name_zh, template_id, set_id, state, tags, conn, family=None):
        identifier(asset_id); require(self.get("deleted_asset",asset_id,conn,True) is None,"Purged Asset ID is reserved for history"); require(template_id in self.templates, "Unknown template")
        require(isinstance(name_zh, str) and 0 < len(name_zh) <= 160, "Invalid display name")
        template = resolve_template(self.templates[template_id],family)
        require(state is None or state == "master" or state in template["structure"], "Unknown state/action")
        if set_id:
            group = self.get("set", set_id, conn)
            require(group["template_id"] == template_id and (state==("effect" if group.get("kind")=="effect_collection" else "icon") and asset_id in group["asset_ids"] if group.get("kind") in ("static_collection","effect_collection") else state in ["master", *group["states"]]) and (group.get("family") or "default")==template["family"], "Asset Set mapping mismatch")
        value = {"asset_id": asset_id, "lifecycle_status":"active", "name_zh": name_zh, "template_id": template_id, "category": template["category"], "family":template["family"], "set_id": set_id, "state": state, "tags": tags or [], "versions": [], "current_approved_version": None, "created_at": now(), "updated_at": now(), "runtime_role":template["creation_policy"]["runtime_role"], **({"frame_count":1} if template["output_mode"]=="icon" else {})}
        self.put("asset", asset_id, value, conn, True)
        return value

    def create_set(self, set_id, name_zh, template_id, states, asset_prefix, labels=None, used_by="", family=None):
        identifier(set_id); identifier(asset_prefix)
        require(self.get("deleted_set",set_id,missing=True) is None,"Purged Set ID is reserved for history")
        require(template_id in self.templates, "Unknown template")
        require(states and len(set(states)) == len(states) and all(s in resolve_template(self.templates[template_id],family)["structure"] for s in states), "Invalid set states")
        if self.templates[template_id]["master_required"]:
            low, high = self.templates[template_id]["state_count"]
            require(low <= len(states) <= high, "Interior Set requires 4–6 states")
        with self.transaction() as conn:
            value = dict(set_id=set_id, name_zh=name_zh, template_id=template_id, states=states, asset_prefix=asset_prefix, labels=labels or {}, used_by=used_by, family=resolve_template(self.templates[template_id],family)["family"])
            self.put("set", set_id, value, conn, True)
            for state in ["master", *states]:
                self._create_asset(asset_prefix + "." + state, (labels or {}).get(state, state), template_id, set_id, state, [], conn, family)
        return value

    def creation_preview(self, template_id, name_zh, generation_scope=None, asset_names=None, generation_mode=None, family=None, machine_id=None, source_container=None, states=None, counts=None, collection_id=None, appearance_directions=None):
        from .collections import require_collection
        require_collection(self,collection_id)
        require(template_id in self.templates,"Unknown template")
        value=creation_spec(self.templates[template_id],name_zh,generation_scope,asset_names,generation_mode,family,machine_id,source_container,states,counts)
        looks=appearance.directions(template_id,[item['name_zh'] for item in value['asset_list']],appearance_directions)
        if template_id==appearance.TEMPLATE:
            for item in value['asset_list']:item['appearance_direction']=looks.get(item['name_zh'],'')
        generation_scope=value["generation_scope"]
        generation_mode=value["generation_mode"]
        kind="set" if generation_scope=="asset_set" else "asset"
        # ID availability does not need image/version histories. Match the lightweight
        # queries used by create_named, especially while mobile inputs issue previews.
        with self.connection() as conn:
            if not machine_id:
                occupied={r[0] for r in conn.execute("SELECT id FROM metadata WHERE kind IN (?,?)",(kind,"deleted_"+kind))}
                value["machine_id"]=available_id(value["machine_id"],occupied)
            if generation_scope=="asset_set" and (value["static"] or value["named_collection"]):
                occupied={r[0] for r in conn.execute("SELECT id FROM metadata WHERE kind IN ('asset','deleted_asset')")}
                for item in value["asset_list"]:
                    item["asset_id"]=available_id(suggested_id(self.templates[template_id]["creation_policy"]["asset_namespace"],value["machine_id"]+"\0"+item["name_zh"]),occupied);occupied.add(item["asset_id"])
        return value

    def create_named(self, template_id, name_zh, generation_scope=None, asset_names=None, generation_mode=None, family=None, machine_id=None, asset_ids=None, states=None, source_container=None, counts=None, collection_id=None, appearance_directions=None):
        value=creation_spec(self.templates[template_id],name_zh,generation_scope,asset_names,generation_mode,family,machine_id,source_container,states,counts)
        looks=appearance.directions(template_id,[item['name_zh'] for item in value['asset_list']],appearance_directions)
        if template_id==appearance.TEMPLATE:
            for item in value['asset_list']:item['appearance_direction']=looks.get(item['name_zh'],'')
        generation_scope=value["generation_scope"]
        generation_mode=value["generation_mode"]
        with self.transaction() as conn:
            from .collections import require_collection
            require_collection(self,collection_id,conn)
            kind="set" if generation_scope=="asset_set" else "asset"
            mid=value["machine_id"]
            if machine_id:require(self.get(kind,mid,conn,True) is None and self.get("deleted_"+kind,mid,conn,True) is None,"Duplicate/reserved stable ID")
            else:
                occupied={row[0] for row in conn.execute("SELECT id FROM metadata WHERE kind=?",(kind,))}
                occupied.update(r[0] for r in conn.execute("SELECT id FROM metadata WHERE kind=?",("deleted_"+kind,)))
                mid=available_id(mid,occupied)
            if generation_scope=="single_asset":
                a=self._create_asset(mid,name_zh,template_id,None,None,[],conn,value["family"])
                if template_id==appearance.TEMPLATE:a['appearance_direction']=looks.get(name_zh.strip(),'')
                if collection_id is not None:a["collection_id"]=collection_id
                a["generation_defaults"]=dict(source_container=value["source_container"],counts=value["frame_counts"],generation_scope="single_asset")
                self.put("asset",mid,a,conn);return a
            template=resolve_template(self.templates[template_id],value["family"])
            if not (value["static"] or value["named_collection"]):
                chosen=states or list(value["frame_counts"])
                require(chosen and len(set(chosen))==len(chosen) and all(a in template["structure"] for a in chosen),"Invalid states")
                if template["master_required"]:require(4<=len(chosen)<=6,"Interior Set requires 4–6 states")
                group=dict(set_id=mid,name_zh=name_zh,template_id=template_id,source_container=value["source_container"],sheet_semantics=value["sheet_semantics"],generation_defaults=dict(counts=value["frame_counts"]),generation_scope="asset_set",states=chosen,asset_prefix=suggested_id(template["creation_policy"]["asset_namespace"],mid),labels=template["creation_policy"]["action_labels_zh"],used_by="",family=value["family"])
                if collection_id is not None:group["collection_id"]=collection_id
                self.put("set",mid,group,conn,True)
                for action in ["master",*chosen]:self._create_asset(group["asset_prefix"]+"."+action,group["labels"].get(action,action),template_id,mid,action,[],conn,value["family"])
                return group
            items=value["asset_list"]
            if asset_ids is not None:require(isinstance(asset_ids,list) and len(asset_ids)==len(items),"Invalid advanced asset IDs")
            occupied={r[0] for r in conn.execute("SELECT id FROM metadata WHERE kind='asset'")}
            occupied.update(r[0] for r in conn.execute("SELECT id FROM metadata WHERE kind='deleted_asset'"))
            actual=[]
            for i,item in enumerate(items):
                proposed=asset_ids[i] if asset_ids is not None else suggested_id(template["creation_policy"]["asset_namespace"],mid+"\0"+item["name_zh"])
                aid=identifier(proposed) if asset_ids is not None else available_id(proposed,occupied)
                require(aid not in occupied,"Duplicate asset ID");occupied.add(aid);actual.append(dict(asset_id=aid,name_zh=item["name_zh"]))
            group=dict(set_id=mid,name_zh=name_zh,template_id=template_id,kind="effect_collection" if value["named_collection"] else "static_collection",generation_defaults=dict(counts=value["frame_counts"]),generation_scope="asset_set",generation_mode=generation_mode,source_container=value["source_container"],sheet_semantics=value["sheet_semantics"],family=value["family"],asset_ids=[a["asset_id"] for a in actual],runtime_role=value["runtime_role"])
            if collection_id is not None:group["collection_id"]=collection_id
            self.put("set",mid,group,conn,True)
            for item in actual:
                asset=self._create_asset(item["asset_id"],item["name_zh"],template_id,mid,"effect" if value["named_collection"] else "icon",[],conn,value["family"])
                if template_id==appearance.TEMPLATE:
                    asset['appearance_direction']=looks.get(item['name_zh'],'')
                    self.put('asset',asset['asset_id'],asset,conn)
                if value["named_collection"]:
                    asset["generation_defaults"]=dict(source_container="sheet",counts=value["frame_counts"],generation_scope="single_asset")
                    self.put("asset",asset["asset_id"],asset,conn)
            return group

    def edit_static_set(self,set_id,asset_list,generation_mode=None):
        from .sets import names,suggested_id
        require(isinstance(asset_list,list),"Invalid asset list")
        names([a.get("name_zh") for a in asset_list])
        with self.transaction() as conn:
            group=self.get("set",set_id,conn);require(group.get("status","active")=="active","Restore Asset Set before editing");require(group.get("kind") in ("static_collection","effect_collection"),"Only named collections have editable asset lists")
            mode=generation_mode or group["generation_mode"];require(mode in ("independent","sheet"),"Invalid generation mode")
            require(group.get("kind")!="effect_collection" or mode=="sheet","批量特效请使用素材表")
            submitted=[a.get("asset_id") for a in asset_list if a.get("asset_id")]
            require(len(set(submitted))==len(submitted) and set(submitted)<=set(group["asset_ids"]),"Invalid existing asset IDs")
            from .lifecycle import detach,audit
            for removed in set(group["asset_ids"])-set(submitted):
                previous=detach(self,removed,conn)
                audit(self,conn,"detach_asset","asset",removed,previous,"unassigned")
            ordered=[];occupied={r[0] for r in conn.execute("SELECT id FROM metadata WHERE kind IN ('asset','deleted_asset')")}
            for item in asset_list:
                aid=item.get("asset_id")
                if aid:
                    a=self.get("asset",aid,conn);a.update(name_zh=item["name_zh"].strip(),updated_at=now())
                    if 'appearance_direction' in item:
                        require(group['template_id']==appearance.TEMPLATE,'只有法宝素材支持外观方向')
                        a['appearance_direction']=appearance.direction(item['appearance_direction'])
                    self.put('asset',aid,a,conn)
                else:
                    aid=available_id(suggested_id(self.templates[group["template_id"]]["creation_policy"]["asset_namespace"],set_id+"\0"+item["name_zh"]),occupied);occupied.add(aid)
                    # Add membership before using the shared Asset validator.
                    group["asset_ids"].append(aid);self.put("set",set_id,group,conn)
                    asset=self._create_asset(aid,item["name_zh"].strip(),group["template_id"],set_id,"effect" if group.get("kind")=="effect_collection" else "icon",[],conn,group["family"])
                    if 'appearance_direction' in item:
                        require(group['template_id']==appearance.TEMPLATE,'只有法宝素材支持外观方向')
                        asset['appearance_direction']=appearance.direction(item['appearance_direction'])
                        self.put('asset',aid,asset,conn)
                    if group.get("kind")=="effect_collection":
                        asset["generation_defaults"]=dict(source_container="sheet",counts=group["generation_defaults"]["counts"],generation_scope="single_asset")
                        self.put("asset",aid,asset,conn)
                ordered.append(aid)
            group.update(asset_ids=ordered,generation_mode=mode,source_container="sheet" if mode=="sheet" else "image_set");self.put("set",set_id,group,conn)
        return group

    def append_set_asset(self, set_id, name_zh):
        """Append against current membership; never submit a stale replacement list."""
        from .sets import names, suggested_id
        name = names([name_zh])[0]
        with self.transaction() as conn:
            group = self.get("set", set_id, conn)
            require(group.get("status", "active") == "active", "请先恢复素材组")
            require(group.get("kind") in ("static_collection", "effect_collection"), "此组使用固定动作/状态，请使用独立命名素材组")
            current_names = [self.get("asset", aid, conn)["name_zh"] for aid in group["asset_ids"]]
            names([*current_names, name])
            occupied = {r[0] for r in conn.execute("SELECT id FROM metadata WHERE kind IN ('asset','deleted_asset')")}
            aid = available_id(suggested_id(self.templates[group["template_id"]]["creation_policy"]["asset_namespace"], set_id + "\0" + name), occupied)
            group["asset_ids"].append(aid)
            self.put("set", set_id, group, conn)
            asset = self._create_asset(aid, name, group["template_id"], set_id, "effect" if group["kind"] == "effect_collection" else "icon", [], conn, group["family"])
            if group["kind"] == "effect_collection":
                asset["generation_defaults"] = dict(source_container="sheet", counts=group["generation_defaults"]["counts"], generation_scope="single_asset")
                self.put("asset", aid, asset, conn)
        return asset

    def rename(self, asset_id, name_zh, tags=None, appearance_direction=None):
        require(isinstance(name_zh, str) and 0 < len(name_zh) <= 160, "Invalid display name")
        with self.transaction() as conn:
            value = self.get("asset", asset_id, conn)
            value.update(name_zh=name_zh, updated_at=now())
            if appearance_direction is not None:
                require(value['template_id']==appearance.TEMPLATE,'只有法宝素材支持外观方向')
                value['appearance_direction']=appearance.direction(appearance_direction)
            if tags is not None:
                require(isinstance(tags, list) and all(isinstance(t, str) and len(t) <= 80 for t in tags), "Invalid tags")
                value["tags"] = tags
            self.put("asset", asset_id, value, conn)
        return value

    def specification(self,template_id,options=None,asset_id=None,set_id=None):
        self.templates=templates(json.loads(self.template_file.read_text()))
        require(template_id in self.templates,"Unknown template")
        options=options or {}
        with self.connection() as conn:
            for kind,key in [("asset",asset_id),("set",set_id)]:
                if key:
                    record=self.get(kind,key,conn)
                    require(record["template_id"]==template_id,"Specification template mismatch")
                    require((record.get("family") or "default")==options.get("family","default"),"Specification family mismatch")
            return self._frozen_spec(template_id,options,asset_id,set_id,conn)

    def _frozen_spec(self,template_id,options,asset_id,set_id,conn):
        if asset_id:
            from .lifecycle import asset_status
            require(asset_status(self.get("asset",asset_id,conn))=="active","Restore Asset before generating Prompt")
        if set_id:require(self.get("set",set_id,conn).get("status","active")=="active","Restore Asset Set before generating Prompt")
        opts=copy.deepcopy(options)
        a=self.get('asset',asset_id,conn) if asset_id else None
        group=self.get('set',set_id,conn) if set_id else None
        if a:
            opts={**a.get('generation_defaults',{}),**opts}
            if a.get('state'):
                opts['state']=a['state']
                if a['state']!='master':
                    opts['counts']={a['state']:opts.get('counts',{}).get(a['state'],resolve_template(self.templates[template_id],opts.get('family'))['structure'][a['state']][0])} if a['state']=='effect' and a.get('generation_defaults') else {a['state']:resolve_template(self.templates[template_id],opts.get('family'))['structure'][a['state']][0]}
                opts.setdefault('source_container','single_image' if self.templates[template_id]['output_mode']!='sprite_sheet' else 'image_set')
        elif group:
            opts={**group.get('generation_defaults',{}),**opts}
            opts.setdefault('generation_scope','asset_set')
            opts.setdefault('source_container',group.get('source_container') or ('sheet' if group.get('generation_mode')=='sheet' else 'image_set' if group.get('kind')=='static_collection' else 'sheet'))
            if group.get('states'):opts.setdefault('counts',{state:resolve_template(self.templates[template_id],opts.get('family'))['structure'][state][0] for state in group['states']})
        frozen=freeze_spec(self.templates[template_id],opts)
        if frozen['output_mode']=='icon':
            if a:items=[dict(asset_id=a['asset_id'],name_zh=a['name_zh'])];actual_set=a['set_id']
            elif group:
                require(group.get('kind')=='static_collection','请选择独立素材组')
                items=[dict(asset_id=aid,name_zh=self.get('asset',aid,conn)['name_zh']) for aid in group['asset_ids']];actual_set=set_id
            else:items=[];actual_set=None
            if items and template_id==appearance.TEMPLATE:
                items=appearance.frozen_items(self,items,conn)
                if 'appearance_direction' in opts:
                    require(len(items)==1,'素材组请逐件保存外观方向，不能用一条说明覆盖整组')
                    items[0]['appearance_direction']=appearance.direction(opts['appearance_direction'])
            if items:frozen=static_spec(frozen,items,actual_set,opts.get('source_container',frozen['source_container']),'single_asset' if a else 'asset_set')
        elif group and not a and group.get('kind')=='effect_collection' and frozen['output_mode']!='master':
            items=[dict(asset_id=aid,name_zh=self.get('asset',aid,conn)['name_zh']) for aid in group['asset_ids']]
            frozen=freeze_container(frozen,opts,items,set_id)
        elif group and group.get('kind')!='effect_collection' and frozen['output_mode']!='master':
            items=[]
            if group.get('states'):
                for state in frozen['row_order']:
                    aid=group['asset_prefix']+'.'+state
                    record=self.get('asset',aid,conn)
                    items.append(dict(asset_id=aid,name_zh=record['name_zh'],action=state))
            if frozen['sheet_semantics'] not in FRAME_SEMANTICS and items:
                frozen=freeze_container(frozen,opts,items,set_id)
            elif items:
                # Legacy action-per-Asset sets remain addressable, no historical rewrite.
                by_action={i['action']:i for i in items}
                frozen['asset_ids']=[i['asset_id'] for i in items];frozen['asset_order']=frozen['asset_ids'];frozen['asset_count']=len(items)
                for cell in frozen['cell_mapping']:cell.update(asset_id=by_action[cell['action']]['asset_id'],name_zh=by_action[cell['action']]['name_zh'])
                frozen['layout_spec']['cell_mapping']=copy.deepcopy(frozen['cell_mapping'])
        elif a and frozen['output_mode']!='master':
            frozen=freeze_container(frozen,{**opts,'generation_scope':'single_asset'},set_id=a.get('set_id'),asset_id=asset_id)
        return frozen

    def prompt(self, template_id, options, asset_id=None, set_id=None, edited_text=None):
        self.templates = templates(json.loads(self.template_file.read_text()))
        require(template_id in self.templates, "Unknown template")
        with self.transaction() as conn:
            for kind, key in [("asset", asset_id), ("set", set_id)]:
                if key:
                    target=self.get(kind,key,conn)
                    require(target["template_id"] == template_id, "Prompt template mismatch")
                    require(not target.get("family") or target["family"]==options.get("family","default"),"Prompt asset family mismatch")
            master = options.get("master_reference")
            master_version = None
            if master:
                asset = self.get("asset", master, conn)
                require(asset["current_approved_version"] is not None and (asset["state"]=="master" or resolve_template(self.templates[template_id],options.get("family"))["output_mode"]=="icon" and asset["template_id"]==template_id), "Master/reference must be approved and selected")
                target_set = set_id or (self.get("asset", asset_id, conn)["set_id"] if asset_id else None)
                require(not target_set or asset["set_id"] == target_set or resolve_template(self.templates[template_id],options.get("family"))["output_mode"]=="icon", "Master belongs to another Asset Set")
                master_version = asset["current_approved_version"]
            frozen = self._frozen_spec(template_id,options,asset_id,set_id,conn)
            context, fingerprints = project_rules(frozen["template_snapshot"])
            text = compile_prompt(self.templates[template_id], options, context, frozen)
            require(edited_text is None or isinstance(edited_text, str) and 0 < len(edited_text) <= 24000, "Invalid edited prompt")
            value = dict(prompt_id=uid(), template_id=template_id, asset_id=asset_id, set_id=set_id, created_at=now(), options=copy.deepcopy(options), frozen_spec=frozen, template_version=frozen["template_version"], master_version=master_version, rule_fingerprints=fingerprints, template_snapshot=copy.deepcopy(self.templates[template_id]), text=edited_text if edited_text is not None else text, compiled_text=text)
            self.put("prompt", value["prompt_id"], value, conn, True)
        return value

    def upload(self, filename, data, template_id, set_id=None, prompt_id=None, tags=None, spec_options=None):
        require(template_id in self.templates, "Unknown template")
        image = decode(data, filename)
        self.templates = templates(json.loads(self.template_file.read_text()))
        with self.transaction() as conn:
            if set_id:
                require(self.get("set",set_id,conn).get("status","active")=="active","Restore Asset Set before uploading")
                require(self.get("set", set_id, conn)["template_id"] == template_id, "Source Set template mismatch")
            frozen = None
            legacy_template = None
            if prompt_id:
                prompt = self.get("prompt", prompt_id, conn)
                require(prompt["template_id"] == template_id and (not prompt["set_id"] or prompt["set_id"] == set_id), "Source prompt relation mismatch")
                frozen = copy.deepcopy(prompt.get("frozen_spec"))
                require(not frozen or not frozen.get("asset_list") or frozen["generation_mode"]=="sheet" or frozen["asset_count"]==1,"逐张独立图片请先从素材组选择一个素材，关联该素材的提示词")
                if frozen and frozen.get('source_container')=='image_set':
                    require(len(frozen.get('asset_ids',[]))<=1 and (frozen.get('asset_list') or len(frozen['frame_counts'])==1),'多张独立图片请为本次上传选择一个素材 / 状态 / 动作提示词')
                if frozen is None:
                    legacy_template = copy.deepcopy(prompt["template_snapshot"])
            else:
                frozen = self._frozen_spec(template_id,spec_options or {},None,set_id,conn)
            if frozen and canonical_spec(frozen).get('source_container')=='image_set':
                require(len(frozen.get('asset_ids',[]))<=1 and (frozen.get('asset_list') or len(frozen['frame_counts'])==1),'多张独立图片请为本次上传选择一个素材 / 状态 / 动作提示词')
            source_id = uid(); extension = filename.rsplit(".", 1)[-1].lower()
            relative = "source/files/" + source_id + "." + extension
            self.atomic(relative, data)
            value = dict(source_id=source_id, original_name=filename, file=relative, sha256=hashlib.sha256(data).hexdigest(), width=image.width, height=image.height, template_id=template_id, set_id=set_id, prompt_id=prompt_id, frozen_spec=frozen, specification_origin="prompt_snapshot" if prompt_id else "import_snapshot", legacy_template_snapshot=legacy_template, tags=tags or [], created_at=now())
            self.put("source", source_id, value, conn, True)
        return value

    def source_image(self, source):
        require(not source.get("file_deleted_at"), "原图已清理，重新切图请上传新原图；现有切块和运行素材仍可使用。")
        data = self.path(source["file"]).read_bytes()
        require(hashlib.sha256(data).hexdigest() == source["sha256"], "Source changed since import")
        return decode(data, source["original_name"])

    def source_spec(self, source):
        """Prefer source-frozen rules. Historical records retain honest legacy provenance."""
        if source.get("frozen_spec"):
            return copy.deepcopy(source["frozen_spec"])
        if source.get("prompt_id"):
            prompt=self.get("prompt",source["prompt_id"])
            if prompt.get("frozen_spec"): return copy.deepcopy(prompt["frozen_spec"])
            return dict(legacy=True,template_snapshot=copy.deepcopy(prompt["template_snapshot"]),frame_counts=copy.deepcopy(prompt["options"].get("counts",{a:prompt["template_snapshot"]["structure"][a][0] for a in prompt["template_snapshot"]["default_actions"]})))
        if source.get("legacy_template_snapshot"):
            return dict(legacy=True,template_snapshot=copy.deepcopy(source["legacy_template_snapshot"]))
        raise AssetError("Historical Source has no frozen specification; explicitly bind a template before import")

    def bind_source_spec(self, source_id, options=None):
        with self.transaction() as conn:
            source=self.get("source",source_id,conn)
            require(not source.get("frozen_spec") and not source.get("prompt_id"), "Source specification is already frozen")
            self.templates=templates(json.loads(self.template_file.read_text()))
            source["frozen_spec"]=freeze_spec(self.templates[source["template_id"]],options or {})
            source["specification_origin"]="explicit_legacy_import_snapshot"
            self.put("source",source_id,source,conn)
        return source

    def source_template(self, source):
        return self.source_spec(source)["template_snapshot"]

    def validate_source_mapping(self, source, regions, counts):
        spec=canonical_spec(self.source_spec(source))
        mapping(spec['template_snapshot'],regions,counts)
        if not spec.get('legacy'):
            require(all(a in spec['frame_counts'] and n==spec['frame_counts'][a] for a,n in counts.items()),'Mapping must match frozen Prompt action counts')
            if spec.get('asset_list') or spec.get('asset_ids'):
                expected={cell_key(c) for c in spec['cell_mapping']}
                require(all(cell_key(r) in expected for r in regions),'Cell belongs to another Asset / action / state')
                if spec.get('asset_list'):
                    require(len(regions)==1 and counts=={regions[0]['action']:1},'独立状态 / 素材每项只允许一张图片')

    def auto_locate(self, source_id, contours=False):
        from .geometry import locate
        source=self.get('source',source_id);spec=canonical_spec(self.source_spec(source))
        require(spec.get('source_container')=='sheet','自动定位需要素材表及冻结Cell Mapping')
        require(type(contours) is bool,'Invalid contour option')
        if contours and spec.get('sheet_semantics')!='effect_frames':
            from .contours import locate_contours
            result=locate_contours(self.source_image(source),spec)
        else:
            image=self.source_image(source);result=locate(image,spec)
            # Disconnected fragments and overlapping rectangle envelopes may still
            # have a valid layout-guided contour. Its own ambiguity guards apply.
            if spec.get('asset_list') and result['status']=='FAILED':
                from .contours import locate_contours
                candidate=locate_contours(image,spec)
                if candidate['status']=='NEEDS_REVIEW':
                    result=candidate;result['automatic_contour_fallback']=True
                    result['message']='主体矩形定位不确定，已改用轮廓建议。'+result['message']
        return dict(result,source_id=source_id,source_sha256=source['sha256'])

    def plan(self, source_id, counts=None, mode='grid', options=None, regions=None, detection=None):
        source=self.get('source',source_id);spec=canonical_spec(self.source_spec(source));image=self.source_image(source)
        require(mode in ('grid','manual','independent','auto'),'Unknown import mode')
        counts=counts if counts is not None else copy.deepcopy(spec['frame_counts'])
        if mode=='grid':
            options=grid_options(spec,options) if not spec.get('legacy') else options;require(options is not None,'Legacy Source requires explicit grid geometry')
            rects=grid(image.width,image.height,options)
            if not regions:
                if not spec.get('legacy'):regions=sheet_regions(spec,options)
                else:
                    require(options['rows']==len(counts) and all(n<=options['columns'] for n in counts.values()),'Grid rows/actions or columns/frames mismatch')
                    regions=[dict(action=a,frame=f,rect=rects[row*options['columns']+f-1]) for row,(a,n) in enumerate(counts.items()) for f in range(1,n+1)]
                regions=[r for r in regions if r['action'] in counts]
        elif mode=='independent':
            cells=[c for c in spec.get('cell_mapping',[]) if c['action'] in counts]
            require(len(cells)==1 or sum(counts.values())==1 and not spec.get('asset_list'),'多张独立图片请关联单项 / 单动作提示词；不能将多个Cell当成一张图片')
            cell=cells[0] if len(cells)==1 else dict(action=next(iter(counts)),frame=1)
            regions=[dict(cell,rect=[0,0,image.width,image.height])]
        regions=copy.deepcopy(regions or [])
        if len(spec.get('asset_ids',[]))==1:
            for r in regions:r.setdefault('asset_id',spec['asset_ids'][0])
        if spec.get('asset_list') or spec.get('asset_ids') or mode=='auto':
            plan=self.sheet_plan(source,spec,image,regions,mode,options,counts)
        else:
            self.validate_source_mapping(source,regions,counts)
            self._validate_rects(image,regions,mode,options)
            plan=dict(source_id=source_id,source_sha256=source['sha256'],counts=counts,mode=mode,regions=regions,grid_spec=options if mode=='grid' else None)
        if detection:
            require(detection.get('source_sha256')==source['sha256'],'Stale geometry detection')
            plan['detection']={k:detection.get(k) for k in ('algorithm','status','foreground_method','detected_count')}
        return plan

    def _validate_rects(self,image,regions,mode,geometry):
        require(0<len(regions)<=256,'Invalid component count')
        require(sum(r['rect'][2]*r['rect'][3] for r in regions)<=16*1024*1024,'Total slice area exceeds limit')
        for r in regions:
            validate_selection(r,image.width,image.height)
            require(not r.get('polygon') or mode in ('manual','auto'),'多边形只能用于人工或自动定位裁切')
        if mode=='auto' or any(r.get('polygon') for r in regions):
            require(not any(selections_intersect(a,b,image.width,image.height) for i,a in enumerate(regions) for b in regions[i+1:]),'自动定位裁切框不能重叠；请调整边界')
        if mode=='grid':
            cells=grid(image.width,image.height,geometry)
            require(all(r['rect'] in cells for r in regions) and len({tuple(r['rect']) for r in regions})==len(regions),'Invalid grid cells')

    def sheet_plan(self,source,spec,image,regions,mode,geometry=None,counts=None):
        spec=canonical_spec(spec);counts=counts or spec['frame_counts']
        require(mode in ('grid','manual','independent','auto'),'Unknown import mode')
        expected=[cell_key(c) for c in spec['cell_mapping'] if c['action'] in counts]
        actual=[cell_key(r) for r in regions]
        require(len(set(actual))==len(actual) and set(actual)==set(expected),'映射必须覆盖全部冻结Cell，且Asset / 动作 / 帧不得重复')
        geometry=grid_options(spec,geometry)
        self._validate_rects(image,regions,mode,geometry)
        return dict(source_id=source['source_id'],source_sha256=source['sha256'],counts=counts,mode=mode,regions=copy.deepcopy(regions),sheet_mapping=True,static_collection=bool(spec.get('asset_list')),sheet_semantics=spec.get('sheet_semantics'),grid_spec=copy.deepcopy(geometry))

    def static_plan(self,source,spec,image,regions,mode,geometry):
        # Compatibility method for callers; same Sheet validation and geometry.
        return self.sheet_plan(source,spec,image,regions,mode,geometry)

    def import_static_set(self,plan,confirmed=False):
        return self.import_sheet(plan,confirmed)

    def import_sheet(self,plan,confirmed=False):
        require(confirmed is True,'Preview must be explicitly confirmed')
        with self.transaction() as conn:
            source=self.get('source',plan['source_id'],conn);spec=canonical_spec(self.source_spec(source))
            self.sheet_plan(source,spec,self.source_image(source),plan['regions'],plan['mode'],plan.get('grid_spec'),plan.get('counts'))
            require(plan['source_sha256']==source['sha256'],'Stale slice plan')
            ids=list(dict.fromkeys(r.get('asset_id') for r in plan['regions']))
            require(all(ids),'Source尚未绑定正式素材，请先选择目标素材')
            result=[]
            for aid in ids:
                subset=copy.deepcopy(plan);subset['regions']=[r for r in plan['regions'] if r['asset_id']==aid]
                subset['counts']={a:max(r['frame'] for r in subset['regions'] if r['action']==a) for a in dict.fromkeys(r['action'] for r in subset['regions'])}
                result.append(dict(asset_id=aid,version=self._import_version(aid,subset,False,conn)))
            source.setdefault('source_region_mappings',[]).append(dict(import_id=uid(),source_sha256=source['sha256'],mode=plan['mode'],expected_layout=dict(rows=spec['row_count'],columns=spec['column_count']),sheet_semantics=spec.get('sheet_semantics'),regions=copy.deepcopy(plan['regions']),detection=copy.deepcopy(plan.get('detection')),confirmed_at=now()))
            self.put('source',source['source_id'],source,conn);return result

    def import_version(self, asset_id, plan, confirmed=False, master=False):
        require(confirmed is True, "Preview must be explicitly confirmed")
        with self.transaction() as conn:
            return self._import_version(asset_id,plan,master,conn)

    def _import_version(self,asset_id,plan,master,conn):
        asset = self.get("asset", asset_id, conn)
        from .lifecycle import asset_status
        require(asset_status(asset)=="active","Restore Asset before importing")
        source = self.get("source", plan["source_id"], conn)
        require(source["template_id"] == asset["template_id"] and (not source["set_id"] or source["set_id"] == asset["set_id"] or (asset["set_id"] is None and asset_id in self.source_spec(source).get("asset_ids",[]))), "Source/asset mismatch")
        require(plan["source_sha256"] == source["sha256"], "Stale slice plan")
        image = self.source_image(source)
        if master:
            require(asset["state"] == "master" and len(plan["regions"]) == 1, "Invalid Master import")
        else:
            self.validate_source_mapping(source, plan["regions"], plan["counts"])
            require(asset["state"] is None or all(r["action"] == asset["state"] for r in plan["regions"]), "Asset state mapping mismatch")
        frozen=self.source_spec(source)
        if not master and (frozen.get("asset_list") or frozen.get("asset_ids")):require(all(r.get("asset_id")==asset_id for r in plan["regions"]),"Cell belongs to another Asset")
        if not frozen.get("legacy"):
            require(not asset.get("family") or asset["family"]==frozen["family"],"Source/asset family mismatch")
            asset["family"]=frozen["family"]
        version = len(asset["versions"]) + 1
        require(0 < len(plan["regions"]) <= 256, "Invalid component count")
        require(sum(r["rect"][2] * r["rect"][3] for r in plan["regions"]) <= 16 * 1024 * 1024, "Total slice area exceeds limit")
        files = []
        for region in plan["regions"]:
            part = crop_region(image, region)
            relative = ("master" if master else "components") + "/files/" + uid() + ".png"
            self.atomic(relative, png(part))
            files.append(dict(file=relative, source_id=source["source_id"], action=region["action"], frame=region["frame"], width=part.width, height=part.height, sha256=hashlib.sha256(self.path(relative).read_bytes()).hexdigest()))
        value = dict(version=version, source_id=source["source_id"], prompt_id=source["prompt_id"], frozen_spec=self.source_spec(source), source_native_size=[source["width"],source["height"]], art_status="draft", files=files, plan=plan, review={}, runtime=None, created_at=now())
        asset["versions"].append(value); asset["updated_at"] = now()
        self.put("asset", asset_id, asset, conn)
        return value

    def replace_frame(self, asset_id, base_version, frame_index, source_id, rect, confirmed=False):
        require(confirmed is True, "Replacement preview must be explicitly confirmed")
        from .model import integer
        with self.transaction() as conn:
            asset = self.get("asset", asset_id, conn)
            require(asset["state"] != "master", "Replace Master by importing a new Master version")
            base = self.version(asset, base_version)
            integer(frame_index, 0, len(base["files"]) - 1)
            source = self.get("source", source_id, conn)
            require(source["template_id"] == asset["template_id"] and (not source["set_id"] or source["set_id"] == asset["set_id"] or (asset["set_id"] is None and asset_id in self.source_spec(source).get("asset_ids",[]))), "Replacement source mismatch")
            base_spec=base.get("frozen_spec") or self.source_spec(self.get("source",base["source_id"],conn))
            replacement_spec=self.source_spec(source)
            if not base_spec.get("legacy") and not replacement_spec.get("legacy"):
                require(all(base_spec[k]==replacement_spec[k] for k in ("source_cell_size","runtime_profile","subject_logic_size","anchor")), "Replacement pixel profile mismatch")
            image = crop(self.source_image(source), rect)
            previous = base["files"][frame_index]
            require((image.width, image.height) == (previous["width"], previous["height"]), "Replacement must match frame viewport dimensions")
            for part in base["files"]:
                require(hashlib.sha256(self.path(part["file"]).read_bytes()).hexdigest() == part["sha256"], "Base component checksum mismatch")
            relative = "components/files/" + uid() + ".png"
            self.atomic(relative, png(image))
            value = copy.deepcopy(base)
            value.update(version=len(asset["versions"]) + 1, source_id=source_id, prompt_id=source["prompt_id"], parent_version=base_version, art_status="draft", review={}, runtime=None, created_at=now())
            value.pop("master_asset", None); value.pop("master_version", None)
            value["files"][frame_index] = dict(file=relative, source_id=source_id, action=previous["action"], frame=previous["frame"], width=image.width, height=image.height, sha256=hashlib.sha256(self.path(relative).read_bytes()).hexdigest())
            value["replacement"] = dict(frame_index=frame_index, rect=rect)
            asset["versions"].append(value); asset["updated_at"] = now()
            self.put("asset", asset_id, asset, conn)
        return value

    def master_plan(self, source_id, rect=None):
        source = self.get("source", source_id)
        rect = rect or [0, 0, source["width"], source["height"]]
        rectangle(rect, source["width"], source["height"])
        return dict(source_id=source_id, source_sha256=source["sha256"], regions=[dict(action="master", frame=1, rect=rect)], counts={"master":1}, mode="independent")

    def version(self, asset, version):
        require(type(version) is int and 1 <= version <= len(asset["versions"]), "Unknown version")
        return asset["versions"][version - 1]

    def review(self, asset_id, version, status, checklist=None):
        with self.transaction() as conn:
            return self._review(asset_id,version,status,checklist,conn)

    def _review(self, asset_id, version, status, checklist=None, conn=None):
        require(status in ("needs_review", "approved", "deprecated"), "Invalid Art Status transition")
        asset = self.get("asset", asset_id, conn); value = self.version(asset, version)
        from .lifecycle import asset_status
        require(status=="deprecated" or asset_status(asset)=="active","Restore Asset before review")
        old = value["art_status"]
        require(status in {"draft":["needs_review", "deprecated"], "needs_review":["approved", "deprecated"], "approved":["deprecated"], "deprecated":[]}[old], "Invalid Art Status transition")
        if status == "approved":
            checks = REVIEW + (INTERIOR_REVIEW if self.source_template(self.get("source",value["source_id"],conn))["master_required"] and asset["state"] != "master" else [])
            require(checklist and all(checklist.get(k) is True for k in checks), "All manual review checks required")
            if self.source_template(self.get("source",value["source_id"],conn))["master_required"] and asset["state"] != "master":
                group = self.get("set", asset["set_id"], conn) if asset["set_id"] else None
                require(group is not None, "Interior state requires Asset Set Master")
                base = self.get("asset", group["asset_prefix"] + ".master", conn)
                require(base["current_approved_version"] is not None, "Approve and select Master first")
                value["master_asset"] = base["asset_id"]
                value["master_version"] = base["current_approved_version"]
            self.source_image(self.get("source", value["source_id"], conn))
            require(all(self.path(f["file"]).is_file() and hashlib.sha256(self.path(f["file"]).read_bytes()).hexdigest() == f["sha256"] for f in value["files"]), "Missing or corrupt Component")
            require(bool(value["files"]),"Cannot approve a version with no valid Components")
            value["review"] = dict(checklist=checklist, reviewed_at=now())
            value["approved_at"]=now();value["approved_by"]="authenticated_operator"
        value.setdefault("review_history",[]).append(dict(from_status=old,to_status=status,at=now(),source="advanced_review"))
        value["art_status"] = status
        if status == "deprecated":
            if asset["current_approved_version"] == version:
                asset["current_approved_version"] = None
            published = json.loads(self.path("manifest.json").read_text())["assets"].get(asset_id)
            if published and published["version"] == version:
                self._remove_manifest(asset_id)
        self.put("asset", asset_id, asset, conn)
        return value

    def lifecycle_prepare(self,kind,key,operation):
        from .lifecycle import prepare
        return prepare(self,kind,key,operation)

    def lifecycle_apply(self,**options):
        from .lifecycle import apply
        return apply(self,**options)

    def deprecate_asset(self,asset_id):
        from .lifecycle import deprecate
        with self.transaction() as conn:return deprecate(self,asset_id,conn)

    def select(self, asset_id, version):
        with self.transaction() as conn:
            return self._select(asset_id,version,conn)

    def _select(self, asset_id, version, conn=None):
        asset = self.get("asset", asset_id, conn)
        from .lifecycle import asset_status
        require(asset_status(asset)=="active","Deprecated Asset cannot be selected")
        require(self.version(asset, version)["art_status"] == "approved", "Select approved version only")
        asset["current_approved_version"] = version
        self.put("asset", asset_id, asset, conn)
        # A selection does not overwrite the published game version; Publish is explicit.
        return asset

    def build(self, asset_id, version, width=None, height=None, format_name="png", allow_non_integer=False, export_policy=None):
        with self.transaction() as conn:
            return self._build(asset_id,version,width,height,format_name,allow_non_integer,conn,export_policy)

    def _build(self, asset_id, version, width=None, height=None, format_name="png", allow_non_integer=False, conn=None, export_policy=None):
        asset = self.get("asset", asset_id, conn); value = self.version(asset, version)
        from .lifecycle import asset_status
        require(asset_status(asset)=="active","Deprecated Asset cannot build Runtime")
        require(value["art_status"] == "approved" and asset["state"] != "master", "Only approved non-Master assets may build runtime")
        spec=value.get("frozen_spec") or self.source_spec(self.get("source",value["source_id"],conn))
        if export_policy is None:
            export_policy=default_export_policy(self.templates[asset["template_id"]],spec)
        spec,export_origin=export_spec(self.templates[asset["template_id"]],spec,export_policy)
        profile=None if spec.get("legacy") else spec["runtime_profile"]
        if profile:
            target=profile["frame_size"]
            require((width is None or width==target[0]) and (height is None or height==target[1]), "Runtime dimensions must match frozen profile")
            width,height=target
        from .model import integer
        integer(width, 1, 4096); integer(height, 1, 4096)
        require(len(value["files"]) * width * height <= 16 * 1024 * 1024, "Total runtime frame area exceeds limit")
        if export_policy=='player_combat_profile':
            # Separate action assets share one scale, keeping the same actor size and feet.
            related=[asset]
            if asset.get('set_id'):
                related=[json.loads(body) for (body,) in conn.execute("SELECT body FROM metadata WHERE kind='asset'") if json.loads(body).get('set_id')==asset['set_id']]
            sizes=[(f['width'],f['height']) for a in related if a.get('current_approved_version') for f in self.version(a,a['current_approved_version'])['files']]
            spec['actor_scale']=min(profile['subject_logic_size'][0]/max(w for w,h in sizes),profile['subject_logic_size'][1]/max(h for w,h in sizes),1)
        outputs = []
        for component in value["files"]:
            content = self.path(component["file"]).read_bytes()
            require(hashlib.sha256(content).hexdigest() == component["sha256"], "Component checksum mismatch")
            with Image.open(io.BytesIO(content)) as image:
                if profile:
                    from .images import profiled_runtime
                    data=profiled_runtime(image,spec,format_name,allow_non_integer,subject_region=value["plan"]["mode"] in ("auto","manual"))
                else:
                    data = runtime(image, width, height, format_name, allow_non_integer)
            relative = "runtime/" + asset_id + "/v" + str(version) + "/" + uid() + "." + format_name
            self.atomic(relative, data)
            outputs.append(dict(file=relative, action=component["action"], frame=component["frame"], width=width, height=height, sha256=hashlib.sha256(data).hexdigest()))
        history=value.setdefault("runtime_build_history",[])
        if value.get("runtime") and not any(b.get("files")==value["runtime"]["files"] for b in history):
            previous=copy.deepcopy(value["runtime"]);previous.setdefault("build_version",len(history)+1);previous.setdefault("export_origin",{"policy":"frozen"});history.append(previous)
        value["runtime"] = dict(build_version=len(history)+1,export_origin=export_origin,source_region_policy="fit_subject_region" if spec.get("asset_list") and value["plan"]["mode"] in ("auto","manual") else "frozen_cell", files=outputs, format=format_name, sampling="nearest", profile=copy.deepcopy(profile), subject_logic_size=copy.deepcopy(export_origin.get("subject_logic_size",spec.get("subject_logic_size"))), anchor=copy.deepcopy(spec.get("anchor")), non_integer_acknowledged=allow_non_integer, built_at=now())
        history.append(copy.deepcopy(value["runtime"]))
        self.put("asset", asset_id, asset, conn)
        return value["runtime"]

    def _remove_manifest(self, asset_id):
        document = json.loads(self.path("manifest.json").read_text())
        document["assets"].pop(asset_id, None)
        self.atomic("manifest.json", (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode())

    def publish(self):
        with self.transaction() as conn:
            # Linked workspaces can contain published Runtime without historical Catalog data.
            # Keep those entries until explicitly replaced or unpublished, never fabricate history.
            output = json.loads(self.path("manifest.json").read_text())["assets"] if self.merge_runtime else {}
            for (body,) in conn.execute("SELECT body FROM metadata WHERE kind='asset'"):
                asset = json.loads(body); selected = asset["current_approved_version"]
                from .lifecycle import asset_status
                if asset_status(asset)=="deprecated":
                    output.pop(asset["asset_id"], None)
                    continue
                if selected is None:
                    continue
                output.pop(asset["asset_id"], None)
                value = self.version(asset, selected)
                if value["art_status"] != "approved" or not value["runtime"]:
                    continue
                files = value["runtime"]["files"]
                if not files:
                    continue
                if not all(f["file"].startswith("runtime/") and self.path(f["file"]).is_file() and hashlib.sha256(self.path(f["file"]).read_bytes()).hexdigest() == f["sha256"] for f in files):
                    continue
                output[asset["asset_id"]] = dict(version=selected, build_version=value["runtime"].get("build_version"), export_origin=value["runtime"].get("export_origin"), files=files, format=value["runtime"]["format"], sampling="nearest", runtime_profile=value["runtime"].get("profile"), subject_logic_size=value["runtime"].get("subject_logic_size"), anchor=value["runtime"].get("anchor"))
            document = dict(schema_version=1, assets=output)
            self.atomic("manifest.json", (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode())
        self.clean_source_files()
        return document

    def clean_source_files(self, all_originals=False):
        from .source_cleanup import clean
        return clean(self, all_originals=all_originals)

    def completeness(self, set_id, group=None, assets=None):
        group = group if group is not None else self.get("set", set_id); states = {}
        lookup=lambda aid: assets.get(aid) if assets is not None else self.get("asset",aid,missing=True)
        if group.get("kind") in ("static_collection","effect_collection"):
            for aid in group["asset_ids"]:
                a=lookup(aid);require(a is not None,"Unknown asset reference");selected=a["current_approved_version"];v=self.version(a,selected) if selected else None
                states[aid]=dict(asset_id=aid,status=v["art_status"] if v else (a["versions"][-1]["art_status"] if a["versions"] else "missing_source"),complete=bool(a["versions"]),approved=any(x["art_status"]=="approved" for x in a["versions"]),runtime=a["runtime_ready"] if "runtime_ready" in a else bool(v and v["runtime"] and all(self.path(f["file"]).is_file() for f in v["runtime"]["files"])))
            return dict(set=group,slots=states,total=len(states),complete=sum(x["complete"] for x in states.values()),approved=sum(x["approved"] for x in states.values()),runtime=sum(x["runtime"] for x in states.values()))
        for state in ["master", *group["states"]]:
            asset = lookup(group["asset_prefix"] + "." + state)
            if asset is None or asset.get("set_id")!=set_id:
                states[state]=dict(asset_id=None,status="missing_source",complete=False,approved=False,runtime=False)
                continue
            selected = asset["current_approved_version"]
            value = self.version(asset, selected) if selected else None
            states[state] = dict(asset_id=asset["asset_id"], status=value["art_status"] if value else (asset["versions"][-1]["art_status"] if asset["versions"] else "missing_source"), complete=bool(asset["versions"]), approved=any(v["art_status"] == "approved" for v in asset["versions"]), runtime=asset["runtime_ready"] if "runtime_ready" in asset else bool(value and value["runtime"] and all(self.path(f["file"]).is_file() for f in value["runtime"]["files"])))
        return dict(set=group, slots=states, total=len(group["states"]), complete=sum(states[s]["complete"] for s in group["states"]), approved=sum(states[s]["approved"] for s in group["states"]), runtime=sum(states[s]["runtime"] for s in group["states"]))

    def search(self, query="", include_deprecated=False, **filters):
        result = []
        parents={g["set_id"]:g.get("collection_id") for g in self.list("set")} if filters.get("collection_id") else {}
        wanted_collection=filters.pop("collection_id",None)
        for asset in self.list("asset"):
            if wanted_collection and (parents.get(asset.get("set_id")) if asset.get("set_id") else asset.get("collection_id"))!=wanted_collection:continue
            from .lifecycle import asset_status
            status=asset_status(asset);asset["lifecycle_status"]=status
            if status=="deprecated" and not include_deprecated and filters.get("art_status")!="deprecated":continue
            latest = asset["versions"][-1] if asset["versions"] else None
            asset["art_status"] = "deprecated" if status=="deprecated" else latest["art_status"] if latest else "missing_source"
            selected = asset["current_approved_version"]
            approved = self.version(asset, selected) if selected else None
            asset["runtime_ready"] = bool(approved and approved["runtime"] and all(self.path(f["file"]).is_file() for f in approved["runtime"]["files"]))
            if query and query.casefold() not in json.dumps(asset, ensure_ascii=False).casefold():
                continue
            if filters.get("tag") and filters["tag"] not in asset["tags"]:
                continue
            if filters.get("version") and not any(str(v["version"]) == str(filters["version"]) for v in asset["versions"]):
                continue
            if any(str(asset.get(k, "")) != str(v) for k, v in filters.items() if k not in ("tag", "version") and v not in (None, "")):
                continue
            result.append(asset)
        return result

    def delete_source(self,source_id):
        p=self.lifecycle_prepare("source",source_id,"delete_source")
        return self.lifecycle_apply(confirmation_id=p["confirmation_id"],confirmed=True)

    def delete_build(self,asset_id,version):
        value=self.version(self.get("asset",asset_id),version)
        require(value["art_status"]=="deprecated","Only deprecated Runtime may be cleaned")
        p=self.lifecycle_prepare("asset",asset_id,"clean_runtime")
        return self.lifecycle_apply(confirmation_id=p["confirmation_id"],confirmed=True)

    def export_registry(self):
        return dict(collections=self.list("collection"),schema_version=1, assets=self.list("asset"), sets=self.list("set"), sources=self.list("source"), prompts=self.list("prompt"), review_previews=self.list("preview"), lifecycle_audit=self.list("audit"), deleted_assets=self.list("deleted_asset"), deleted_sets=self.list("deleted_set"))

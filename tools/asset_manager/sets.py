"""Shared creation and static collection specification; counts never stand for animation frames."""
import copy, hashlib
from .model import require, identifier, integer
from .specs import resolve_template

def is_static(template, family=None):
    return resolve_template(template,family)["output_mode"] == "icon"

def names(value):
    require(isinstance(value,list) and 1<=len(value)<=128,"素材清单需要1～128个独立素材")
    require(all(isinstance(n,str) and 0<len(n.strip())<=160 for n in value),"请填写每个素材的中文名称")
    result=[n.strip() for n in value]
    require(len(set(result))==len(result),"素材清单名称重复，请区分")
    return result

def suggested_id(namespace, name):
    identifier(namespace)
    return namespace+".a"+hashlib.sha256(name.encode("utf-8")).hexdigest()[:12]

def available_id(proposed, occupied):
    identifier(proposed)
    candidate=proposed;number=2
    while candidate in occupied:
        candidate=proposed+"."+str(number);number+=1
    identifier(candidate);return candidate

from .sheets import grid_shape, scope, choices, freeze_container

def creation_spec(template, name_zh, generation_scope=None, asset_names=None, generation_mode=None, family=None, machine_id=None, source_container=None, states=None, counts=None):
    require(isinstance(name_zh,str) and 0<len(name_zh.strip())<=160,"请填写中文名称")
    policy=template["creation_policy"];family=family or policy["default_asset_family"]
    selected=resolve_template(template,family);policy=selected["creation_policy"];static=selected["output_mode"]=="icon"
    generation_scope=scope(generation_scope or selected.get('default_generation_scope','single_asset'))
    opts=dict(family=family,generation_scope=generation_scope)
    if generation_mode:opts['generation_mode']=generation_mode
    if source_container:opts['source_container']=source_container
    if counts is not None:opts['counts']=counts
    elif states:opts['counts']={a:selected['structure'][a][0] for a in states if a in selected['structure']};require(len(opts['counts'])==len(states),'Invalid states')
    sc,container,semantics=choices(selected,opts)
    namespace=policy["set_namespace"] if sc=="asset_set" else policy["asset_namespace"]
    mid=identifier(machine_id) if machine_id else suggested_id(namespace,name_zh.strip())
    named_collection=sc=="asset_set" and selected["creation_policy"].get("named_frame_collection",False)
    require(not named_collection or container=="sheet","批量特效请使用一张素材表；每行一个特效，横向为动作帧")
    item_names=names(asset_names if sc=="asset_set" and (static or named_collection) else [name_zh])
    items=[dict(name_zh=n,asset_id=suggested_id(policy["asset_namespace"],mid+"\0"+n) if sc=="asset_set" else mid) for n in item_names]
    from .specs import freeze_spec
    spec=freeze_spec(template,opts)
    if static:spec=static_spec(spec,items,mid if sc=='asset_set' else None,container,sc)
    elif named_collection:spec=freeze_container(spec,opts,items,mid)
    return dict(name_zh=name_zh.strip(),template_id=template["template_id"],family=family,generation_scope=sc,generation_mode='sheet' if container=='sheet' else 'independent',source_container=container,sheet_semantics=semantics,machine_id=mid,asset_list=items,asset_count=len(items) if sc=="single_asset" or static or selected["default_sheet_semantics"] in ("action_frames","effect_frames") else len(spec["frame_counts"]),grid_rows=spec['row_count'],grid_columns=spec['column_count'],layout_spec=spec['layout_spec'],frame_counts=spec['frame_counts'],runtime_role=policy["runtime_role"],static=static,named_collection=named_collection,subject_logic_size=spec['subject_logic_size'],source_cell_size=spec['source_cell_size'],pixel_size_profile_id=spec['pixel_size_profile_id'])

def static_spec(spec, items, set_id=None, generation_mode="independent", generation_scope=None):
    require(spec["output_mode"]=="icon","Static collection requires icon template")
    names([a["name_zh"] for a in items]);ids=[identifier(a["asset_id"]) for a in items]
    require(len(set(ids))==len(ids),"Duplicate asset mapping")
    container={'independent':'image_set' if len(items)>1 else 'single_image','sheet':'sheet'}.get(generation_mode,generation_mode)
    return freeze_container(spec,dict(generation_scope=generation_scope or ('asset_set' if set_id else 'single_asset'),source_container=container),items,set_id)

def static_regions(spec, geometry=None):
    # Historical call name; no separate Icon Sheet geometry implementation.
    from .sheets import regions
    require(spec.get('cell_mapping'),'逐张独立图片请先选择一个素材生成提示词')
    return [dict(asset_id=r['asset_id'],action=r['action'],frame=r['frame'],rect=r['rect']) for r in regions(spec,geometry)]

"""Reuse artwork projections; never cache gameplay state or committed receipts."""
import hashlib,json,os,tempfile
from pathlib import Path
from src.rendering.game import present, BINDING_PATH, bindings, _battle, projection
from src.rendering.concepts import PATH as CONCEPT_PATH

@projection
def battle_artwork(assets,combat):return _battle(assets,assets.snapshot(),combat,bindings())

class DesktopArtwork:
    def __init__(self,assets,cache_path=None):
        self.assets=assets;self.key=None;self.value=None;self.battle_key=None
        self.cache_path=Path(cache_path) if cache_path else None;self.restore_pending=True
        self.paths=(assets.root/'manifest.json',BINDING_PATH,CONCEPT_PATH,
                    Path(__file__).parents[1]/'ui/pages/game/static/battle/combat_fx_profiles.json',
                    Path(__file__).parents[1]/'application/combat_effect_views.py',
                    Path(__file__).parents[1]/'data/combat/mechanics.json',
                    Path(__file__).parents[1]/'data/artifacts/content.json',
                    Path(__file__).parents[1]/'data/content_manifest.json',
                    *(Path(__file__).with_name(name) for name in ('desktop_artwork.py','game.py','assets.py','game_runtime.py','concepts.py','backdrop.py')))
    def invalidate(self):self.key=None;self.restore_pending=False
    def _restore(self,token):
        path=self.cache_path
        if path is None:return False
        try:
            if path.is_symlink() or path.parent.is_symlink() or path.stat().st_size>2*1024*1024:return False
            record=json.loads(path.read_text(encoding='utf-8'));body=record['body']
            if record['format']!=1 or hashlib.sha256(body.encode()).hexdigest()!=record['sha256']:return False
            saved=json.loads(body);value=saved['projection']
            fields={'schema_version','mode','icons','system_icons','resource_overview','equipment_icons','artifact_icons','technique_icons','building_icons','screens','battle'}
            if saved['key']!=token or type(value) is not dict or set(value)!=fields:return False
            if value['schema_version']!=1 or value['mode']!='icon' or type(value['resource_overview']) is not list:return False
            if any(type(value[k]) is not dict for k in fields-{'schema_version','mode','resource_overview'}):return False
            previous=saved['battle_key']
            if previous is not None and (not isinstance(previous,list) or len(previous)!=3 or any(not isinstance(v,str) for v in previous)):return False
            self.value=value;self.battle_key=tuple(previous) if previous is not None else None
            return True
        except (OSError,ValueError,TypeError,KeyError,AttributeError):return False
    def _persist(self,token):
        path=self.cache_path
        if path is None:return
        temporary=None
        try:
            if path.is_symlink() or path.parent.is_symlink():return
            body=json.dumps({'key':token,'battle_key':self.battle_key,'projection':self.value},ensure_ascii=False,separators=(',',':'))
            record=json.dumps({'format':1,'body':body,'sha256':hashlib.sha256(body.encode()).hexdigest()},ensure_ascii=False,separators=(',',':'))
            if len(record.encode())>2*1024*1024:return
            with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,prefix='.artwork-',delete=False) as output:
                temporary=output.name;output.write(record)
            os.replace(temporary,path)
        except OSError:pass  # Optional artwork cache must never block gameplay.
        finally:
            if temporary:
                try:Path(temporary).unlink(missing_ok=True)
                except OSError:pass
    def __call__(self,view):
        stamps=[]
        for path in self.paths:
            try:
                stat=path.stat();stamps.append((stat.st_mtime_ns,stat.st_size,path.is_symlink()))
            except OSError:stamps.append(None)
        combat=view.get('combat')
        signature=(tuple(sorted(view['holdings'])),
                   tuple(sorted({r['definition_id'] for r in view['buildings'].values()})),
                   bool(view.get('equipment')),bool(view.get('cultivation')),
                   tuple(sorted({(r['definition_id'],r['asset_id']) for r in view.get('equipment',{}).get('instances',[])})),
                   tuple((r['id'],r['asset_id']) for r in (view.get('techniques') or {}).get('catalog',[])),
                   bool(combat))
        battle_key=(combat['player']['asset_id'],combat['enemy']['asset_id'],combat['encounter']['background_asset_id']) if combat else None
        key=(tuple(stamps),signature)
        if self.key!=key:
            token=hashlib.sha256(json.dumps(key,separators=(',',':')).encode()).hexdigest()
            restored=self.restore_pending and self._restore(token)
            self.restore_pending=False;self.key=key
            if not restored:
                self.value=present(view,self.assets);self.battle_key=battle_key;self._persist(token)
        if self.battle_key!=battle_key:
            self.value={**self.value,'battle':{**self.value['battle'],'assets':battle_artwork(self.assets,combat)}}
            self.battle_key=battle_key
        # Runtime byte access still verifies paths and digests. Config changes or
        # explicit reload rebuild availability without retaining gameplay facts.
        return self.value

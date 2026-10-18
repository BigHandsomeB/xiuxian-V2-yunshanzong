"""Read-only icon-first game shell over Application views and approved RuntimeAssets.

Public entrypoints: present(view, assets), manifest(assets). No daily scene,
gameplay commands, clock reads, or simulation authority.
"""
import json
from contextvars import ContextVar
from functools import wraps
from .assets import observation
from pathlib import Path
from .asset_catalog import metadata
from .concepts import concepts

_projection = ContextVar("game_projection", default=None)

def projection(function):
    @wraps(function)
    def render(*args, **kwargs):
        token = _projection.set({"concepts": {r["asset_id"]: r for r in concepts()}, "icons": {}})
        try:
            with observation():return function(*args, **kwargs)
        finally:_projection.reset(token)
    return render

BINDING_PATH=Path(__file__).with_name('game-assets.json')
BINDINGS=json.loads(BINDING_PATH.read_text())

def bindings():
    # Presentation-only config; operators update IDs and reload Manifest without code/restart.
    try:
        if BINDING_PATH.is_symlink() or BINDING_PATH.stat().st_size>65536:return BINDINGS
        value=json.loads(BINDING_PATH.read_text())
        if value.get('schema_version')!=1:return BINDINGS
        for name in ('icons','building_icons','battle','combat_bindings','system_icons','combat_effects','battle_ui','artifact_icons'):
            if not isinstance(value.get(name,{} if name in ('system_icons','combat_effects','battle_ui','artifact_icons') else None),dict) or any(v is not None and not isinstance(v,str) for v in value.get(name,{}).values()):return BINDINGS
        if not {'background','player','enemy'}<=value['battle'].keys():return BINDINGS
        if not isinstance(value.get('combat_actions',{}),dict):return BINDINGS
        for actions in value.get('combat_actions',{}).values():
            if not isinstance(actions,dict) or any(not isinstance(a,str) for a in actions.values()):return BINDINGS
        return value
    except (OSError,ValueError,AttributeError):return BINDINGS
SCREENS = {
    'sect': {'mode': 'icon', 'implemented': True, 'read_only': True},
    'inventory': {'mode': 'icon', 'implemented': True, 'read_only': True},
    'disciples': {'mode': 'icon', 'implemented': True, 'read_only': True},
    'alchemy': {'mode': 'icon', 'implemented': True, 'read_only': False},
    'equipment': {'mode': 'icon', 'implemented': False, 'read_only': True},
    'cultivation': {'mode': 'icon', 'implemented': False, 'read_only': True},
    'battle': {'mode': 'scene', 'implemented': False, 'read_only': True},
}


def _icon(asset_id, assets, snapshot):
    scope=_projection.get()
    if scope is not None and asset_id in scope['icons']:return dict(scope['icons'][asset_id])
    concept=scope['concepts'].get(asset_id) if scope is not None else next((r for r in concepts() if r['asset_id']==asset_id),None)
    row=snapshot.get(asset_id,{}) if asset_id else {}
    origin=row.get('export_origin',{}) if isinstance(row,dict) else None
    if (not isinstance(origin,dict) or
        (concept and origin and (origin.get('template_id')!=concept['template_id'] or
            (origin.get('policy')!='current_item_profile' and origin.get('template_version')!=concept['template_version'])))):
        return {'asset_id':asset_id,'fallback':True,'asset':None}
    resolved = getattr(assets,'icon',assets.resolve)(asset_id, snapshot) if asset_id else None
    public = None
    if resolved:
        public = {key: resolved[key] for key in ('asset_id', 'width', 'height', 'version')}
        # Same RuntimeAssets digest route; this shell is mounted at /game.
        if resolved.get('nine_slice_insets'):public['nine_slice_insets']=resolved['nine_slice_insets']
        if resolved.get('content_box'):public['content_box']=resolved['content_box']
        public['url'] = '/game/runtime/' + resolved['url'].split('/play/runtime/', 1)[1]
    result={'asset_id': asset_id, 'fallback': public is None, 'asset': public}
    if scope is not None:scope['icons'][asset_id]=dict(result)
    return result


def _map(keys, bindings, assets, snapshot):
    return {key: _icon(bindings.get(key), assets, snapshot) for key in sorted(keys)}


def resource_overview(assets,snapshot,config=None):
    """Explicit presentation concepts; missing Inventory definitions never imply ownership."""
    config=config or bindings()
    rows={r['concept_id']:r for r in concepts()}
    order=['spirit_stone','spirit_stone_low','spirit_stone_mid','spirit_stone_high','spirit_stone_supreme','spirit_money','herb','spirit_wood','spirit_iron_ore','spirit_iron_ingot','wood','stone','grain','spring_water']
    result=[]
    for key in order:
        row=rows.get('concept.'+key)
        if not row:continue
        result.append({'concept_id':row['concept_id'],'name':config.get('resource_overview_names',{}).get(key,'灵谷种子' if key=='seed' else row['display_name_zh']),
            'gameplay_id':'seed_grain' if key=='seed' else row.get('gameplay_id'),
            'visual':_icon(row['asset_id'],assets,snapshot)})
    return result


def _battle(assets,snapshot,combat=None,config=None):
    config=config or bindings()
    bound=dict(config['battle'])
    if combat:
        identities={'player':combat['player']['asset_id'],'enemy':combat['enemy']['asset_id'],'background':combat['encounter']['background_asset_id'],'slash':'effect.combat.slash'}
        bound={role:config.get('combat_bindings',{}).get(identity) or identity for role,identity in identities.items()}
    result=_map(bound,bound,assets,snapshot)
    result['background']=result['background']['asset']
    result['sprites']={}
    result['ui']=_map(config.get('battle_ui',{}),config.get('battle_ui',{}),assets,snapshot)
    for role in (('player','enemy','slash') if combat else ('player','enemy')):
        asset_id=bound[role]
        if asset_id and hasattr(assets,'sprite'):
            sprite=assets.sprite(asset_id,snapshot,role=role) if combat else assets.sprite(asset_id,snapshot)
            if sprite is not None:
                if role=='player' and combat:
                    for action,aid in config.get('combat_actions',{}).get(combat['player']['asset_id'],{}).items():
                        part=assets.sprite(aid,snapshot,role='player')
                        if part and (part['width'],part['height'],part['anchor'])==(sprite['width'],sprite['height'],sprite['anchor']) and action in part['actions']:
                            sprite['actions'][action]=part['actions'][action]
                result['sprites'][asset_id]=sprite;result[role]['fallback']=False
    result['fx_config']=json.loads((Path(__file__).parents[1]/'ui/pages/game/static/battle/combat_fx_profiles.json').read_text())
    result['artifact_icons']=_map(config.get('artifact_icons',{}),config.get('artifact_icons',{}),assets,snapshot)
    result['effects']={}
    if combat and hasattr(assets,'sprite'):
        for key,aid in config.get('combat_effects',{}).items():
            part=assets.sprite(aid,snapshot,role='effect')
            if part:result['sprites'][aid]=part;result['effects'][key]={'asset_id':aid}
    return result


@projection
def present(view, assets):
    """One approved Manifest observation; never mutates the committed read model."""
    snapshot = assets.snapshot();config=bindings()
    resources = set(view['holdings']) | set(config['icons'])
    kinds = set(config['building_icons']) | {row['definition_id'] for row in view['buildings'].values()}
    combat=view.get('combat');screens={key:dict(value) for key,value in SCREENS.items()}
    if combat:screens['battle'].update(implemented=True,read_only=False)
    if view.get('equipment'):screens['equipment'].update(implemented=True,read_only=False)
    if view.get('cultivation'):screens['cultivation'].update(implemented=True,read_only=False)
    return {
        'schema_version': 1, 'mode': 'icon',
        'icons': _map(resources, config['icons'], assets, snapshot),
        'system_icons': _map(config.get('system_icons',{}),config.get('system_icons',{}),assets,snapshot),
        'resource_overview':resource_overview(assets,snapshot,config),
        'equipment_icons': {r['definition_id']:_icon(config['icons'].get(r['definition_id']) or r['asset_id'],assets,snapshot) for r in view.get('equipment',{}).get('instances',[])},
        'artifact_icons': _map(config.get('artifact_icons',{}),config.get('artifact_icons',{}),assets,snapshot),
        'technique_icons': {r['id']:_icon(r['asset_id'],assets,snapshot) for r in (view.get('techniques') or {}).get('catalog',[])},
        'building_icons': _map(kinds, config['building_icons'], assets, snapshot),
        'screens': screens,
        'battle': {'mode': 'scene', 'implemented': bool(combat), 'read_only': not bool(combat),
                   'assets': _battle(assets,snapshot,combat,config)},
    }


def catalog(assets, snapshot, config):
    projection=metadata(assets.root,snapshot)
    from src.core.validation import ValidationError
    from src.data.asset_notes import read_notes
    try:annotations=read_notes(assets.root)['assets']
    except (ValueError,OSError,ValidationError):annotations={}
    # Missing annotations are optional presentation data; gameplay keeps its authority.
    try:
        manual_rows=json.loads(Path(__file__).parents[1].joinpath('data/cultivation/techniques.json').read_text())['techniques']
        manual_by_asset={r['asset_id']:r for r in manual_rows if r.get('asset_id')}
    except (OSError,ValueError,KeyError):manual_by_asset={}
    by_asset={aid:row for row in concepts() for aid in [row['asset_id'],*row.get('alternate_asset_ids',[])]}
    # Both approved blood images refer to one concept; do not rewrite either asset identity.
    canonical={r['concept_id']:r['asset_id'] for r in concepts()}
    linked={aid:key for key,aid in config['icons'].items() if aid}
    for group in projection['groups']:
        rows=[]
        for item in group['items']:
            concept=by_asset.get(item['asset_id'])
            if concept:
                if item['asset_id']!=canonical[concept['concept_id']]:continue
                item.update({k:v for k,v in concept.items() if k not in ('asset_id','alternate_asset_ids')})
                item['name']=concept['display_name_zh']
                group['category']='concepts'
            item['annotation']=annotations.get(item['asset_id'],{})
            manual=manual_by_asset.get(item['asset_id'])
            if manual:
                item['planned_grade']={'white':'白阶','green':'绿阶','blue':'蓝阶','purple':'紫阶','orange':'橙阶','red':'红阶'}[manual['grade']]
                item['manual_function']={'movement':'身法槽','defense':'防御槽','special':'绝技槽','ultimate':'终极槽','passive':'内功槽'}[manual['category']]+'；装备后击杀获得经验，提升功法Lv与属性'
            item['visual']=_icon(item['asset_id'],assets,snapshot)
            item['runtime_status']='RUNTIME_READY' if item['visual']['asset'] else 'RUNTIME_UNAVAILABLE'
            item['gameplay_item_id']=linked.get(item['asset_id'])
            if item['gameplay_item_id'] in ('ore','ingot'):
                item['name']={'ore':'凡铁矿','ingot':'铁锭'}[item['gameplay_item_id']]
            if concept and concept['gameplay_status']=='NEEDS_CONFIRMATION':
                item['gameplay_status']=concept.get('note','素材语义待确认。')
            else:
                item['gameplay_status']='真实炼丹与修炼已开放' if item['gameplay_item_id']=='pill' else '已登记正式物品；不代表持有或玩法全部开放。' if item['gameplay_item_id'] else '素材已登记，玩法尚未开放。'
            if concept:item['category']=concept['category']
            rows.append(item)
        group['items']=rows
    return projection


@projection
def manifest(assets):
    """Injectable public binding/availability map and optional public catalog; no Source or raw file paths.

    manifest_available means a nonempty approved manifest snapshot. A listed
    binding can still be unavailable when RuntimeAssets rejects its runtime.
    """
    snapshot = assets.snapshot();config=bindings()
    maps = {key: _map(config[key], config[key], assets, snapshot)
            for key in ('icons', 'building_icons', 'battle','combat_bindings')}
    return {'schema_version': 1, 'manifest_available': bool(snapshot),
            'manifest_asset_count': len(snapshot), 'system_icons':_map(config.get('system_icons',{}),config.get('system_icons',{}),assets,snapshot), 'catalog':catalog(assets,snapshot,config), **maps}

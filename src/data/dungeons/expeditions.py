"""Versioned expedition content, independently configured from immutable thorn data."""
import json
from functools import lru_cache
from pathlib import Path
from src.core.state.envelope import freeze_json
from src.core.validation import ValidationError,integer
from src.data.registry import Definition,DefinitionKey
from src.data.items.resources import ResourceDefinition
from src.data.economy.definitions import EquipmentDefinition
from src.data.combat.definitions import MonsterDefinition,EncounterDefinition
from . import balance

IDS=('red_copper_mine','mist_marsh')
ALL_IDS=(*IDS,'cold_jade_cave')

@lru_cache(maxsize=3)
def content(dungeon_id):
    if dungeon_id not in ALL_IDS:raise ValidationError('unknown expedition')
    p=json.loads(Path(__file__).with_name(dungeon_id+'.json').read_text())
    if set(p)!={'schema_version','id','name','floors','elite_interval','unlock','background_asset_id','monsters','balance','reward','materials','equipment','loot'} or p['schema_version']!=1 or p['id']!=dungeon_id:raise ValidationError('invalid expedition package')
    integer(p['floors'],'floors',1);integer(p['elite_interval'],'elite interval',1)
    previous=('thorn_path',*ALL_IDS)[ALL_IDS.index(dungeon_id)]
    if p['floors']!=100 or p['elite_interval']!=10 or set(p['unlock'])!={'dungeon_id','cleared_floor'} or p['unlock']['dungeon_id']!=previous:raise ValidationError('invalid expedition structure/unlock')
    integer(p['unlock']['cleared_floor'],'unlock cleared floor',1)
    if p['unlock']['cleared_floor']>100:raise ValidationError('unlock floor out of range')
    balance.validate_content(p['balance'],dungeon_id+'-balance-v1')
    if len(p['monsters'])!=16 or len(p['materials'])!=12 or len(p['equipment'])!=12:raise ValidationError('expedition requires 16 enemies/12 materials/12 equipment')
    if [sum(m['tier']==t for m in p['monsters']) for t in ('normal','elite','boss')]!=[10,5,1] or set(p['balance']['profiles'])!={m['name'] for m in p['monsters']}:raise ValidationError('invalid expedition monster profiles')
    if len({m['id'] for m in p['monsters']})!=16 or len({m['asset_id'] for m in p['monsters']})!=16:raise ValidationError('duplicate expedition enemies')
    for m in p['monsters']:
        if set(m)!={'id','name','tier','order','asset_id','poison_milli'}:raise ValidationError('invalid expedition monster')
        integer(m['order'],'monster order');integer(m['poison_milli'],'poison')
    for tier in ('normal','elite','boss'):
        rows=[m for m in p['monsters'] if m['tier']==tier]
        if [m['order'] for m in rows]!=list(range(len(rows))):raise ValidationError('invalid expedition order')
    for k,n in p['reward'].items():DefinitionKey('resources',k);integer(n,'base reward',1)
    table=p['loot']
    if set(table)!={'version','roll_version','rates','normal_materials','elite_materials','theme_materials','beast_materials','rare_materials','extra_rates'} or table['version']!=dungeon_id+'-loot-v1' or table['roll_version']!=dungeon_id+'-roll-v1':raise ValidationError('invalid expedition loot version')
    if len(table['normal_materials'])!=10 or len(table['elite_materials'])!=5 or len(table['theme_materials'])!=4 or len(table['beast_materials'])!=3 or len(table['rare_materials'])!=4:raise ValidationError('invalid expedition loot pools')
    if set(table['rates'])!={'normal','elite','boss'}:raise ValidationError('invalid tier rates')
    for row in table['rates'].values():
        if set(row)!={'material_bps','material_quantity','equipment_bps'}:raise ValidationError('invalid tier drop rates')
        for k,n in row.items():
            integer(n,k,1 if k.endswith('quantity') else 0)
            if k.endswith('bps') and n>10000:raise ValidationError('drop probability exceeds 100%')
    if set(table['extra_rates'])!={'theme_bps','theme_quantity','beast_bps','beast_quantity','rare_bps','rare_quantity'}:raise ValidationError('invalid extra rates')
    for k,n in table['extra_rates'].items():
        integer(n,k,1 if k.endswith('quantity') else 0)
        if k.endswith('bps') and n>10000:raise ValidationError('drop probability exceeds 100%')
    # Immutable content can also be consumed by the existing decimal stat calculator.
    return freeze_json(p)

def register(registry,dungeon_type,*,cold_jade=False):
    shared=json.loads(Path(__file__).with_name('expedition_materials.json').read_text())
    if set(shared)!={'schema_version','materials'} or shared['schema_version']!=1:raise ValidationError('invalid common expedition materials')
    for row in shared['materials']:
        if set(row)!={'id','name','asset_id','grade','tier'}:raise ValidationError('invalid common material')
        registry.register(ResourceDefinition('resources',row['id'],row['name'],(),True,row['grade'],row['tier']))
    if cold_jade:
        for identity,name in (('cold_jade_ore','寒玉矿'),('ice_crystal_ore','冰晶矿')):
            registry.register(ResourceDefinition('resources',identity,name,(),True,1,'待定'))
    for did in ALL_IDS if cold_jade else IDS:
        p=content(did);table=p['loot']
        for row in p['materials']:
            if set(row)!={'id','name','asset_id','grade','tier','boss_only'} or type(row['boss_only']) is not bool:raise ValidationError('invalid expedition material')
            registry.register(ResourceDefinition('resources',row['id'],row['name'],(),True,row['grade'],row['tier']))
        for row in p['equipment']:
            if set(row)!={'id','name','slot','quality','stats','asset_id','sell_coins','salvage','boss_only','stat_ranges'} or type(row['boss_only']) is not bool:raise ValidationError('invalid expedition equipment')
            salvage=tuple(sorted(row['salvage'].items()))
            registry.register(EquipmentDefinition('equipment',row['id'],row['name'],tuple(DefinitionKey('resources',k) for k,_ in salvage),row['slot'],row['quality'],tuple(sorted(row['stats'].items())),row['asset_id'],row['sell_coins'],salvage,None,True,tuple((k,*v) for k,v in sorted(row['stat_ranges'].items()))))
        refs=tuple(DefinitionKey('resources',k) for k in (*table['normal_materials'],*table['elite_materials'],*table['theme_materials'],*table['beast_materials'],*table['rare_materials']))
        registry.register(Definition('loot',did,table['version'],refs))
        for version in (table['version'],):registry.register(Definition('loot_versions',version.replace('-','_'),version,refs))
        registry.register(Definition('equipment_rolls',table['roll_version'].replace('-','_'),table['roll_version'],tuple(DefinitionKey('equipment',r['id']) for r in p['equipment'])))
        ids=[];tiers=[];families={t:[m for m in p['monsters'] if m['tier']==t] for t in ('normal','elite','boss')}
        for f in range(1,p['floors']+1):
            tier='boss' if f==p['floors'] else 'elite' if f%p['elite_interval']==0 else 'normal'
            index=0 if tier=='boss' else (f//p['elite_interval']-1)%len(families[tier]) if tier=='elite' else (f-1-(f-1)//p['elite_interval'])%len(families[tier])
            m=families[tier][index];mid=f'{did}_v1_enemy_{f:03d}';eid=f'{did}_v1_{f:03d}'
            hp,attack,armor=balance.stats(p['balance'],f,tier,m['name']);reward=tuple(sorted(p['reward'].items()))
            registry.register(MonsterDefinition('monsters',mid,m['name'],tuple(DefinitionKey('resources',k) for k,_ in reward),hp,attack,armor,m['asset_id'],reward,m['poison_milli'],500 if tier=='elite' else 1000 if tier=='boss' else 0))
            registry.register(EncounterDefinition('encounters',eid,f'{p["name"]} · 第{f}层',(DefinitionKey('monsters',mid),DefinitionKey('players','hero')),mid,p['background_asset_id']))
            ids.append(eid);tiers.append(tier)
        registry.register(dungeon_type('dungeons',did,p['name'],tuple(DefinitionKey('encounters',k) for k in ids),tuple(ids),tuple(tiers)))

def owner(registry,encounter_id):
    if not isinstance(encounter_id,str):return None
    for did in ('thorn_path',*ALL_IDS):
        key=DefinitionKey('dungeons',did)
        if registry.contains(key):
            d=registry.lookup(key)
            if encounter_id in d.encounters or encounter_id in d.legacy_encounters:return did
    return None

def loot_version(registry,encounter_id):
    # Legacy loaders also carry loot without the current DungeonDefinition being registered yet.
    for did in ('thorn_path',*ALL_IDS):
        key=DefinitionKey('loot',did)
        if encounter_id.startswith(did+'_') and registry.contains(key):return registry.lookup(key).display_name
    return None

def valid_loot_version(registry,encounter_id,version):
    current=loot_version(registry,encounter_id)
    if current is None:return False
    versions=('thorn-loot-v1','thorn-loot-v2') if encounter_id.startswith('thorn_path_') else (current,)
    return type(version) is str and version in versions and registry.contains(DefinitionKey('loot_versions',version.replace('-','_')))

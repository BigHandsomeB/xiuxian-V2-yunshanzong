"""Validated content config and deterministic per-battle drops; no catalog/save writes."""
import json,hashlib
from functools import lru_cache
from pathlib import Path
from src.core.validation import ValidationError,integer
from src.data.registry import Definition,DefinitionKey,_fields
from src.data.items.resources import ResourceDefinition
from src.data.economy.definitions import EquipmentDefinition
from src.core.state.envelope import freeze_json

@lru_cache(maxsize=1)
def content():
    p=json.loads(Path(__file__).with_name('thorn_loot.json').read_text())
    _fields(p,('schema_version','version','equipment','materials','normal_materials','elite_materials','rates'))
    if p['schema_version']!=1 or p['version']!='thorn-loot-v1' or len(p['equipment'])!=12 or len(p['materials'])!=12:raise ValidationError('invalid thorn loot package')
    for rows in (p['equipment'],p['materials']):
        if len({r['id'] for r in rows})!=len(rows):raise ValidationError('duplicate thorn content')
    return freeze_json(p)

def register(registry,*,current=True):
    p=content()
    for row in p['materials']:
        _fields(row,('id','name','asset_id','grade','boss_only'))
        registry.register(ResourceDefinition('resources',row['id'],row['name'],(),True,row['grade']))
    ranges=json.loads(Path(__file__).with_name('equipment_ranges.json').read_text())
    if ranges['version']!='thorn-roll-v2' or set(ranges['equipment'])!={r['id'] for r in p['equipment']}:raise ValidationError('invalid roll range package')
    for row in p['equipment']:
        _fields(row,('id','name','slot','quality','stats','asset_id','sell_coins','salvage','boss_only'))
        salvage=tuple(sorted(row['salvage'].items()))
        registry.register(EquipmentDefinition('equipment',row['id'],row['name'],tuple(DefinitionKey('resources',k) for k,_ in salvage),row['slot'],row['quality'],tuple(sorted(row['stats'].items())),row['asset_id'],row['sell_coins'],salvage,None,True,tuple((k,*v) for k,v in sorted(ranges['equipment'][row['id']].items()))))
    if len(p['normal_materials'])!=10 or len(p['elite_materials'])!=5:raise ValidationError('invalid material source maps')
    refs=[DefinitionKey('resources',k) for k in (*p['normal_materials'],*p['elite_materials'])]
    for tier in ('normal','elite','boss'):
        r=p['rates'][tier];_fields(r,('material_bps','material_quantity','equipment_bps'))
        for k in ('material_bps','equipment_bps'):
            integer(r[k],k)
            if r[k]>10000:raise ValidationError('drop probability exceeds 100%')
        integer(r['material_quantity'],'material quantity',1)
    registry.register(Definition('loot','thorn_path','thorn-loot-v2',tuple(refs)))
    for version in ('thorn-loot-v1','thorn-loot-v2'):registry.register(Definition('loot_versions',version.replace('-','_'),version,tuple(refs)))

def roll(identity,salt):return int.from_bytes(hashlib.sha256((identity+'|'+salt).encode()).digest()[:8],'big')%10000

def _plan(registry,b):
    from .expeditions import ALL_IDS,owner
    did=owner(registry,b['encounter_id'])
    if did in ALL_IDS:return expedition_plan(registry,b,did)
    if not registry.contains(DefinitionKey('loot','thorn_path')) or b.get('loot_version') not in ('thorn-loot-v1','thorn-loot-v2') or not b['encounter_id'].startswith('thorn_path_'):return {'amounts':{},'equipment':None}
    # Immutable v1 salt and battle identity: retries, failed storage and offline replay
    # cannot reroll. Future table revisions must use a new version, not edit this salt.
    p=content();floor=int(b['encounter_id'].rsplit('_',1)[1]);tier='boss' if floor==100 else 'elite' if floor%10==0 else 'normal';r=p['rates'][tier];seed=b['battle_id']+'|'+b['loot_version'];amounts={}
    if roll(seed,'material')<r['material_bps']:
        keys=[v['id'] for v in p['materials'] if v['boss_only']] if tier=='boss' else [p['elite_materials'][(floor//10-1)%5]] if tier=='elite' else [p['normal_materials'][(floor-1-(floor-1)//10)%10]]
        amounts={k:r['material_quantity'] for k in keys}
    pool=[v['id'] for v in p['equipment'] if v['boss_only']==(tier=='boss')]
    chance=r['equipment_bps']
    equipment=pool[roll(seed,'choice')%len(pool)] if roll(seed,'equipment')<chance else None
    return {'amounts':amounts,'equipment':equipment}


def expedition_plan(registry,b,did):
    from .expeditions import content
    p=content(did);table=p['loot']
    if b.get('loot_version')!=table['version']:return {'amounts':{},'equipment':None}
    d=registry.lookup(DefinitionKey('dungeons',did));floor=d.encounters.index(b['encounter_id'])+1;tier=d.tiers[floor-1];r=table['rates'][tier];seed=b['battle_id']+'|'+b['loot_version'];amounts={}
    def award(k,n):amounts[k]=amounts.get(k,0)+n
    if roll(seed,'material')<r['material_bps']:
        keys=[v['id'] for v in p['materials'] if v['boss_only']] if tier=='boss' else [table['elite_materials'][(floor//p['elite_interval']-1)%len(table['elite_materials'])]] if tier=='elite' else [table['normal_materials'][(floor-1-(floor-1)//p['elite_interval'])%len(table['normal_materials'])]]
        for k in keys:award(k,r['material_quantity'])
    extra=table['extra_rates']
    for pool in (('theme','beast') if tier=='normal' else ('rare',)):
        if roll(seed,pool)<extra[pool+'_bps']:
            keys=table[pool+'_materials'];award(keys[roll(seed,pool+'_choice')%len(keys)],extra[pool+'_quantity'])
    pool=[v['id'] for v in p['equipment'] if v['boss_only']==(tier=='boss')]
    chance=r['equipment_bps']
    gear=pool[roll(seed,'choice')%len(pool)] if roll(seed,'equipment')<chance else None
    return {'amounts':amounts,'equipment':gear}


def equipment_roll_version(b):
    from .expeditions import ALL_IDS,content
    if b.get('loot_version') in ('thorn-loot-v2',):return 'thorn-roll-v2'
    for did in ALL_IDS:
        table=content(did)['loot']
        if b.get('loot_version') in (table['version'],):return table['roll_version']
    return None


def plan(registry,b):
    from .durability import amount
    result=_plan(registry,b)
    return {**result,'amounts':{k:amount(v,b,k) for k,v in result['amounts'].items()}}

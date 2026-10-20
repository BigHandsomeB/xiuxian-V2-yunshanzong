"""Nonstacking owned instances, protection, projection, deterministic evaluation."""
import hashlib
from collections.abc import Mapping
from src.core.state.envelope import freeze_json,thaw_json
from src.core.validation import ValidationError,NotFoundError,integer
from src.data.registry import DefinitionKey
from src.data.economy.definitions import EquipmentDefinition,EQUIPMENT_STATS,NEW_STAT_CAPS,COMBAT_AFFIX_RANGES,COMBAT_AFFIX_VERSION

AUDIT_LIMIT=512
STATS=EQUIPMENT_STATS
from src.data.combat.mechanics import CAPS as EFFECT_CAPS, ROLL_VERSION, CRAFT_ROLL_VERSION, equipment_ranges
RATE_CAPS={**EFFECT_CAPS,'crit_bps':3000,'accuracy_bps':10000,'evasion_bps':2500,'speed_bps':3000,'reflect_bps':3500,'poison_resist_bps':7500,'execute_bps':2000,**NEW_STAT_CAPS}
FIELDS={'definition_id','stats','affixes','owner','equipped','locked','favorite','tradeable','status','provenance','policy_epoch','evaluation'}
def definition(registry,key):
    d=registry.lookup(DefinitionKey('equipment',key))
    if not isinstance(d,EquipmentDefinition):raise ValidationError('equipment definition required')
    return d
def sale_price(registry,key):
    from src.systems.economy.valuation import equipment_sale
    return equipment_sale(registry,definition(registry,key))
def initial():return freeze_json({'instances':{},'slots':{},'audit':[],'latest_reward':None})
def validate(p,registry,save_id):
    if not isinstance(p,Mapping) or not {'instances','slots','audit'}<=set(p) or bool(set(p)-{'instances','slots','audit','latest_reward'}) or any(not isinstance(p[k],Mapping) for k in ('instances','slots')):raise ValidationError('equipment instances and slots required')
    if not isinstance(p['audit'],(list,tuple)) or len(p['audit'])>AUDIT_LIMIT:raise ValidationError('bounded equipment audit required')
    marker=p.get('latest_reward')
    if marker is not None:
        if not isinstance(marker,Mapping) or set(marker)!={'battle_id','instance_id','definition_id'} or any(type(v) is not str for v in marker.values()):raise ValidationError('invalid equipment reward presentation marker')
        definition(registry,marker['definition_id'])
    seen=set()
    for a in p['audit']:
        if not isinstance(a,Mapping) or set(a)!={'instance_id','definition_id','provenance','action','amounts','policy_epoch'} or a['instance_id'] in seen or a['action'] not in ('SELL','SALVAGE'):raise ValidationError('invalid equipment disposition audit')
        seen.add(a['instance_id']);definition(registry,a['definition_id']);integer(a['policy_epoch'],'audit policy epoch')
        if type(a['instance_id']) is not str or type(a['provenance']) is not str or not isinstance(a['amounts'],Mapping):raise ValidationError('invalid audit identity')
        for k,n in a['amounts'].items():registry.lookup(DefinitionKey('resources',k));integer(n,'audit quantity',1)
    for identity,row in p['instances'].items():
        if type(identity) is not str or not isinstance(row,Mapping) or not FIELDS<=set(row) or bool(set(row)-FIELDS-{'roll_version','enhancement','refinement'}):raise ValidationError('invalid equipment instance')
        d=definition(registry,row['definition_id'])
        if not isinstance(row['stats'],Mapping) or not row['stats']:raise ValidationError('actual equipment stats required')
        for k,n in row['stats'].items():
            if type(k) is not str:raise ValidationError('stat identity required')
            integer(n,'actual stat')
        if not isinstance(row['affixes'],(tuple,list)) or any(not isinstance(a,Mapping) for a in row['affixes']):raise ValidationError('affix metadata invalid')
        if any(a.get('version')==COMBAT_AFFIX_VERSION for a in row['affixes']) and not known_affixes(row,d):raise ValidationError('invalid saved combat affix')
        for k in ('equipped','locked','favorite','tradeable'):
            if type(row[k]) is not bool:raise ValidationError('boolean equipment state required')
        if row['owner'] not in ('inventory','player') or (row['owner']=='player')!=row['equipped'] or row['status']!='OWNED' or type(row['provenance']) is not str or row['evaluation'] not in ('NONE','PENDING','KEEP','SELL','SALVAGE','REVIEW'):raise ValidationError('invalid equipment ownership')
        integer(row['policy_epoch'],'acquisition policy epoch')
        if 'roll_version' in row and (not valid_roll(registry,d,row['roll_version']) or not d.stat_ranges or dict(row['stats'])!=rolled_stats(d,row['provenance'],row['roll_version'])):raise ValidationError('invalid saved equipment roll')
        if 'enhancement' in row:
            from src.data.economy.sect_rules import settings
            cfg=(settings(registry) or {}).get('management',{});e=row['enhancement']
            if not cfg or not isinstance(e,Mapping) or set(e)!={'level','bonus_bps','version'}:raise ValidationError('invalid enhancement metadata')
            integer(e['level'],'enhancement level',1)
            if e['level']>cfg['enhancement_max_level'] or type(e['bonus_bps']) is not int or e['bonus_bps']!=e['level']*cfg['enhancement_bonus_bps_per_level'] or e['version']!='sect-enhance-v1' or unknown(row,registry):raise ValidationError('invalid enhancement level or base stats')
        if 'refinement' in row:
            from .refinement import validate as validate_refinement
            validate_refinement(row['refinement'],registry)
        if row['equipped'] and p['slots'].get(d.slot)!=identity:raise ValidationError('equip slot/owner mismatch')
    for slot,identity in p['slots'].items():
        row=p['instances'].get(identity)
        if row is None or not row['equipped'] or definition(registry,row['definition_id']).slot!=slot:raise ValidationError('invalid equipped slot')
    return p
def get(p,identity):
    if identity not in p['instances']:raise NotFoundError('装备已不存在，请更新仓库')
    return p['instances'][identity]
def valid_roll(registry,d,version):
    if d.craft_roll_version and version==d.craft_roll_version:return True
    if version=='thorn-roll-v2':return True  # Existing roll contract accepts every registered range definition.
    if not isinstance(version,str):return False
    key=DefinitionKey('equipment_rolls',version.replace('-','_'))
    return registry.contains(key) and DefinitionKey('equipment',d.machine_id) in registry.lookup(key).references

def rolled_stats(d,provenance,version='thorn-roll-v2'):
    result={}
    if version in (ROLL_VERSION,CRAFT_ROLL_VERSION):
        ranges=equipment_ranges(d.machine_id,craft=version==CRAFT_ROLL_VERSION)
    else:ranges=d.craft_stat_ranges if d.craft_roll_version and version==d.craft_roll_version else d.stat_ranges
    for key,low,high,step in ranges:
        seed=f'{provenance}|{d.machine_id}|{version}|{key}'
        value=int.from_bytes(hashlib.sha256(seed.encode()).digest()[:8],'big')
        result[key]=low+(value%((high-low)//step+1))*step
    return result

def known_stats(row,d):
    if row.get('roll_version'):return bool(d.stat_ranges) and dict(row['stats'])==rolled_stats(d,row['provenance'],row['roll_version'])
    return 'roll_version' not in row and dict(row['stats'])==dict(d.stats)

def rolled_affixes(d,provenance):
    key,low,high,step=COMBAT_AFFIX_RANGES[d.slot]
    seed=f'{provenance}|{d.machine_id}|{COMBAT_AFFIX_VERSION}|{key}'
    value=int.from_bytes(hashlib.sha256(seed.encode()).digest()[:8],'big')
    return [{'version':COMBAT_AFFIX_VERSION,'stat':key,'value':low+value%((high-low)//step+1)*step}]

def known_affixes(row,d):
    return not row['affixes'] or list(row['affixes'])==rolled_affixes(d,row['provenance'])

def add(p,registry,identity,definition_id,provenance,epoch,enabled,*,roll_version=None,combat_affix=False):
    if identity in p['instances']:raise ValidationError('duplicate equipment identity')
    d=definition(registry,definition_id);r=thaw_json(p)
    r['instances'][identity]={'definition_id':definition_id,'stats':dict(d.stats),'affixes':[],'owner':'inventory','equipped':False,'locked':False,'favorite':False,'tradeable':d.tradeable,'status':'OWNED','provenance':provenance,'policy_epoch':epoch,'evaluation':'PENDING' if enabled else 'NONE'}
    if roll_version is not None:
        if not valid_roll(registry,d,roll_version) or not d.stat_ranges:raise ValidationError('unsupported equipment roll')
        r['instances'][identity].update(roll_version=roll_version,stats=rolled_stats(d,provenance,roll_version))
    if combat_affix:r['instances'][identity]['affixes']=rolled_affixes(d,provenance)
    return freeze_json(r)
def protected(row):return row['equipped'] or row['locked'] or row['favorite']
def unknown(row,registry):
    d=definition(registry,row['definition_id'])
    return not known_affixes(row,d) or not known_stats(row,d) or not row['tradeable'] or not d.tradeable

def remove(p,registry,identity):
    row=get(p,identity)
    if protected(row):raise ValidationError('穿戴、锁定或收藏的装备不能处理')
    if unknown(row,registry):raise ValidationError('装备属性尚不能安全评价，请人工保留')
    r=thaw_json(p);del r['instances'][identity];return freeze_json(r)
def equip(p,registry,identity,active):
    if active:raise ValidationError('当前战斗中，结束战斗后才能更换装备')
    row=get(p,identity)
    if unknown(row,registry):raise ValidationError('此装备属性尚未开放')
    r=thaw_json(p);d=definition(registry,row['definition_id']);old=r['slots'].get(d.slot)
    if old:r['instances'][old].update(owner='inventory',equipped=False)
    r['slots'][d.slot]=identity;r['instances'][identity].update(owner='player',equipped=True,evaluation='KEEP');return freeze_json(r)
def unequip(p,registry,identity,active):
    if active:raise ValidationError('当前战斗中，结束战斗后才能更换装备')
    row=get(p,identity)
    if not row['equipped']:raise ValidationError('装备尚未穿戴')
    r=thaw_json(p);del r['slots'][definition(registry,row['definition_id']).slot];r['instances'][identity].update(owner='inventory',equipped=False);return freeze_json(r)
def flag(p,identity,key,value):
    if key not in ('locked','favorite') or type(value) is not bool:raise ValidationError('合法保护状态必需')
    get(p,identity);r=thaw_json(p);r['instances'][identity][key]=value;return freeze_json(r)
def effective_stats(row):
    bonus=row.get('enhancement',{}).get('bonus_bps',0)
    stats={k:n+n*bonus//10000 if k in ('max_hp_milli','attack_milli','armor_milli') else n for k,n in row['stats'].items()}
    for affix in row.get('affixes',[]):
        if affix.get('version')==COMBAT_AFFIX_VERSION:
            key=affix['stat'];stats[key]=stats.get(key,0)+affix['value']
    for key,value in row.get('refinement',{}).get('stats',{}).items():
        stats[key]=stats.get(key,0)+value
    return stats

def projection(p,base):
    stats={**base}
    for identity in p['slots'].values():
        for key,n in effective_stats(p['instances'][identity]).items():
            if key in STATS:stats[key]=stats.get(key,0)+n
    for key,limit in RATE_CAPS.items():
        if key in stats:stats[key]=min(limit,stats[key])
    return freeze_json(stats)
def evaluate(p,registry,identity,rules):
    row=get(p,identity);d=definition(registry,row['definition_id'])
    if protected(row) or row.get('enhancement',{}).get('level',0) or row.get('refinement'):return 'KEEP'
    if unknown(row,registry):return 'REVIEW'
    if rules['mode']=='OFF':return 'KEEP'
    current=p['instances'].get(p['slots'].get(d.slot),{'stats':{}})
    if rules['keep_upgrades'] and any(n>effective_stats(current).get(k,0) for k,n in effective_stats(row).items()):return 'KEEP'
    rank={'white':0,'green':1,'blue':2,'rare':3}
    if rank[d.quality]>=rank[rules['min_quality']] or row['stats'].get(rules['keep_stat'],0)>=rules['min_stat']:return 'KEEP'
    if rules['mode']=='REVIEW':return 'REVIEW'
    return rules['mode'] if rules['mode'] in ('SELL','SALVAGE') else 'KEEP'

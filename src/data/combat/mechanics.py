"""Versioned effect vocabulary and immutable definitions; no runtime Domain imports."""
from collections.abc import Mapping
from dataclasses import dataclass
import json
from pathlib import Path
from functools import lru_cache
from src.core.state.envelope import freeze_json
from src.core.validation import ValidationError, integer
from src.data.registry import Definition, DefinitionKey

VERSION = 'five-dungeons-effects-v1'
CONTENT_VERSION = 'sect-effects-v1-6.3.0-r1'
ROLL_VERSION = 'equipment-effects-roll-v1'
CRAFT_ROLL_VERSION = 'equipment-effects-forge-v1'
TRIGGERS = frozenset(('battle_start','turn_start','turn_end','before_attack','on_hit','on_crit',
    'on_evade','on_block','on_hurt','before_hurt','lethal','shield_break','status_applied',
    'status_removed','status_resisted','on_heal','on_shield','on_support','skill_cast','kill','battle_end'))
OPS = frozenset(('damage','heal','shield','status','consume','cleanse','dispel','cooldown',
    'resource','revive','reduce','convert','extend','shorten','remove_shield'))
EXPRS = frozenset(('add','sub','mul','min','max','div','lt','le','gt','ge','eq','and','or','not','if'))
ELEMENTS = ('wood','earth','metal','water','fire','ice','poison','yin','lightning','neutral')
STATS = ('block_bps','spirit_milli','dot_reduction_bps','heal_bonus_bps','shield_bonus_bps',
    'burn_apply_bps','burn_bonus_bps','chill_bonus_bps',
    *(e+'_damage_bps' for e in ELEMENTS if e!='neutral'),
    *(e+'_resist_bps' for e in ELEMENTS if e not in ('neutral','poison')))
CAPS = {k:(1000000 if k.endswith('_milli') else 7500 if 'resist' in k else 5000) for k in STATS}

@lru_cache(maxsize=1)
def equipment_profiles():
    return freeze_json(json.loads(Path(__file__).with_name('mechanics.json').read_text())['equipment'])

def equipment_ranges(identity,*,craft=False):
    profile=equipment_profiles()[identity]
    ranges=profile.get('craft_ranges',profile['ranges']) if craft else profile['ranges']
    return tuple((k,*v) for k,v in sorted(ranges.items()))

@dataclass(frozen=True, slots=True)
class MechanicsDefinition(Definition):
    values: object = None

def settings(registry):
    key=DefinitionKey('combat_mechanics','shipping')
    return registry.lookup(key).values if registry.contains(key) else None

STAT_KEYS=frozenset((*STATS,'max_hp_milli','attack_milli','armor_milli','pierce_milli','crit_bps','accuracy_bps','evasion_bps','speed_bps','reflect_bps','poison_resist_bps','execute_bps','crit_damage_bps','crit_resist_bps','lifesteal_bps','damage_bonus_bps','damage_reduction_bps','attack_bonus_bps','status_resist_bps','adaptive_resist_bps','convert_bps','shield_pierce_bps','skill_bonus_bps'))
HISTORY_KEYS=frozenset(('hit','hurt','evade','block','heal','skill','negative','clean_turns','last_hurt_turn','last_movement_turn','last_skill_turn'))
EVENT_KEYS=frozenset(('amount','critical','kind','tier','negative','status','cleansed','category','new_element','new_negative','new_kind','shield_hit','removed_shield','removed_count','gap_turns','new_category','melee'))

def expression(value,statuses=None):
    if type(value) in (int,bool):return
    if isinstance(value,str):
        if value in ('turn','level','types','tier'):return
        if value.startswith('event.') and value[6:] in EVENT_KEYS:return
        if value.startswith('event.is_') and value[9:] in ELEMENTS:return
        if value.startswith(('own.','target.')):
            key=value.split('.',1)[1]
            if key in STAT_KEYS|{'hp_bps','max_hp','shield','resource','negatives','dead','dot','clean_turns','unique_negatives','unique_elements'}:return
            if key.startswith('history:') and key[8:] in HISTORY_KEYS:return
            if key.startswith('stack:') and statuses is not None and key[6:] in statuses:return
        raise ValidationError('unknown effect expression reference')
    if not isinstance(value,(list,tuple)) or not 2<=len(value)<=12 or value[0] not in EXPRS:
        raise ValidationError('invalid effect expression')
    arity=len(value)-1;op=value[0]
    if (op=='not' and arity!=1 or op=='if' and arity!=3 or op not in ('not','if','add','and','or','min','max') and arity!=2 or op in ('add','and','or','min','max') and arity<2):raise ValidationError('invalid effect expression arity')
    for item in value[1:]:expression(item,statuses)

def validate_rule(row,statuses):
    allowed={'id','trigger','condition','effects','chance','cooldown','per_turn','per_battle','every','category','cost','description'}
    if not isinstance(row,Mapping) or set(row)-allowed or not {'id','trigger','effects'}<=set(row):raise ValidationError('invalid effect rule')
    DefinitionKey('effect_rules',row['id'])
    if row['trigger'] not in TRIGGERS:raise ValidationError('unknown effect trigger')
    if not isinstance(row['effects'],(list,tuple)) or not 1<=len(row['effects'])<=12:raise ValidationError('bounded effects required')
    expression(row.get('condition',True),statuses)
    for key in ('chance','cooldown','per_turn','per_battle','every','cost'):
        if key in row:
            integer(row[key],key)
            if row[key]>10000:raise ValidationError('effect parameter exceeds bound')
    for effect in row['effects']:
        if not isinstance(effect,Mapping) or set(effect)-{'op','target','amount','status','stacks','duration','element','kind','condition','limit','category','count'} or effect.get('op') not in OPS:raise ValidationError('unknown effect operation')
        if effect.get('target','self') not in ('self','other','both'):raise ValidationError('unknown effect target')
        if effect.get('element','neutral') not in (*ELEMENTS,'weakest','incoming'):raise ValidationError('unknown effect element')
        if 'status' in effect and effect['status'] not in statuses:raise ValidationError('unknown effect status')
        if effect.get('kind','skill') not in ('direct','skill','ranged','dot','reflect','counter','extra_hit'):raise ValidationError('unknown damage kind')
        for key in ('amount','stacks','duration','condition','limit','count'):
            if key in effect:expression(effect[key],statuses)

def register(registry):
    data=json.loads(Path(__file__).with_name('mechanics.json').read_text())
    if set(data)!={'schema_version','version','balance','statuses','techniques','equipment','enemies'} or data['schema_version']!=1 or data['version']!=VERSION:raise ValidationError('invalid mechanics package')
    for key,value in data['balance'].items():integer(value,key,1)
    if data['balance']['effect_budget']>128 or data['balance']['event_limit']>128 or data['balance']['max_turns']>1000:raise ValidationError('combat work exceeds safety budget')
    statuses=data['statuses']
    for key,row in statuses.items():
        DefinitionKey('statuses',key)
        if set(row)-{'name','max_stacks','duration','modifiers','magnitude_modifiers','tick','negative','control','consume_on_skill','consume_on_heal','consume_on_hit','consume_on_support','break_on_category','exclusive_group','requires_shield'} or not {'name','max_stacks','duration'}<=set(row):raise ValidationError('invalid status definition')
        integer(row['max_stacks'],'stack cap',1);integer(row['duration'],'duration',1)
        if row['max_stacks']>20 or row['duration']>100:raise ValidationError('unbounded status')
        for stat,amount in row.get('modifiers',{}).items():
            if stat not in STAT_KEYS or type(amount) is not int:raise ValidationError('invalid status modifier')
        for stat,amount in row.get('magnitude_modifiers',{}).items():
            if stat not in STAT_KEYS or type(amount) is not int:raise ValidationError('invalid magnitude modifier')
        for flag in ('negative','control','consume_on_skill','consume_on_heal','consume_on_hit','consume_on_support','requires_shield'):
            if flag in row and type(row[flag]) is not bool:raise ValidationError('boolean status lifecycle flag required')
        if row.get('tick') not in (None,'damage','heal'):raise ValidationError('invalid status tick')
    manuals=json.loads(Path(__file__).parents[1].joinpath('cultivation/techniques.json').read_text())['techniques']
    if set(data['techniques'])!={r['id'] for r in manuals}:raise ValidationError('mechanics must cover all 150 manuals')
    for group in ('techniques','equipment','enemies'):
        for key,row in data[group].items():
            DefinitionKey(group,key)
            if group=='equipment':
                if DefinitionKey('equipment',key) not in registry._definitions:raise ValidationError('unknown equipment effects binding')
                for stat,values in row['ranges'].items():
                    if stat not in (*STATS,'max_hp_milli','attack_milli','armor_milli','crit_bps','accuracy_bps','evasion_bps','pierce_milli','reflect_bps','speed_bps','poison_resist_bps'):raise ValidationError('unknown equipment stat')
                    if len(values)!=3:raise ValidationError('stat range triple required')
                    low,high,step=values
                    for n in values:integer(n,'range',1)
                    if high<low or (high-low)%step:raise ValidationError('invalid effect stat range')
            if row.get('attack_kind','direct') not in ('direct','ranged'):raise ValidationError('invalid basic attack kind')
            ids=set()
            for rule in row['rules']:
                validate_rule(rule,statuses)
                if rule['id'] in ids:raise ValidationError('duplicate source rule')
                ids.add(rule['id'])
    registry.register(MechanicsDefinition('combat_mechanics','shipping',VERSION,(),freeze_json(data)))
    refs=tuple(DefinitionKey('equipment',key) for key in data['equipment'])
    registry.register(Definition('equipment_rolls',ROLL_VERSION.replace('-','_'),ROLL_VERSION,refs))
    crafting=tuple(DefinitionKey('equipment',key) for key,row in data['equipment'].items() if row.get('craft_ranges'))
    registry.register(Definition('equipment_rolls',CRAFT_ROLL_VERSION.replace('-','_'),CRAFT_ROLL_VERSION,crafting))
    equipment_profiles.cache_clear()

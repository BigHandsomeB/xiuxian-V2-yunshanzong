"""Phase16 content composed into the existing sealed Definition Registry."""
from dataclasses import dataclass,replace
from pathlib import Path
import json
from src.core.validation import ValidationError,integer
from src.data.registry import Definition,DefinitionKey,DefinitionRegistry
from src.data.cultivation.definitions import load_cultivation
from src.data.recipes.production import register_production,ProductionDefinition

VERSION='economy-v1-6.3.0-r1'
SOURCE_RECIPES=('herb','ore','wood')
EQUIPMENT_IDS=('basic_left','basic_head')
EQUIPMENT_SLOTS=(('left','武器'),('gloves','手套'),('belt','腰带'),('body','衣服'),('feet','鞋子'),('head','头盔'))
EQUIPMENT_STATS=('max_hp_milli','attack_milli','armor_milli','pierce_milli','crit_bps','accuracy_bps','evasion_bps','speed_bps','reflect_bps','poison_resist_bps','execute_bps','crit_damage_bps','crit_resist_bps','lifesteal_bps','damage_bonus_bps','damage_reduction_bps')
COMBAT_AFFIX_VERSION='combat-affix-v1'
# Additive rolled affixes for newly acquired equipment; original saved base stats stay fixed.
COMBAT_AFFIX_RANGES={'left':('crit_damage_bps',200,600,100),'gloves':('lifesteal_bps',100,300,100),'belt':('crit_resist_bps',200,400,100),'body':('damage_reduction_bps',100,300,100),'feet':('damage_bonus_bps',100,300,100),'head':('crit_resist_bps',100,300,100)}
NEW_STAT_CAPS={'crit_damage_bps':10000,'crit_resist_bps':5000,'lifesteal_bps':1500,'damage_bonus_bps':3000,'damage_reduction_bps':4000}
CRAFT_RECIPES=('forge_sword','forge_ingot_sword')
@dataclass(frozen=True,slots=True)
class EquipmentDefinition(Definition):
    slot:str='left'
    quality:str='white'
    stats:tuple=()
    asset_id:str=''
    sell_coins:int=25
    salvage:tuple=(('coins',7),('ingot',1))
    craft_recipe_id:str|None=None
    tradeable:bool=True
    stat_ranges:tuple=()
    def __post_init__(self):
        super(EquipmentDefinition,self).__post_init__()
        if self.domain!='equipment' or self.slot not in dict(EQUIPMENT_SLOTS) or self.quality not in ('white','green','blue','rare') or type(self.tradeable) is not bool:raise ValidationError('invalid basic equipment definition')
        if type(self.stats) is not tuple or type(self.salvage) is not tuple:raise ValidationError('immutable equipment values required')
        if not self.stats or len(dict(self.stats))!=len(self.stats):raise ValidationError('equipment stats required')
        for k,n in self.stats:
            if k not in EQUIPMENT_STATS:raise ValidationError('unsupported base stat')
            integer(n,'equipment stat',1)
            if k.endswith('_bps') and n>10000:raise ValidationError('equipment rate exceeds 100%')
        if type(self.stat_ranges) is not tuple or len({v[0] for v in self.stat_ranges})!=len(self.stat_ranges):raise ValidationError('immutable unique stat ranges required')
        if self.stat_ranges and {v[0] for v in self.stat_ranges}!=set(dict(self.stats)):raise ValidationError('range keys must match stats')
        for key,low,high,step in self.stat_ranges:
            for n in (low,high,step):integer(n,'stat range',1)
            if high<low or (high-low)%step or not low<=dict(self.stats)[key]<=high or (dict(self.stats)[key]-low)%step:raise ValidationError('invalid equipment stat range')
            if key.endswith('_bps') and high>10000:raise ValidationError('range exceeds 100%')
        integer(self.sell_coins,'sale',1)
        for k,n in self.salvage:DefinitionKey('resources',k);integer(n,'salvage',1)
        refs=tuple(DefinitionKey('resources',k) for k,_ in self.salvage)
        if self.craft_recipe_id:refs+=(DefinitionKey('production',self.craft_recipe_id),)
        if self.references!=refs or type(self.asset_id) is not str or not self.asset_id:raise ValidationError('equipment references required')
def load_economy(*,seal=True,content_version=VERSION,production_input_overrides=None):
    package=json.loads(Path(__file__).parents[1].joinpath('cultivation/content.json').read_text());package['content_version']=content_version
    r=load_cultivation(json.dumps(package),seal=False)
    overrides={} if production_input_overrides is None else production_input_overrides
    if not isinstance(overrides,dict) or set(overrides)-set((*SOURCE_RECIPES,'grain')):raise ValidationError('unknown production input override')
    if 'grain' in overrides:
        updated=DefinitionRegistry(schema_version=r.schema_version,content_version=r.content_version)
        for d in r._definitions.values():
            if d.key==DefinitionKey('production','grain'):
                if not isinstance(overrides['grain'],dict):raise ValidationError('production inputs must be object')
                inputs=tuple(sorted(overrides['grain'].items()))
                refs=(DefinitionKey('buildings',d.building_kind),)+tuple(DefinitionKey('resources',key) for key,_ in inputs+d.outputs)
                d=replace(d,inputs=inputs,references=refs)
            updated.register(d)
        r=updated
    register_production(r,[dict(machine_id=k,display_name=name,building_kind=kind,inputs=overrides.get(k,{}),outputs={k:3},duration_ms=30000,min_level=1,unlock_floor=0,unlock_realm=0) for k,name,kind in [('herb','种植灵草','garden'),('ore','开采凡铁矿','mine'),('wood','采集灵木','forest')]])
    for key,name,slot,stats,recipe in [('basic_left','青锋剑','left',(('attack_milli',4000),),'forge_sword'),('basic_head','青布冠','head',(('armor_milli',2000),('max_hp_milli',8000)),None)]:
        refs=(DefinitionKey('resources','coins'),DefinitionKey('resources','ingot'))+((DefinitionKey('production',recipe),) if recipe else ())
        r.register(EquipmentDefinition('equipment',key,name,refs,slot,'white',stats,'equipment.'+key,25,(('coins',7),('ingot',1)),recipe,True))
    for key,name,inputs,duration in [('forge_sword','炼制青锋剑',(('coins',20),('ore',9),('wood',1)),120000),('forge_ingot_sword','铁锭炼剑',(('coins',20),('ingot',3),('wood',1)),30000)]:
        refs=(DefinitionKey('buildings','forge'),)+tuple(DefinitionKey('resources',k) for k,_ in inputs)+(DefinitionKey('equipment','basic_left'),)
        r.register(ProductionDefinition('production',key,name,refs,'forge',inputs,(),duration,1,0,0,'basic_left'))
    if seal:r.seal()
    return r

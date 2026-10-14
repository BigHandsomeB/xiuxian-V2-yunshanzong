"""Immutable audited minimum Combat content; compose through existing public loaders."""
from dataclasses import dataclass
import json
from pathlib import Path
from src.core.validation import ValidationError, DuplicateError, integer, text
from src.data.registry import Definition, DefinitionKey, _fields
from src.data.disciples.work import load_work
from src.data.recipes.production import register_production

@dataclass(frozen=True, slots=True)
class PlayerDefinition(Definition):
    level: int = 1
    realm: int = 0
    asset_id: str = ''
    def __post_init__(self):
        super(PlayerDefinition,self).__post_init__()
        if self.domain!='players' or self.machine_id!='hero' or self.references:raise ValidationError('minimal formal player definition required')
        integer(self.level,'level',1);integer(self.realm,'realm');text(self.asset_id,'player asset id')
        if (self.level,self.realm)!=(1,0):raise ValidationError('player growth is not migrated')

@dataclass(frozen=True, slots=True)
class MonsterDefinition(Definition):
    base_hp_milli: int = 1
    attack_milli: int = 0
    armor_milli: int = 0
    asset_id: str = ''
    reward: tuple = ()
    poison_milli: int = 0
    crit_bps: int = 0
    def __post_init__(self):
        super(MonsterDefinition,self).__post_init__()
        if self.domain!='monsters':raise ValidationError('monster namespace required')
        integer(self.base_hp_milli,'base hp',1);integer(self.attack_milli,'attack');integer(self.armor_milli,'armor');text(self.asset_id,'monster asset id')
        integer(self.poison_milli,'poison')
        integer(self.crit_bps,'monster critical chance')
        if self.crit_bps>10000:raise ValidationError('monster critical chance exceeds 100%')
        if type(self.reward) is not tuple or not self.reward:raise ValidationError('immutable nonempty reward required')
        keys=[]
        for entry in self.reward:
            if type(entry) is not tuple or len(entry)!=2:raise ValidationError('immutable resource amount required')
            key,amount=entry;DefinitionKey('resources',key);integer(amount,'reward amount',1);keys.append(key)
        if len(set(keys))!=len(keys):raise DuplicateError('duplicate reward resource')
        if self.references!=tuple(DefinitionKey('resources',key) for key in keys):raise ValidationError('reward references mismatch')

@dataclass(frozen=True, slots=True)
class EncounterDefinition(Definition):
    monster_id: str = ''
    background_asset_id: str = ''
    def __post_init__(self):
        super(EncounterDefinition,self).__post_init__()
        if self.domain!='encounters':raise ValidationError('encounter namespace required')
        text(self.background_asset_id,'background asset id')
        if self.references!=(DefinitionKey('monsters',self.monster_id),DefinitionKey('players','hero')):raise ValidationError('encounter references mismatch')


def load_combat(source=None,*,seal=True):
    """Same existing content package plus additive Combat content; no Foundation edits.

    Reuse the unsealed Work loader and exact Alchemy recipe registration. Existing
    existing definitions stay equal; content version explicitly advances; no recipes or old loaders changed.
    """
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise DuplicateError('duplicate combat JSON key')
            result[key]=value
        return result
    def invalid(value):raise ValidationError('nonfinite combat content')
    try:p=json.loads(source if source is not None else Path(__file__).with_name('content.json').read_text(),object_pairs_hook=unique,parse_constant=invalid)
    except (TypeError,json.JSONDecodeError) as exc:raise ValidationError('invalid combat JSON') from exc
    _fields(p,('schema_version','content_version','player','monsters','encounters'))
    if type(p['schema_version']) is not int or p['schema_version']!=1:raise ValidationError('unsupported combat schema')
    root=Path(__file__).parents[1]
    alchemy=json.loads((root/'recipes/alchemy.json').read_text());work=json.loads((root/'disciples/work.json').read_text());text(p['content_version'],'combat content version');work['content_version']=p['content_version']
    registry=load_work(json.dumps(work),seal=False);register_production(registry,alchemy['definitions'])
    registry.register(Definition('alchemy','recipes','丹方',tuple(DefinitionKey('production',r['machine_id']) for r in alchemy['definitions'])))
    _fields(p['player'],('machine_id','display_name','level','realm','asset_id'))
    registry.register(PlayerDefinition('players',**p['player']))
    if type(p['monsters']) is not list or len(p['monsters'])!=1 or type(p['encounters']) is not list or len(p['encounters'])!=1:raise ValidationError('minimal content requires one monster and one encounter')
    for r in p['monsters']:
        _fields(r,('machine_id','display_name','base_hp_milli','attack_milli','armor_milli','asset_id','reward'))
        if type(r['reward']) is not dict:raise ValidationError('reward object required')
        reward=tuple(sorted(r['reward'].items()));refs=tuple(DefinitionKey('resources',k) for k,_ in reward)
        registry.register(MonsterDefinition('monsters',r['machine_id'],r['display_name'],refs,r['base_hp_milli'],r['attack_milli'],r['armor_milli'],r['asset_id'],reward))
    for r in p['encounters']:
        _fields(r,('machine_id','display_name','monster_id','background_asset_id'))
        registry.register(EncounterDefinition('encounters',r['machine_id'],r['display_name'],(DefinitionKey('monsters',r['monster_id']),DefinitionKey('players','hero')),r['monster_id'],r['background_asset_id']))
    if seal:registry.seal()
    return registry

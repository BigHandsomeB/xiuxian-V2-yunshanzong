"""Additive 100-floor content, immutable stats and explicit identities; no asset DB dependency."""
import json
from pathlib import Path
from dataclasses import dataclass
from src.core.validation import ValidationError,integer
from src.data.registry import Definition,DefinitionKey,_fields
from src.data.economy.definitions import load_economy
from src.data.combat.definitions import MonsterDefinition,EncounterDefinition
LEGACY_VERSION='dungeons-v1-6.3.0-r1'
LOOT_VERSION='dungeons-loot-v1-6.3.0-r1'
EXPANSION_LEGACY_VERSION='dungeons-balance-v2-6.3.0-r1'
VERSION='dungeons-expeditions-v1-6.3.0-r1'
MANAGEMENT_VERSION='sect-management-v1-6.3.0-r1'
COLD_JADE_VERSION='dungeons-cold-jade-v1-6.3.0-r1'
COLD_JADE_MANAGEMENT_VERSION='sect-management-cold-jade-v1-6.3.0-r1'
ID='thorn_path'
@dataclass(frozen=True,slots=True)
class DungeonDefinition(Definition):
    encounters:tuple=()
    tiers:tuple=()
    legacy_encounters:tuple=()
    def __post_init__(self):
        super(DungeonDefinition,self).__post_init__()
        if self.domain!='dungeons' or self.machine_id not in (ID,'red_copper_mine','mist_marsh','cold_jade_cave') or len(self.encounters)!=100 or len(set(self.encounters))!=100 or len(self.tiers)!=100:raise ValidationError('exact 100-floor dungeon required')
        if self.tiers!=tuple('boss' if f==100 else 'elite' if f%10==0 else 'normal' for f in range(1,101)):raise ValidationError('invalid dungeon tier order')
        if self.legacy_encounters and (len(self.legacy_encounters)!=100 or len(set(self.legacy_encounters))!=100 or set(self.encounters)&set(self.legacy_encounters)):raise ValidationError('invalid historical dungeon encounters')
        if self.references!=tuple(DefinitionKey('encounters',k) for k in (*self.encounters,*self.legacy_encounters)):raise ValidationError('dungeon encounter references mismatch')

def load_dungeons(*,legacy=False,balance_legacy=False,expansion_legacy=False,management=False,cold_jade=False,ecology=False):
    if cold_jade and (legacy or balance_legacy or expansion_legacy):raise ValidationError('cold jade requires current expeditions')
    if management and (legacy or balance_legacy or expansion_legacy):raise ValidationError('management requires current expeditions')
    input_overrides=json.loads(Path(__file__).parents[1].joinpath('economy/sect_management.json').read_text()).get('production_input_overrides',{}) if management else {}
    if ecology and not (management and cold_jade):raise ValidationError('ecology requires current management and cold jade content')
    from src.data.economy.ecology import VERSION as ECOLOGY_VERSION
    r=load_economy(seal=False,production_input_overrides=input_overrides,content_version=ECOLOGY_VERSION if ecology else (COLD_JADE_MANAGEMENT_VERSION if management else COLD_JADE_VERSION) if cold_jade else MANAGEMENT_VERSION if management else LEGACY_VERSION if legacy else LOOT_VERSION if balance_legacy else EXPANSION_LEGACY_VERSION if expansion_legacy else VERSION)
    if not legacy:
        from src.data.dungeons.loot import register
        register(r,current=not (balance_legacy or expansion_legacy))
    p=json.loads(Path(__file__).with_name('thorn_path.json').read_text())
    _fields(p,('id','name','floors','elite_interval','background_asset_id','monsters'))
    if p['id']!=ID or p['floors']!=100 or p['elite_interval']!=10:raise ValidationError('unsupported dungeon structure')
    families={k:[] for k in ('normal','elite','boss')}
    for m in p['monsters']:
        _fields(m,('id','name','tier','order','asset_id','hp','attack','armor'))
        if m['tier'] not in families:raise ValidationError('invalid enemy tier')
        for k in ('hp','attack','armor','order'):integer(m[k],k,1 if k=='hp' else 0)
        families[m['tier']].append(m)
    if [len(families[k]) for k in ('normal','elite','boss')]!=[10,5,1] or len({m['id'] for m in p['monsters']})!=16:raise ValidationError('dungeon requires 10/5/1 unique monsters')
    ids=[];tiers=[];historical=[]
    from . import balance
    package=balance.content() if not (legacy or balance_legacy) else None
    if package and set(package['profiles'])!={m['name'] for m in p['monsters']}:raise ValidationError('balance profiles mismatch')
    for f in range(1,101):
        tier='boss' if f==100 else 'elite' if f%10==0 else 'normal'
        index=0 if tier=='boss' else (f//10-1)%5 if tier=='elite' else (f-1-(f-1)//10)%10
        m=families[tier][index];mid=f'{ID}_enemy_{f:03d}';eid=f'{ID}_{f:03d}'
        reward={'coins':50 if tier=='boss' else 10+f//10 if tier=='elite' else 3+(f-1)//10,'wood':4 if tier=='boss' else 2 if tier=='elite' else 1}
        if tier!='normal':reward['herb']=3 if tier=='boss' else 1
        amounts=tuple(sorted(reward.items()));refs=tuple(DefinitionKey('resources',k) for k,_ in amounts)
        poison=0 if legacy else 2000 if m['id']=='thorn_normal_8' else 4000 if m['id']=='thorn_elite_4' else 0
        r.register(MonsterDefinition('monsters',mid,m['name'],refs,(m['hp']+f-1)*1000,(m['attack']+(f-1)//25)*1000,m['armor']*1000+((f-1)//40)*500,m['asset_id'],amounts,poison,500 if tier=='elite' else 1000 if tier=='boss' else 0))
        r.register(EncounterDefinition('encounters',eid,f'{p["name"]} · 第{f}层',(DefinitionKey('monsters',mid),DefinitionKey('players','hero')),mid,p['background_asset_id']))
        if package:
            historical.append(eid);mid=f'{ID}_v2_enemy_{f:03d}';eid=f'{ID}_v2_{f:03d}'
            hp,attack,armor=balance.stats(package,f,tier,m['name'])
            r.register(MonsterDefinition('monsters',mid,m['name'],refs,hp,attack,armor,m['asset_id'],amounts,poison,500 if tier=='elite' else 1000 if tier=='boss' else 0))
            r.register(EncounterDefinition('encounters',eid,f'{p["name"]} · 第{f}层',(DefinitionKey('monsters',mid),DefinitionKey('players','hero')),mid,p['background_asset_id']))
        ids.append(eid);tiers.append(tier)
    r.register(DungeonDefinition('dungeons',ID,p['name'],tuple(DefinitionKey('encounters',k) for k in (*ids,*historical)),tuple(ids),tuple(tiers),tuple(historical)))
    if not (legacy or balance_legacy):
        from src.data.economy.sect_rules import register as register_sect_rules
        register_sect_rules(r,management=management,ecology=ecology)
    if not (legacy or balance_legacy or expansion_legacy):
        from .expeditions import register as register_expeditions
        register_expeditions(r,DungeonDefinition,cold_jade=cold_jade)
    r.seal();return r

"""Immutable, explicit shipping economy configuration; historical registries stay valid."""
from dataclasses import dataclass
from pathlib import Path
import json
from src.data.registry import Definition,DefinitionKey
from src.core.state.envelope import freeze_json
from src.core.validation import ValidationError,integer
from src.data.recipes.production import register_production
from src.data.items.resources import ResourceDefinition

@dataclass(frozen=True,slots=True)
class SectRules(Definition):
    values:object=None

def register(registry,*,management=False,ecology=False):
    def unique(pairs):
        result={}
        for k,v in pairs:
            if k in result:raise ValidationError('duplicate sect rule key')
            result[k]=v
        return result
    p=json.loads(Path(__file__).with_suffix('.json').read_text(),object_pairs_hook=unique)
    p['leveling']=json.loads(Path(__file__).parents[1].joinpath('cultivation/leveling.json').read_text(),object_pairs_hook=unique)
    if ecology:p['techniques']=json.loads(Path(__file__).parents[1].joinpath('cultivation/techniques.json').read_text(),object_pairs_hook=unique)
    from src.data.cultivation.levels import validate_config
    validate_config(p['leveling'])
    if management:
        extra=json.loads(Path(__file__).with_name('sect_management.json').read_text(),object_pairs_hook=unique)
        p['management']=extra
        p['material_caps'].update({rid:extra['material_retention_cap'] for rid in extra['sale_prices']})
        p['additional_recipes']=[{**row,'inputs':extra['pill_inputs'].get(row['machine_id'],row['inputs'])} for row in p['additional_recipes']]+extra['recipes']
        p['production_whitelist']+= [row['machine_id'] for row in extra['recipes']]
        p['building_upgrade']['materials'].update({kind:'wood' for kind in extra['upgrade_costs']})
        p['craft']['materials'].update({key:next(resource for resource in cost if '_material_' in resource) for key,cost in extra['craft_costs'].items()})
        for key in ('housing_beds_per_level','population_per_sect_level','max_recruit_count','recruit_duration_ms','meal_period_ms','meal_food_per_person','meal_bonus_bps','enhancement_max_level','enhancement_bonus_bps_per_level'):
            integer(extra[key],key,1)
        for key in ('log_limit','material_retention_cap','enhancement_min_sect_level','enhancement_min_forge_level','new_craft_min_sect_level','new_craft_min_forge_level'):integer(extra[key],key,1)
        integer(extra['meal_reserve_default'],'default meal reserve')
        integer(extra['stone_trade_max_quantity'],'stone trade max quantity',1)
        if set(extra['building_stone_costs'])!={str(n) for n in range(1,11)}:raise ValidationError('building stone costs must cover levels 1 through 10')
        for cost in extra['building_stone_costs'].values():
            if len(cost)!=1:raise ValidationError('one stone grade per building stage required')
            for rid,n in cost.items():DefinitionKey('resources',rid);integer(n,'building stone quantity',1)
        for rid,price in extra['stone_trade_prices'].items():DefinitionKey('resources',rid);integer(price,'stone trade price',1)
        if set(extra['upgrade_additional_costs'])!={str(n) for n in range(1,11)}:raise ValidationError('additional construction costs must cover levels 1 through 10')
        for cost in extra['upgrade_additional_costs'].values():
            for rid,n in cost.items():DefinitionKey('resources',rid);integer(n,'additional construction cost',1)
        for costs in [extra['recruit_cost'],*extra['upgrade_costs'].values(),*extra['craft_costs'].values(),*extra['enhancement_costs'].values(),*extra['pill_inputs'].values()]:
            if not costs:raise ValidationError('positive management costs required')
            for resource,n in costs.items():DefinitionKey('resources',resource);integer(n,'management cost',1)
        for resource,price in extra['sale_prices'].items():DefinitionKey('resources',resource);integer(price,'material sale price',1)
        if extra['meal_bonus_bps']>10000 or extra['enhancement_max_level']>10:raise ValidationError('bounded management bonuses required')
    if ecology:
        if not management:raise ValidationError('ecology requires sect management')
        from .ecology import content,register as register_ecology
        eco=content();register_ecology(registry,eco);p['ecology']=eco
        registry.register(ResourceDefinition('resources','manual_page','功法残页',(),False,None,'待定'))
        stone_recipes=p['techniques']['sources']['mining_recipes']
        p['additional_recipes']+=stone_recipes
        p['production_whitelist']+=[r['machine_id'] for r in stone_recipes]
        p['additional_recipes']+=eco['recipes']
        p['production_whitelist']=[key for key in p['production_whitelist'] if key not in eco['retired_recipes']]
        p['production_whitelist'] += [row['machine_id'] for row in eco['recipes']] + ['build_'+row['id'] for row in eco['facilities']]
    for n in p['material_caps'].values():integer(n,'material cap',1)
    integer(p['overflow_coin_per_item'],'overflow coins')
    ratio=p['auto_production_capacity_ratio']
    if type(ratio) not in (int,float) or not 0<ratio<=1:raise ValidationError('invalid automatic capacity ratio')
    for n in p['building_upgrade'].values():
        if type(n) is int:integer(n,'upgrade parameter',1)
    for row in p['new_save_production'].values():
        for key in ('workers','target'):integer(row[key],key,1)
        integer(row['max_consumption'],'batch consumption')
    for v in p['craft']['common'].values():integer(v,'craft quantity',1)
    for v in p['craft']['boss'].values():integer(v,'craft quantity',1)
    for k in ('new_save_material_overflow','legacy_material_overflow'):
        if type(p[k]) is not bool:raise ValidationError('overflow default must be boolean')
    stages=p['cultivation']['stages']
    if not stages or stages[0]['minimum_progress']!=0 or sorted(set(r['minimum_progress'] for r in stages))!=[r['minimum_progress'] for r in stages]:raise ValidationError('ordered cultivation stages required')
    for row in stages:
        integer(row['minimum_progress'],'stage threshold');integer(row['bonus_bps'],'stage bonus')
    integer(p['cultivation']['pill_gain'],'pill gain',1)
    for n in p['cultivation']['breakthrough_cost'].values():integer(n,'breakthrough cost',1)
    for n in p['read_default_buildings'].values():integer(n,'default building level',1)
    foundation=p.get('foundation_cultivation')
    if foundation:
        integer(foundation['threshold'],'foundation threshold',1)
        rows=foundation['stages']
        if not rows or rows[0]['minimum_progress']!=0 or [r['minimum_progress'] for r in rows]!=sorted(set(r['minimum_progress'] for r in rows)):raise ValidationError('ordered foundation stages required')
        for row in rows:
            integer(row['minimum_progress'],'foundation stage');integer(row['bonus_bps'],'foundation bonus')
            if row['minimum_progress']>=foundation['threshold']:raise ValidationError('foundation stage outside progress limit')
        for row in foundation['pills'].values():integer(row['gain'],'foundation pill gain',1)
    levels=p.get('sect_levels',[])
    if [r['level'] for r in levels]!=sorted(set(r['level'] for r in levels)):raise ValidationError('ordered unique sect levels required')
    for row in levels:
        for key in ('level','building_count','building_level','cleared_floor'):integer(row[key],key,1)
        if not 2<=row['level']<=5 or row['cleared_floor']>100:raise ValidationError('sect level out of range')
    for n in p.get('recipe_sect_minimum',{}).values():integer(n,'recipe sect level',1)
    for values in p.get('legacy_job_duration_ms',{}).values():
        for n in values:integer(n,'legacy job duration',1)
    for row in p['additional_resources']:
        registry.register(ResourceDefinition('resources',row['machine_id'],row['display_name'],(),row['capacity_counted'],row['grade'],row.get('tier','待定')))
    register_production(registry,p['additional_recipes'])
    registry.register(Definition('alchemy','additional_recipes','新增丹方',tuple(DefinitionKey('production',r['machine_id']) for r in p['additional_recipes'] if r['building_kind']=='alchemy')))
    refs={DefinitionKey('resources',k) for k in p['material_caps']}
    if management:
        for cost in [extra['recruit_cost'],*extra['upgrade_costs'].values(),*extra['craft_costs'].values(),*extra['enhancement_costs'].values(),*extra['pill_inputs'].values()]:refs|={DefinitionKey('resources',k) for k in cost}
    if management:
        refs|={DefinitionKey('resources',k) for cost in extra['building_stone_costs'].values() for k in cost}
        refs|={DefinitionKey('resources',k) for k in extra['stone_trade_prices']}
        refs|={DefinitionKey('resources',k) for cost in extra['upgrade_additional_costs'].values() for k in cost}
    refs|={DefinitionKey('resources',k) for k in p['cultivation']['breakthrough_cost']}
    refs|={DefinitionKey('resources',k) for k in p['craft']['boss']}
    refs|={DefinitionKey('resources',k) for k in p['craft']['materials'].values()}
    refs|={DefinitionKey('equipment',k) for k in (*p['craft']['materials'],*p['craft']['boss_equipment'])}
    refs|={DefinitionKey('production',k) for k in (*p['production_whitelist'],*p.get('recipe_sect_minimum',{}),*p.get('production_building_overrides',{}),*p.get('legacy_job_duration_ms',{}))}
    refs|={DefinitionKey('buildings',k) for k in p.get('production_building_overrides',{}).values()}
    refs|={DefinitionKey('resources',k) for k in foundation['pills']} if foundation else set()
    refs|={DefinitionKey('buildings',k) for k in (*p['new_save_production'],*p['building_upgrade']['materials'],*p['read_default_buildings'])}
    registry.register(SectRules('sect_rules','shipping','宗门经营规则',tuple(sorted(refs,key=lambda x:(x.domain,x.machine_id))),freeze_json(p)))
    if management:
        from .market import register as register_market
        register_market(registry,ecology=ecology)

def settings(registry):
    key=DefinitionKey('sect_rules','shipping')
    return registry.lookup(key).values if registry.contains(key) else None

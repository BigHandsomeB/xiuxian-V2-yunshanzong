"""@module systems/sect/rules
@purpose Pure build requirement checks and real timed-upgrade quotation; no mutation.
@depends systems/sect/buildings,data/buildings,core/state,core/validation
@usedBy tests/systems/test_buildings, future Application construction coordination
@see ./INDEX.md
"""
from src.core.state.envelope import freeze_json
from src.core.validation import ValidationError, integer
from src.data.buildings.definitions import CONSTRUCTION_WORK_SECONDS
from src.systems.sect.buildings import definition, get_building


def can_build(registry, kind, *, cleared_floor, realm):
    integer(cleared_floor,'cleared_floor');integer(realm,'realm')
    d=definition(registry,kind)
    return cleared_floor>=d.unlock_floor and realm>=d.unlock_realm


def quote_upgrade(partition, registry, identity):
    row=get_building(partition,registry,identity);d=definition(registry,row['definition_id'])
    if row['construction_target'] is not None:
        raise ValidationError('building construction already pending')
    if row['level']>=d.max_level:
        raise ValidationError('building at maximum level')
    from src.data.economy.sect_rules import settings
    cfg=settings(registry)
    if cfg and row['level']>=min(d.max_level,cfg['building_upgrade']['max_level']):raise ValidationError('building at maximum level')
    target=row['level']+1
    management=cfg.get('management',{}) if cfg else {}
    if row['definition_id'] in management.get('upgrade_costs',{}):
        cost={key:n*(target*target if key=='coins' else target) for key,n in management['upgrade_costs'][row['definition_id']].items()}
        cost.update(management.get('building_stone_costs',{}).get(str(target),{}))
        cost.update(management.get('upgrade_additional_costs',{}).get(str(target),{}))
        return freeze_json({'target_level':target,'cost':cost,'construction_work_seconds':cfg['building_upgrade']['construction_seconds_per_level']*target})
    if cfg and row['definition_id'] in cfg['building_upgrade']['materials']:
        rule=cfg['building_upgrade'];cost={k:n*target for k,n in d.cost if k!='coins'}
        cost.update({key:rule[key+'_per_level']*target for key in ('stone','wood') if key in cost and key+'_per_level' in rule})
        cost['coins']=rule['coin_coefficient']*target*target
        cost[rule['materials'][row['definition_id']]]=rule['material_per_level']*target
        return freeze_json({'target_level':target,'cost':cost,'construction_work_seconds':rule['construction_seconds_per_level']*target})
    return freeze_json({'target_level':target,'cost':{key:amount*target for key,amount in d.cost},
                        'construction_work_seconds':CONSTRUCTION_WORK_SECONDS*target})


def development(partition, registry, cleared_floor=0):
    """Derived, read-only sect rank; only currently upgradeable buildings qualify."""
    from src.data.economy.sect_rules import settings
    cfg=settings(registry)
    levels=[r['level'] for r in partition['buildings'].values()
            if cfg and r['definition_id'] in cfg['building_upgrade']['materials']]
    rows=[];level=1
    for row in cfg.get('sect_levels',()) if cfg else ():
        count=sum(n>=row['building_level'] for n in levels)
        complete=count>=row['building_count'] and cleared_floor>=row['cleared_floor']
        if complete:level=row['level']
        rows.append({**row,'current_building_count':count,'current_cleared_floor':cleared_floor,'complete':complete})
    return {'level':level,'next':next((r for r in rows if r['level']>level),None),'conditions':rows}

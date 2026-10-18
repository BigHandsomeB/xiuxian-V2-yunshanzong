"""@module systems/sect/buildings
@purpose One building instance partition, completed level and deterministic capability.
@depends core/state,core/validation,data/buildings, data/registry
@usedBy application/sect, tests/systems/test_buildings
@see ./INDEX.md
"""
from src.core.state.projection import checked_partition
from collections.abc import Mapping

from src.core.state.envelope import freeze_json
from src.core.validation import ValidationError, NotFoundError, integer, uuid4_id
from src.data.buildings.definitions import BuildingDefinition, DEFAULT_BUILDINGS
from src.data.registry import DefinitionKey


def definition(registry, kind):
    result=registry.lookup(DefinitionKey('buildings',kind))
    if not isinstance(result,BuildingDefinition):
        raise ValidationError('building requires BuildingDefinition')
    return result


def instance_id(value):
    if type(value) is not str or len(value.split(':')) != 4:
        raise ValidationError('building instance id requires save:generation:i:counter')
    save,generation,marker,counter=value.split(':')
    uuid4_id(save,'instance save_id')
    if marker != 'i' or any(not part.isdecimal() or str(int(part)) != part or int(part)<1
                            for part in (generation,counter)):
        raise ValidationError('invalid building instance identity')
    return save


def _rows(partition):
    if not isinstance(partition,Mapping) or set(partition) != {'buildings'}:
        raise ValidationError('sect requires exactly buildings')
    if not isinstance(partition['buildings'],Mapping):
        raise ValidationError('buildings must be an instance object')
    return partition['buildings']


@checked_partition
def validate(partition, registry, *, save_id=None):
    for identity,row in _rows(partition).items():
        owner=instance_id(identity)
        if save_id is not None and owner != save_id:
            raise ValidationError('building instance belongs to another Save')
        if not isinstance(row,Mapping) or set(row) != {'definition_id','level','construction_target'}:
            raise ValidationError('building requires definition_id/level/construction_target')
        d=definition(registry,row['definition_id']);level=row['level'];target=row['construction_target']
        integer(level,'completed building level')
        if level>d.max_level:raise ValidationError('building above maximum level')
        if target is not None:
            integer(target,'construction_target',1)
            if target != level+1 or target>d.max_level:
                raise ValidationError('construction target must be next valid level')
        elif level==0:
            raise ValidationError('level0 requires initial construction target1')
    return partition


def initial(save_id, generation):
    uuid4_id(save_id,'save_id');integer(generation,'generation',1)
    return freeze_json({'buildings': {f'{save_id}:{generation}:i:{i}':
        {'definition_id':kind,'level':1,'construction_target':None}
        for i,kind in enumerate(DEFAULT_BUILDINGS,1)}})


def get_building(partition, registry, identity):
    validate(partition,registry)
    try:return freeze_json(partition['buildings'][identity])
    except (KeyError,TypeError) as exc:raise NotFoundError('unknown building instance') from exc


def get_level(partition, registry, identity):
    return get_building(partition,registry,identity)['level']


def capability(partition, registry):
    validate(partition,registry)
    effective={key: row['level'] for key,row in sorted(partition['buildings'].items()) if row['level']>0}
    warehouse=sum(row['level'] for row in partition['buildings'].values() if row['definition_id']=='warehouse')
    return freeze_json({'effective_levels':effective,'warehouse_levels':warehouse})


def references(snapshot):
    if 'sect' not in snapshot.domains:raise ValidationError('sect partition missing')
    refs=[]
    for identity,row in _rows(snapshot.domains['sect']).items():
        if instance_id(identity) != snapshot.save_id:
            raise ValidationError('building instance belongs to another Save')
        _,generation,_,counter=identity.split(':')
        if int(generation)>snapshot.generation or int(counter)>snapshot.identity['instance_counter']:
            raise ValidationError('building instance identity exceeds committed counters/lineage')
        if not isinstance(row,Mapping) or 'definition_id' not in row:
            raise ValidationError('building definition reference missing')
        refs.append(DefinitionKey('buildings',row['definition_id']))
    return tuple(refs)


def work_slots(partition,registry,identity):
    """Derived completed-level work capacity; no slot cache or worker authority."""
    from src.data.buildings.work import BuildingWorkDefinition
    row=get_building(partition,registry,identity)
    rule=registry.lookup(DefinitionKey('building_work',row['definition_id']))
    if not isinstance(rule,BuildingWorkDefinition):raise ValidationError('building work definition required')
    from src.data.economy.sect_rules import settings
    cfg=settings(registry)
    enabled=rule.enabled or bool(cfg and cfg.get('management') and row['definition_id']=='spring')
    return row['level']*rule.slots_per_level if enabled else 0

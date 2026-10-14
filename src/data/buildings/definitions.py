"""@module data/buildings/definitions
@purpose Immutable real building rules and explicit single Registry content composition.
@depends data/registry, data/items/resources, core/validation, standard library
@usedBy systems/sect/buildings, application/sect
@see ./INDEX.md
"""
from dataclasses import dataclass
import json
from pathlib import Path

from src.core.validation import DuplicateError, ValidationError, integer, schema_version
from src.data.registry import Definition, DefinitionKey, _fields
from src.data.items.resources import load_resources

CONSTRUCTION_WORK_SECONDS = 60
DEFAULT_BUILDINGS = ('house', 'house', 'field', 'canteen', 'forest', 'quarry',
                     'mine', 'garden', 'alchemy', 'forge', 'builders', 'warehouse')


@dataclass(frozen=True, slots=True)
class BuildingDefinition(Definition):
    max_level: int = 10
    unlock_floor: int = 0
    unlock_realm: int = 0
    cost: tuple = ()

    def __post_init__(self):
        super(BuildingDefinition, self).__post_init__()
        if self.domain != 'buildings':
            raise ValidationError('building requires buildings namespace')
        integer(self.max_level, 'max_level', 1)
        integer(self.unlock_floor, 'unlock_floor')
        integer(self.unlock_realm, 'unlock_realm')
        if type(self.cost) is not tuple:
            raise ValidationError('building costs must be immutable pairs')
        keys=[]
        for pair in self.cost:
            if type(pair) is not tuple or len(pair) != 2:
                raise ValidationError('invalid building cost pair')
            key,amount=pair
            DefinitionKey('resources', key);integer(amount, 'building cost')
            keys.append(key)
        if len(keys) != len(set(keys)):
            raise DuplicateError('duplicate building cost')
        if self.references != tuple(DefinitionKey('resources', key) for key in keys):
            raise ValidationError('building references must match cost resources')


def load_content(source=None, *, seal=True):
    """New explicit composed package; no old Save conversion or hot reload."""
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise DuplicateError('duplicate building JSON key')
            result[key]=value
        return result
    if source is None:
        source=Path(__file__).with_name('buildings.json').read_text(encoding='utf-8')
    try:
        package=json.loads(source,object_pairs_hook=unique)
    except (TypeError,json.JSONDecodeError) as exc:
        raise ValidationError('invalid building JSON') from exc
    _fields(package, ('schema_version','content_version','definitions'))
    if type(package['definitions']) is not list:
        raise ValidationError('building definitions must be an array')
    schema_version(package['schema_version'],'data_schema_version')
    resources=json.loads(Path(__file__).parents[1].joinpath('items/resources.json').read_text(),object_pairs_hook=unique)
    if package['schema_version'] != resources['schema_version']:
        raise ValidationError('content component schemas differ')
    # Composition defines a new package version, not a migration of any stored Save.
    resources['content_version']=package['content_version']
    registry=load_resources(json.dumps(resources),seal=False)
    for row in package['definitions']:
        _fields(row, ('machine_id','display_name','max_level','unlock_floor','unlock_realm','cost'))
        if type(row['cost']) is not dict:
            raise ValidationError('cost must be a resource object')
        cost=tuple(sorted(row['cost'].items()))
        refs=tuple(DefinitionKey('resources',key) for key,_ in cost)
        registry.register(BuildingDefinition('buildings',row['machine_id'],row['display_name'],refs,
                          row['max_level'],row['unlock_floor'],row['unlock_realm'],cost))
    if type(seal) is not bool:raise ValidationError('seal must be boolean')
    if seal:registry.seal()
    return registry

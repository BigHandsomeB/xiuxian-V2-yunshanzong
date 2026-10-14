"""@module data/items/resources
@purpose Real V1 resource definitions, immutable metadata and existing Registry loading.
@depends data/registry, core/validation, standard library
@usedBy systems/inventory, application/inventory
@see ./INDEX.md
"""
from dataclasses import dataclass
from pathlib import Path
import json

from src.core.validation import DuplicateError, ValidationError, integer
from src.data.registry import Definition, DefinitionRegistry, _fields

BASE_CAPACITY = 5000
CAPACITY_PER_WAREHOUSE_LEVEL = 2000


@dataclass(frozen=True, slots=True)
class ResourceDefinition(Definition):
    capacity_counted: bool = True
    grade: int | None = None
    tier: str = "待定"

    @property
    def warehouse_counted(self):
        """Personal pills live in the unlimited backpack; materials retain their capacity rule."""
        key = self.machine_id
        personal = key == 'pill' or key.startswith('pill_') or key.endswith('_pill')
        return self.capacity_counted and not personal

    def __post_init__(self):
        super(ResourceDefinition, self).__post_init__()
        if self.domain != 'resources' or type(self.capacity_counted) is not bool:
            raise ValidationError('resource requires resources namespace and boolean capacity_counted')
        if self.tier not in ('待定','凡','灵','玄','地','天','仙'):
            raise ValidationError('invalid item tier')
        if self.grade is not None:
            integer(self.grade, 'resource grade', 1)


def warehouse_capacity(warehouse_levels):
    """Derived input only; caller owns effective warehouse levels, not Inventory."""
    integer(warehouse_levels, 'warehouse_levels')
    return BASE_CAPACITY + CAPACITY_PER_WAREHOUSE_LEVEL * warehouse_levels


def load_resources(source=None, *, seal=True):
    """Explicit content load; import never performs disk IO or loads V1."""
    if source is None:
        source = Path(__file__).with_name('resources.json').read_text(encoding='utf-8')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise DuplicateError('duplicate resource JSON key: ' + key)
            result[key] = value
        return result
    def invalid_constant(value):
        raise ValidationError('non-finite resource JSON: ' + value)
    try:
        package = json.loads(source, object_pairs_hook=unique, parse_constant=invalid_constant)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValidationError('malformed resource JSON') from exc
    _fields(package, ('schema_version', 'content_version', 'definitions'))
    if type(package['definitions']) is not list:
        raise ValidationError('resource definitions must be an array')
    registry = DefinitionRegistry(schema_version=package['schema_version'],
                                  content_version=package['content_version'])
    for row in package['definitions']:
        _fields(row, ('domain', 'machine_id', 'display_name', 'capacity_counted', 'grade'), ('tier',))
        registry.register(ResourceDefinition(**row))
    if type(seal) is not bool:
        raise ValidationError('seal must be boolean')
    if seal:
        registry.seal()
    return registry

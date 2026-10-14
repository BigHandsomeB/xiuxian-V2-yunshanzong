"""@module systems/inventory/holdings
@purpose Inventory partition ownership, pure validation and immutable projections.
@depends data/registry, data/items/resources, core/validation, core/state
@usedBy systems/inventory/operations, application/inventory
@see ./INDEX.md
"""
from collections.abc import Mapping

from src.core.state.envelope import freeze_json
from src.core.validation import ValidationError, integer
from src.data.registry import DefinitionKey
from src.data.items.resources import ResourceDefinition


def definition(registry, resource_id):
    value = registry.lookup(DefinitionKey('resources', resource_id))
    if not isinstance(value, ResourceDefinition):
        raise ValidationError('holding requires ResourceDefinition')
    return value


def _holdings(partition):
    if not isinstance(partition, Mapping) or set(partition) != {'holdings'}:
        raise ValidationError('inventory requires exactly holdings')
    holdings = partition['holdings']
    if not isinstance(holdings, Mapping):
        raise ValidationError('holdings must be an object')
    return holdings


def validate(partition, registry):
    for key, quantity in _holdings(partition).items():
        definition(registry, key)
        integer(quantity, 'held quantity', 1)
    return partition


def initial():
    return freeze_json({'holdings': {}})


def get_quantity(partition, registry, resource_id):
    validate(partition, registry)
    definition(registry, resource_id)
    return partition['holdings'].get(resource_id, 0)


def has(partition, registry, resource_id, amount=1):
    integer(amount, 'required quantity')
    return get_quantity(partition, registry, resource_id) >= amount


def project(partition, registry):
    """Immutable canonical projection, no second authority or mutable dict leak."""
    validate(partition, registry)
    return freeze_json(dict(sorted(partition['holdings'].items())))


def stock_size(partition, registry):
    validate(partition, registry)
    return sum(quantity for key, quantity in partition['holdings'].items()
               if definition(registry, key).warehouse_counted)


def references(snapshot):
    """Inventory owns only its references; future composition stays Application-side."""
    if 'inventory' not in snapshot.domains:
        raise ValidationError('inventory partition missing')
    return tuple(DefinitionKey('resources', key)
                 for key in sorted(_holdings(snapshot.domains['inventory'])))

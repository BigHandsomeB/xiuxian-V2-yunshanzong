"""@module systems/inventory/operations
@purpose Pure atomic grant/consume with real warehouse overflow semantics.
@depends systems/inventory/holdings, core/state, core/validation
@usedBy application/inventory, future trusted cross-Domain coordination
@see ./INDEX.md
"""
from collections.abc import Mapping

from src.core.state.envelope import freeze_json
from src.core.validation import ValidationError, integer
from src.systems.inventory.holdings import definition, validate, stock_size


class InsufficientResources(ValidationError):
    """A valid consumption intent cannot be funded; no candidate is applied."""


def _intent(amounts, registry):
    if not isinstance(amounts, Mapping):
        raise ValidationError('resource amounts must be an object')
    for key, quantity in amounts.items():
        definition(registry, key)
        integer(quantity, 'intent quantity')
    return sorted(amounts.items())


def _candidate(holdings, registry):
    result = {'holdings': dict(sorted((key, value) for key, value in holdings.items() if value))}
    validate(result, registry)
    return freeze_json(result)


def consume(partition, registry, amounts):
    validate(partition, registry)
    intent = _intent(amounts, registry)
    current = partition['holdings']
    for key, quantity in intent:
        if current.get(key, 0) < quantity:
            raise InsufficientResources('insufficient resource: ' + key)
    candidate = dict(current)
    for key, quantity in intent:
        candidate[key] = candidate.get(key, 0) - quantity
    return _candidate(candidate, registry), freeze_json({'consumed': dict(intent)})


def grant(partition, registry, amounts, *, capacity):
    validate(partition, registry)
    integer(capacity, 'inventory capacity')
    intent = _intent(amounts, registry)  # Entire batch validated before allocation.
    available = max(0, capacity - stock_size(partition, registry))
    candidate = dict(partition['holdings'])
    accepted, discarded = {}, {}
    for key, quantity in intent:
        counted = definition(registry, key).warehouse_counted
        kept = min(quantity, available) if counted else quantity
        if counted:
            available -= kept
        candidate[key] = candidate.get(key, 0) + kept
        accepted[key], discarded[key] = kept, quantity - kept
    return _candidate(candidate, registry), freeze_json({'accepted': accepted, 'discarded': discarded})

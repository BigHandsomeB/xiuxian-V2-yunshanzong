"""@module application/inventory
@purpose Trusted internal Inventory operations using existing Foundation coordination.
@depends application/memory,persistent, systems/inventory, core/state, data/items
@usedBy tests/systems/test_inventory; future explicitly authorized source coordination
@see ./INDEX.md
"""
from src.application.memory import CommandSpec, MemoryApplication
from src.application.persistent import PersistentApplication
from src.core.state.envelope import StateEnvelope, thaw_json
from src.core.validation import ValidationError, integer
from src.systems.inventory import holdings, operations


def commands(registry, *, capacity):
    """Internal capability, NOT a player-facing grant API or policy authority.

    capacity is a trusted derived input for this configured operation context.
    Future building coordination must supply its current effective limit.
    """
    integer(capacity, 'inventory capacity')
    def transition(operation):
        def apply(partition, payload):
            if set(payload) != {'amounts'}:
                raise ValidationError('inventory intent requires exactly amounts')
            if operation == 'grant':
                candidate, result = operations.grant(partition, registry, payload['amounts'], capacity=capacity)
            else:
                candidate, result = operations.consume(partition, registry, payload['amounts'])
            partition.clear()
            partition.update(thaw_json(candidate))
            return result
        return apply
    return {name: CommandSpec('inventory', transition(operation))
            for operation, name in [('grant', 'inventory_grant'), ('consume', 'inventory_consume')]}


def new_state(registry, *, last_settled_at_ms):
    return StateEnvelope.create(content_version=registry.content_version,
                                data_schema_version=registry.schema_version,
                                domains={'inventory': holdings.initial()},
                                last_settled_at_ms=last_settled_at_ms)


def memory(state, registry, *, capacity):
    holdings.validate(state.domains['inventory'], registry)
    return MemoryApplication(state, registry, commands(registry, capacity=capacity))


def persistent(store, registry, *, capacity):
    return PersistentApplication(store, registry, commands(registry, capacity=capacity),
                                 references=holdings.references,
                                 validators={'inventory': lambda partition: holdings.validate(partition, registry)})


def query_quantity(application, registry, resource_id, *, save_id=None):
    snapshot = application.query() if save_id is None else application.query(save_id)
    return holdings.get_quantity(snapshot.domains['inventory'], registry, resource_id)

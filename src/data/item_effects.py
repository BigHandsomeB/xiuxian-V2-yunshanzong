"""Immutable use bindings derived from one sealed registry; no new content values."""
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from src.core.state.envelope import freeze_json
from src.core.validation import ValidationError
from src.data.registry import DefinitionKey, _fields
from src.data.cultivation.definitions import CultivationAction
from src.data.economy.sect_rules import settings
from src.data.items.resources import ResourceDefinition

EFFECT_TYPES = frozenset({'cultivation_pill'})
USE_COMMANDS = frozenset({'cultivation_train', 'cultivation_use_pill'})


@dataclass(frozen=True, slots=True)
class ItemUseBinding:
    command: str
    item_id: str
    effect_type: str
    parameters: Mapping


def validate_bindings(registry, rows):
    """Strict schema, references and uniqueness; returns a frozen dispatch table."""
    if not registry.is_sealed:
        raise ValidationError('item effects require a sealed registry')
    bindings = {}
    for row in rows:
        _fields(row, ('command', 'item_id', 'effect_type', 'parameters'))
        command, item, effect = row['command'], row['item_id'], row['effect_type']
        if type(command) is not str or command not in USE_COMMANDS:
            raise ValidationError('unsupported item use command')
        if type(effect) is not str or effect not in EFFECT_TYPES:
            raise ValidationError('unsupported item effect type')
        # cultivation_pill takes its values from the owning registry, never from requests.
        if not isinstance(row['parameters'], Mapping) or row['parameters']:
            raise ValidationError('cultivation_pill requires empty parameters')
        key = DefinitionKey('resources', item)
        if not registry.contains(key) or not isinstance(registry.lookup(key), ResourceDefinition):
            raise ValidationError('item effect references a missing resource')
        if command == 'cultivation_train' and item != 'pill':
            raise ValidationError('legacy train must use its existing pill')
        identity = (command, item)
        if identity in bindings:
            raise ValidationError('duplicate item use binding')
        bindings[identity] = ItemUseBinding(command, item, effect, freeze_json({}))
    return MappingProxyType(bindings)


def bindings_for(registry):
    """Version-local adapter: historical actions and current levels keep their rules."""
    action = registry.lookup(DefinitionKey('cultivation_actions', 'pill_train'))
    if not isinstance(action, CultivationAction):
        raise ValidationError('registered cultivation action required')
    cfg = settings(registry) or {}
    pills = (cfg.get('leveling') or cfg.get('foundation_cultivation') or {}).get('pills', {})
    rows = [{'command': 'cultivation_train', 'item_id': action.required_item_id,
             'effect_type': 'cultivation_pill', 'parameters': {}}]
    rows.extend({'command': 'cultivation_use_pill', 'item_id': item,
                 'effect_type': 'cultivation_pill', 'parameters': {}} for item in pills)
    return validate_bindings(registry, rows)

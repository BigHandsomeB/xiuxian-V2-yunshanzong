"""Trusted, pure item effect handlers. Application owns inventory and persistence."""
from dataclasses import dataclass
from types import MappingProxyType

from src.core.state.envelope import freeze_json
from src.core.validation import ValidationError
from src.data.item_effects import EFFECT_TYPES
from . import growth


@dataclass(frozen=True, slots=True)
class ItemEffectResult:
    cultivation: object
    costs: object
    events: object


def _cultivation_pill(binding, p, registry, save_id, stock, active, count, world_ms):
    if binding.command == 'cultivation_train':
        candidate, events = growth.train(p, registry, save_id, stock, active,
                                         count=count, world_ms=world_ms)
    else:
        candidate, events = growth.use_foundation_pill(
            p, registry, save_id, stock, binding.item_id, active,
            count=count, world_ms=world_ms)
    consumed = events[0]
    if consumed['kind'] != 'pill_consumed' or consumed['item_id'] != binding.item_id:
        raise ValidationError('pill handler consumption differs from binding')
    return ItemEffectResult(candidate, freeze_json({binding.item_id: consumed['quantity']}), events)


HANDLERS = MappingProxyType({'cultivation_pill': _cultivation_pill})


def validate_handlers(bindings):
    if set(HANDLERS) != EFFECT_TYPES or any(not callable(fn) for fn in HANDLERS.values()):
        raise ValidationError('item effect handler table differs from supported schema')
    if any(binding.effect_type not in HANDLERS for binding in bindings.values()):
        raise ValidationError('item effect handler missing')


def apply(bindings, command, item_id, p, registry, save_id, stock, active=False,
          *, count=1, world_ms=0):
    if type(item_id) is not str:
        raise ValidationError('item ID must be a string')
    binding = bindings.get((command, item_id))
    if binding is None:
        message = '此丹药不能增加修为' if growth.leveling.config(registry) else '筑基修炼丹尚未开放'
        raise ValidationError(message)
    return HANDLERS[binding.effect_type](binding, p, registry, save_id, stock,
                                       active, count, world_ms)

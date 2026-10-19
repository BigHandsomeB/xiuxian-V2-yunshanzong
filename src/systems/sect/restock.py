"""Optional stock targets and day-boundary events; no inventory or time authority."""
from collections.abc import Mapping
from src.core.validation import ValidationError, integer
from src.data.economy.market import settings


def empty():
    return {'targets': {}, 'wake': None, 'log': []}


def validate(part, registry):
    if not isinstance(part, Mapping) or set(part) != {'targets', 'wake', 'log'}:
        raise ValidationError('invalid market restock policy')
    if not isinstance(part['targets'], Mapping):
        raise ValidationError('购买清单格式不正确')
    for rid, target in part['targets'].items():
        if type(rid) is not str or rid not in settings(registry)['items']:
            raise ValidationError('请选择正式交易材料')
        integer(target, '库存保有量', 1)
        if target > 10000:
            raise ValidationError('库存保有量不能超过10000')
    wake = part['wake']
    if wake is not None:
        if not isinstance(wake, Mapping) or set(wake) != {'event_id', 'next_event_id', 'due_ms'} or type(wake['event_id']) is not str or (wake['next_event_id'] is not None and type(wake['next_event_id']) is not str):
            raise ValidationError('invalid restock event')
        integer(wake['due_ms'], 'restock due', 1)
        if not part['targets']:
            raise ValidationError('empty restock policy has an event')
    if not isinstance(part['log'], (list, tuple)) or len(part['log']) > 20:
        raise ValidationError('bounded restock log required')
    for row in part['log']:
        if not isinstance(row, Mapping) or set(row) != {'resource_id', 'quantity', 'coins', 'sim_ms'} or row['resource_id'] not in settings(registry)['items']:
            raise ValidationError('invalid restock log')
        for key in ('quantity', 'coins', 'sim_ms'):
            integer(row[key], key, 0 if key == 'sim_ms' else 1)
    return part

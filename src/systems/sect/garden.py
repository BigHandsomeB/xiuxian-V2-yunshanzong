"""Independent cultivated plots; accrual uses the existing ecology event/clock."""
from collections.abc import Mapping
from src.core.validation import ValidationError, integer
from src.data.economy.ecology import settings
from src.data.economy.sect_rules import settings as sect_settings
from src.systems.resources import jobs

COMMANDS = ('garden_reclaim', 'garden_plant', 'garden_repeat')
FIELDS = {'plant_id', 'recipe_id', 'planted_ms', 'progress_milli', 'rate_milli',
          'base_rate_milli', 'yield_milli', 'extra_bps'}


def crops(registry):
    cfg = settings(registry)
    return tuple(key for key in sect_settings(registry)['production_whitelist']
                 if key not in cfg['retired_recipes']
                 and jobs.definition(registry, key).building_kind == 'garden'
                 and not jobs.definition(registry, key).facility_output_id)


def plots(part, bid):
    return part.get('garden', {}).get(bid, {})


def ready(row, registry):
    return row['progress_milli'] >= jobs.definition(registry, row['recipe_id']).duration_ms * 1000


def validate(owned, registry):
    if not isinstance(owned, Mapping):
        raise ValidationError('invalid garden plots')
    if not owned:
        return
    allowed = set(crops(registry))
    seen = set()
    for bid, field in owned.items():
        if type(bid) is not str or not isinstance(field, Mapping):
            raise ValidationError('invalid garden field')
        for key, row in field.items():
            if type(key) is not str or not key.isascii() or not key.isdecimal() or str(int(key)) != key:
                raise ValidationError('invalid plot index')
            if row is None:
                continue
            if not isinstance(row, Mapping) or set(row) != FIELDS or row['recipe_id'] not in allowed:
                raise ValidationError('invalid garden plant')
            if type(row['plant_id']) is not str or row['plant_id'] in seen:
                raise ValidationError('invalid garden plant identity')
            seen.add(row['plant_id'])
            for name in FIELDS - {'plant_id', 'recipe_id'}:
                integer(row[name], name, 1 if name in ('yield_milli', 'base_rate_milli') else 0)
            total = jobs.definition(registry, row['recipe_id']).duration_ms * 1000
            if row['progress_milli'] > total or row['rate_milli'] > row['base_rate_milli'] or row['extra_bps'] > 10000:
                raise ValidationError('invalid garden progress/rate')


def accrue(part, registry, elapsed):
    for field in part.get('garden', {}).values():
        for row in field.values():
            if row:
                total = jobs.definition(registry, row['recipe_id']).duration_ms * 1000
                row['progress_milli'] = min(total, row['progress_milli'] + elapsed * row['rate_milli'])


def validate_policies(owned, registry):
    if not isinstance(owned, Mapping):
        raise ValidationError('invalid repeat planting policies')
    allowed = set(crops(registry)) if owned else set()
    for bid, field in owned.items():
        if type(bid) is not str or not isinstance(field, Mapping):
            raise ValidationError('invalid repeat field')
        for index, policy in field.items():
            if type(index) is not str or not index.isascii() or not index.isdecimal() or str(int(index)) != index:
                raise ValidationError('invalid repeat plot')
            if not isinstance(policy, Mapping) or set(policy) != {'recipe_id', 'enabled'} or type(policy['enabled']) is not bool or policy['recipe_id'] not in allowed:
                raise ValidationError('invalid repeat planting choice')

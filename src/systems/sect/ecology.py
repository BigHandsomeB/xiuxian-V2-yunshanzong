"""Bounded live-stock groups, facility facts and one shared simulation event.

Inventory and workforce remain owned by their existing domains. This module
owns only husbandry progress and nutrition policy; Application pays resources.
"""
from collections.abc import Mapping
from src.core.state.envelope import freeze_json
from src.core.time.model import Event, SimulationDomain
from src.core.validation import ValidationError, integer
from src.data.economy.ecology import settings, lookup

DOMAIN = 'ecology'
BATCH_FIELDS = {'species_id', 'building_id', 'count', 'stage', 'progress_milli',
                'feed_paid', 'rate_milli', 'cycle_rate_milli', 'extra_bps', 'cycle',
                'last_collection_ms', 'reason'}


def initial():
    return freeze_json({
        'schema_version': 1, 'batches': {}, 'facilities': {}, 'job_effects': {},
        'meals': {}, 'wake': None, 'tick_ready': False,
        'supply': {'activated': False, 'enabled': False, 'target_days': 3,
                   'next_day_ms': None, 'served': {}, 'hungry': {},
                   'people_snapshot': {}, 'legacy_until_ms': 0,
                   'legacy_covered_count': 0, 'last_day_ms': None}})


def capacity(state, registry, building_id):
    row = state.domains['sect']['buildings'][building_id]
    level, kind = row['level'], row['definition_id']
    cfg = settings(registry)['limits']
    if kind == 'garden':
        base = level * cfg['base_plots_per_level']
    elif kind == 'pasture':
        base = cfg['base_pasture_slots'] + (level - 1) * cfg['pasture_slots_per_level']
    elif kind == 'spring':
        base = cfg['base_spring_slots'] + (level - 1) * cfg['spring_slots_per_level']
    else:
        return 0
    return base + sum(n * lookup(registry, 'facilities', fid)['capacity']
                      for fid, n in state.domains[DOMAIN]['facilities'].get(building_id, {}).items())


def occupied(partition, registry, building_id):
    return sum(row['count'] * lookup(registry, 'species', row['species_id'])['slots']
               for row in partition['batches'].values() if row['building_id'] == building_id)


def total_work(batch, registry, day_length_ms):
    return lookup(registry, 'species', batch['species_id'])['days'] * day_length_ms * 1000


def total_feed(batch, registry):
    return lookup(registry, 'species', batch['species_id'])['feed_quantity'] * batch['count']


def credit_limit(batch, registry, day_length_ms):
    return total_work(batch, registry, day_length_ms) * batch['feed_paid'] // total_feed(batch, registry)


def validate(partition, registry):
    fields = {'schema_version', 'batches', 'facilities', 'job_effects', 'meals',
              'wake', 'tick_ready', 'supply'}
    if not isinstance(partition, Mapping) or set(partition) != fields or partition['schema_version'] != 1:
        raise ValidationError('invalid ecology partition')
    for key in ('batches', 'facilities', 'job_effects', 'meals'):
        if not isinstance(partition[key], Mapping):
            raise ValidationError('ecology maps required')
    if len(partition['batches']) > settings(registry)['limits']['max_batches']:
        raise ValidationError('养殖批次达到上限')
    for identity, row in partition['batches'].items():
        if type(identity) is not str or not isinstance(row, Mapping) or set(row) != BATCH_FIELDS:
            raise ValidationError('invalid husbandry group')
        species = lookup(registry, 'species', row['species_id'])
        if row['stage'] not in ('JUVENILE', 'MATURE', 'READY') or type(row['building_id']) is not str:
            raise ValidationError('invalid husbandry lifecycle')
        for key in ('count', 'progress_milli', 'feed_paid', 'rate_milli',
                    'cycle_rate_milli', 'extra_bps', 'cycle', 'last_collection_ms'):
            integer(row[key], key, 1 if key == 'count' else 0)
        if row['count'] > settings(registry)['limits']['max_count'] or row['extra_bps'] > 10000:
            raise ValidationError('husbandry group exceeds bounds')
        if row['feed_paid'] > species['feed_quantity'] * row['count']:
            raise ValidationError('husbandry feed overpayment')
        if row['stage'] == 'JUVENILE' and row['cycle'] != 0:
            raise ValidationError('juvenile cannot have produced')
        if type(row['reason']) is not str:
            raise ValidationError('husbandry reason required')
    for bid, row in partition['facilities'].items():
        if type(bid) is not str or not isinstance(row, Mapping):
            raise ValidationError('invalid facility ownership')
        for fid, count in row.items():
            lookup(registry, 'facilities', fid)
            integer(count, 'completed facilities', 1)
    for bid, row in partition['meals'].items():
        if type(bid) is not str or set(row) != {'meal_id', 'enabled', 'covered_count', 'expires_ms'}:
            raise ValidationError('invalid position meal slot')
        meal = lookup(registry, 'meals', row['meal_id'])
        if meal['basic'] or type(row['enabled']) is not bool:
            raise ValidationError('position meal requires a buff meal')
        integer(row['covered_count'], 'meal coverage')
        integer(row['expires_ms'], 'meal expiry')
    for jid, row in partition['job_effects'].items():
        if type(jid) is not str or set(row) != {'extra_bps', 'discovery_bps', 'meal_id'}:
            raise ValidationError('invalid production meal snapshot')
        for key in ('extra_bps', 'discovery_bps'):
            integer(row[key], key)
            if row[key] > 10000:
                raise ValidationError('production probability outside bounds')
        if row['meal_id'] is not None:
            lookup(registry, 'meals', row['meal_id'])
    supply = partition['supply']
    expected = {'activated', 'enabled', 'target_days', 'next_day_ms', 'served', 'hungry',
                'people_snapshot', 'legacy_until_ms', 'legacy_covered_count', 'last_day_ms'}
    if not isinstance(supply, Mapping) or set(supply) != expected:
        raise ValidationError('invalid daily supply state')
    if any(type(supply[key]) is not bool for key in ('activated', 'enabled')):
        raise ValidationError('invalid supply switch')
    integer(supply['target_days'], 'supply reserve days', 3)
    if supply['target_days'] > 7:
        raise ValidationError('口粮储备为3至7游戏日')
    for key in ('served', 'hungry', 'people_snapshot'):
        if not isinstance(supply[key], Mapping):
            raise ValidationError('nutrition census required')
        for gid, count in supply[key].items():
            if type(gid) is not str:
                raise ValidationError('nutrition group reference required')
            integer(count, 'nutrition count')
    for key in ('legacy_until_ms', 'legacy_covered_count'):
        integer(supply[key], key)
    for key in ('next_day_ms', 'last_day_ms'):
        if supply[key] is not None:
            integer(supply[key], key)
    if type(partition['tick_ready']) is not bool:
        raise ValidationError('ecology tick flag required')
    wake = partition['wake']
    if wake is not None:
        if not isinstance(wake, Mapping) or set(wake) != {'event_id', 'next_event_id', 'due_ms'} or type(wake['event_id']) is not str:
            raise ValidationError('invalid shared ecology event')
        integer(wake['due_ms'], 'ecology wake due')
        if wake['next_event_id'] is not None and type(wake['next_event_id']) is not str:
            raise ValidationError('invalid ecology successor identity')
    return partition


def simulation(registry, day_length_ms):
    def events(partition):
        wake = partition['wake']
        return (Event(wake['event_id'], DOMAIN, wake['due_ms'], 5, {}),) if wake else ()

    def accrue(partition, start, end):
        for row in partition['batches'].values():
            if row['stage'] == 'READY' or not row['rate_milli']:
                continue
            row['progress_milli'] = min(total_work(row, registry, day_length_ms),
                                       credit_limit(row, registry, day_length_ms),
                                       row['progress_milli'] + (end - start) * row['rate_milli'])

    def apply(partition, event):
        # Keep a strictly-forward, preallocated successor until Application
        # dispatch. Otherwise Core could accrue to the window target before
        # daily food or a maturity transition is committed at this boundary.
        successor = partition['wake']['next_event_id']
        if successor is None:
            raise ValidationError('ecology successor must be allocated before settlement')
        partition['wake'] = {'event_id': successor, 'next_event_id': None,
                             'due_ms': event.due_sim_ms + 1}
        partition['tick_ready'] = True

    return SimulationDomain(events, apply, accrue, lambda part: validate(part, registry))

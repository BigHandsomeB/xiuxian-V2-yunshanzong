"""Deterministic cohort-count supply and position meals, no individual roster."""
from src.data.economy.ecology import settings, lookup
from src.systems.disciples import work


def basic_ids(registry):
    return tuple(row['id'] for row in settings(registry)['meals'] if row['basic'])


def basic_stock(state, registry):
    stock = state.domains['inventory']['holdings']
    return sum(stock.get(rid, 0) for rid in basic_ids(registry))


def people(state):
    return sum(row['count'] for row in state.domains['disciples']['groups'].values())


def matching(meal, kind):
    return meal['scope'] == 'all' or meal['scope'] == kind or (
        meal['scope'] == 'gather' and kind in ('mine', 'forest', 'quarry'))


def penalty_bps(state, building_id):
    count = 0
    affected = 0
    hungry = state.domains['ecology']['supply']['hungry']
    groups = state.domains['disciples']['groups']
    for gid, group in groups.items():
        targets = work.allocations(state.domains['disciples'], gid)
        before = sum(n for bid, n in sorted(targets.items()) if bid < building_id)
        assigned = state.domains['disciples']['assignments'].get(gid, {}).get(building_id, 0)
        served = group['count'] - min(group['count'], hungry.get(gid, 0))
        affected += max(0, before + assigned - max(before, served))
        count += assigned
    return 3000 * affected // count if count else 0


def effects(state, registry, building_id):
    kind = state.domains['sect']['buildings'][building_id]['definition_id']
    workers = work.capability(state.domains['disciples'], registry, building_id)['workers']
    slot = state.domains['ecology']['meals'].get(building_id)
    result = {'speed_bps': 0, 'extra_bps': 0, 'discovery_bps': 0, 'meal_id': None}
    if slot and slot['expires_ms'] > state.time['sim_time_ms'] and workers:
        meal = lookup(registry, 'meals', slot['meal_id'])
        if matching(meal, kind):
            for key in ('speed_bps', 'extra_bps', 'discovery_bps'):
                result[key] = meal[key] * min(workers, slot['covered_count']) // workers
            result['meal_id'] = meal['id']
    facility_bonus = sum(n * lookup(registry, 'facilities', fid)['speed_bps']
                         for fid, n in state.domains['ecology']['facilities'].get(building_id, {}).items())
    result['rate_milli'] = max(500, 1000 + min(5000, facility_bonus + result['speed_bps']) // 10
                              - penalty_bps(state, building_id) // 10)
    return result


def protected_inputs(state, registry):
    """Reserve the rice chain needed to meet the explicit basic-meal target."""
    supply = state.domains['ecology']['supply']
    if not supply['activated']:
        return {}
    missing = max(0, people(state) * supply['target_days'] - basic_stock(state, registry))
    rice = next(row for row in settings(registry)['recipes'] if row['machine_id'] == 'meal_qingling_rice')
    portions = rice['outputs']['meal_qingling_rice']
    return {rid: (n * missing + portions - 1) // portions for rid, n in rice['inputs'].items()}

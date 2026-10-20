"""Optional per-recipe cohort allocations, subordinate to the existing assignments."""
from collections.abc import Mapping
from src.core.state.envelope import thaw_json, freeze_json
from src.core.validation import ValidationError, integer
from src.data.registry import DefinitionKey


def workers(part, bid, recipe):
    return part.get('recipe_assignments', {}).get(bid, {}).get(recipe, {})


def planned(part, bid):
    return bid in part.get('recipe_assignments', {})


def claims(part, group):
    assigned = part['assignments'].get(group, {})
    desired = {}
    for bid, recipes in part.get('recipe_assignments', {}).items():
        desired[bid] = {rid: rows.get(group, 0) for rid, rows in recipes.items()}
    held = {}
    for row in part['commitments'].values():
        bucket = held.setdefault(row['building_id'], {})
        rid = row.get('recipe_id')
        bucket[rid] = bucket.get(rid, 0) + row['workers'].get(group, 0)
    result = {}
    for bid in set(assigned) | set(held):
        recipes = desired.get(bid, {})
        commitments = held.get(bid, {})
        generic = assigned.get(bid, 0) - sum(recipes.values())
        count = max(generic, commitments.get(None, 0))
        count += sum(max(recipes.get(rid, 0), commitments.get(rid, 0))
                     for rid in (set(recipes) | set(commitments)) - {None})
        if count:
            result[bid] = count
    return result


def validate(part, registry):
    plans = part.get('recipe_assignments', {})
    if not isinstance(plans, Mapping):
        raise ValidationError('recipe assignments must be an object')
    for bid, recipes in plans.items():
        if type(bid) is not str or not isinstance(recipes, Mapping):
            raise ValidationError('invalid recipe assignment building')
        totals = {}
        for rid, rows in recipes.items():
            if type(rid) is not str or not isinstance(rows, Mapping) or not rows:
                raise ValidationError('invalid recipe workforce')
            registry.lookup(DefinitionKey('production', rid))
            for gid, count in rows.items():
                if gid not in part['groups']:
                    raise ValidationError('recipe workforce source missing')
                integer(count, 'recipe workers', 1)
                totals[gid] = totals.get(gid, 0) + count
        for gid, count in totals.items():
            if count > part['assignments'].get(gid, {}).get(bid, 0):
                raise ValidationError('recipe workers exceed building assignment')


def materialize(part, bid, fallback=None, active_recipe=None):
    result = thaw_json(part)
    if planned(part, bid):
        return result
    recipes = result.setdefault('recipe_assignments', {}).setdefault(bid, {})
    if fallback:
        rows = {g: targets[bid] for g, targets in part['assignments'].items() if targets.get(bid)}
        if rows:
            recipes[fallback] = rows
    if active_recipe and fallback:
        for row in result['commitments'].values():
            if row['building_id'] == bid:
                row['recipe_id'] = active_recipe
    return result


def remove_group(part, gid, bid):
    for rid, rows in list(part.get('recipe_assignments', {}).get(bid, {}).items()):
        rows.pop(gid, None)
        if not rows:
            del part['recipe_assignments'][bid][rid]


def adjust(part, registry, bid, rid, delta):
    """Change one future assignment; held workers remain until the old job completes."""
    if type(delta) is not int or delta not in (-1, 1):
        raise ValidationError('每次只能增加或减少一名弟子')
    result = thaw_json(part)
    selected = workers(part, bid, rid) if rid else {
        g: targets.get(bid, 0) - sum(rows.get(g, 0) for rows in part.get('recipe_assignments', {}).get(bid, {}).values())
        for g, targets in part['assignments'].items()}
    if delta == -1:
        gid = next((g for g in sorted(selected) if selected[g] > 0), None)
        if gid is None:
            raise ValidationError('此配方没有可减少的弟子')
        targets = result['assignments'][gid]
        targets[bid] -= 1
        if not targets[bid]:del targets[bid]
        if not targets:del result['assignments'][gid]
        if rid:
            rows = result['recipe_assignments'][bid][rid]
            rows[gid] -= 1
            if not rows[gid]:del rows[gid]
            if not rows:del result['recipe_assignments'][bid][rid]
    else:
        # Existing unspecified people at this building can be assigned a recipe first.
        unbound = {g: targets.get(bid, 0) - sum(rows.get(g, 0) for rows in part.get('recipe_assignments', {}).get(bid, {}).values()) - sum(c['workers'].get(g,0) for c in part['commitments'].values() if c['building_id']==bid and not c.get('recipe_id'))
                   for g, targets in part['assignments'].items()}
        gid = next((g for g in sorted(unbound) if rid and unbound[g] > 0), None)
        if gid is None:
            gid = next((g for g, row in sorted(part['groups'].items())
                        if row['count'] > sum(claims(part, g).values())), None)
            if gid is None:
                raise ValidationError('未分配弟子不足，正在工作的弟子需本轮完成后释放')
            targets = result['assignments'].setdefault(gid, {})
            targets[bid] = targets.get(bid, 0) + 1
        if rid:
            rows = result.setdefault('recipe_assignments', {}).setdefault(bid, {}).setdefault(rid, {})
            rows[gid] = rows.get(gid, 0) + 1
    validate(result, registry)
    return freeze_json(result)

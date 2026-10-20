"""Recipe workforce commands/read models and scheduling within the existing batch slot."""
from dataclasses import replace
from src.core.state.envelope import thaw_json
from src.core.validation import ValidationError, ConflictError
from src.core.time.world import paused
from src.data.economy.sect_rules import settings
from src.systems.disciples import work, recipe_allocations as plans
from src.systems.economy import policy
from src.systems.resources import jobs
from src.systems.sect import buildings, rules

COMMAND = 'work_recipe_adjust'
SPECIAL = {'garden': '灵田照料', 'pasture': '灵兽照料', 'spring': '灵池照料',
           'trading': '商店经营与补货', 'builders': '营造施工'}


def open_recipes(state, registry, bid):
    b = buildings.get_building(state.domains['sect'], registry, bid)
    if b['definition_id'] in SPECIAL:
        return []
    cfg = settings(registry) or {}
    rank = rules.development(state.domains['sect'], registry, state.domains.get('dungeon', {}).get('cleared_floor', 0))['level']
    result = []
    for rid in cfg.get('production_whitelist', ()):
        d = jobs.definition(registry, rid)
        gate = cfg.get('recipe_unlock_overrides', {}).get(rid, {'floor': d.unlock_floor, 'realm': d.unlock_realm})
        if (d.building_kind == b['definition_id'] and not d.facility_output_id
                and b['level'] >= d.min_level and not gate['floor'] and not gate['realm']
                and rank >= cfg.get('recipe_sect_minimum', {}).get(rid, 1)):
            result.append(d)
    return result


def fallback(state, bid, recipes):
    job = state.domains['production']['jobs'].get(bid)
    active = job['recipe_id'] if job and job['status'] == 'WORKING' else None
    old = state.domains['automation']['production'].get(bid)
    candidate = active or (old['recipe_id'] if old and old['enabled'] else None)
    return candidate if candidate in {d.machine_id for d in recipes} else None, active


def part_for_view(state, bid, recipes):
    default, active = fallback(state, bid, recipes)
    return plans.materialize(state.domains['disciples'], bid, default, active)


def transition(state, registry, payload):
    if set(payload) != {'building_id', 'recipe_id', 'delta'} or type(payload['building_id']) is not str:
        raise ValidationError('请选择建筑、配方以及加减人数')
    if type(payload['delta']) is not int or payload['delta'] not in (-1, 1):
        raise ValidationError('每次只能增加或减少一名弟子')
    if state.time['pending'] or paused(state.time):
        raise ValidationError('请先恢复世界运行并完成进度续算')
    bid, rid = payload['building_id'], payload['recipe_id']
    b = buildings.get_building(state.domains['sect'], registry, bid)
    recipes = open_recipes(state, registry, bid)
    if rid is not None and (type(rid) is not str or rid not in {d.machine_id for d in recipes}):
        raise ValidationError('此配方尚未开放或不属于当前建筑')
    if rid is None and payload['delta'] == 1 and not recipes and b['definition_id'] not in SPECIAL:
        raise ValidationError('此建筑尚无已开放的生产配方或经营岗位')
    if buildings.work_slots(state.domains['sect'], registry, bid) < 1:
        raise ValidationError('此建筑没有可用工作岗位')
    part = state.domains['disciples']
    automation = state.domains['automation']
    if rid is not None:
        part = part_for_view(state, bid, recipes)
        automation = policy.recipe_queue(automation, bid, rid)
    candidate = plans.adjust(part, registry, bid, rid, payload['delta'])
    work.validate(candidate, registry)
    occupied = sum(work.allocations(candidate, g).get(bid, 0) for g in candidate['groups'])
    if occupied > buildings.work_slots(state.domains['sect'], registry, bid):
        raise ValidationError('建筑岗位已满，待本轮弟子释放或扩建后再安排')
    policy.validate(automation, registry)
    result = replace(state, domains={**state.domains, 'disciples': candidate, 'automation': automation})
    return result, {'operation': COMMAND, **payload}


def queue_rows(state, bid):
    queue = state.domains['automation'].get('recipe_production', {}).get(bid)
    if queue is None:
        return []
    identities = sorted(queue['recipes'])
    last = queue['last_recipe_id']
    if last is not None:
        identities = [rid for rid in identities if rid > last] + [rid for rid in identities if rid <= last]
    return [queue['recipes'][rid] for rid in identities]


def check_policy(state, registry, bid, row):
    rid = row['recipe_id']
    count = work.capability(state.domains['disciples'], registry, bid, rid)['workers']
    if not count:
        raise ValidationError('此配方未安排弟子')
    amounts = {key: n * count for key, n in jobs.definition(registry, rid).inputs}
    if row['max_consumption'] and sum(amounts.values()) > row['max_consumption']:
        raise ValidationError('超过本配方每批材料消耗限制')
    stock = state.domains['inventory']['holdings']
    if any(stock.get(k, 0) - row['reserves'].get(k, 0) < n for k, n in amounts.items()):
        raise ValidationError('材料不足或触及本配方保留量')


def dispatch(app, state):
    for bid in sorted(state.domains['automation'].get('recipe_production', {})):
        current = state.domains['production']['jobs'].get(bid)
        if current and current['status'] != 'COMPLETE':
            continue
        for row in queue_rows(state, bid):
            if not row['enabled']:
                continue
            d = jobs.definition(app.registry, row['recipe_id'])
            if app.output_stock(state, d) >= row['target']:
                continue
            try:
                check_policy(state, app.registry, bid, row)
                candidate = app.start_candidate(state, bid, d.machine_id, policy_row=row)
            except (ValidationError, ConflictError):
                continue
            auto = thaw_json(candidate.domains['automation'])
            auto['recipe_production'][bid]['last_recipe_id'] = d.machine_id
            state = replace(candidate, domains={**candidate.domains, 'automation': auto})
            break
    return state


def view(app, state):
    registry = app.registry
    result = []
    globally_idle = sum(row['count'] - sum(work.allocations(state.domains['disciples'], gid).values())
                        for gid, row in state.domains['disciples']['groups'].items())
    locked = paused(state.time) or bool(state.time['pending'])
    for bid, b in state.domains['sect']['buildings'].items():
        capacity = buildings.work_slots(state.domains['sect'], registry, bid)
        if capacity < 1:
            continue
        recipes = open_recipes(state, registry, bid)
        part = part_for_view(state, bid, recipes) if recipes else state.domains['disciples']
        assigned = sum(targets.get(bid, 0) for targets in part['assignments'].values())
        occupied = sum(work.allocations(part, g).get(bid, 0) for g in part['groups'])
        if not recipes and b['definition_id'] not in SPECIAL and not occupied:
            continue
        job = state.domains['production']['jobs'].get(bid)
        active = job if job and job['status'] == 'WORKING' else None
        held = next((c for c in part['commitments'].values() if c['building_id'] == bid), None)
        rows = []
        for d in recipes:
            count = sum(plans.workers(part, bid, d.machine_id).values())
            pending = sum(max(0, n - plans.workers(part, bid, d.machine_id).get(g, 0))
                          for g, n in (held['workers'] if held and held.get('recipe_id') == d.machine_id else {}).items())
            unbound = sum(max(0,targets.get(bid,0)-sum(rows.get(g,0) for rows in part.get('recipe_assignments',{}).get(bid,{}).values())-sum(c['workers'].get(g,0) for c in part['commitments'].values() if c['building_id']==bid and not c.get('recipe_id'))) for g,targets in part['assignments'].items())
            reason = None
            if not count:reason = '未安排'
            elif active and active['recipe_id'] == d.machine_id:reason = '本轮生产中'
            elif active:reason = '等待当前批次结束后轮到此配方'
            else:
                q = next((r for r in queue_rows(state, bid) if r['recipe_id'] == d.machine_id), None)
                old = state.domains['automation']['production'].get(bid)
                q = q or (old if old and old['recipe_id'] == d.machine_id else None)
                if q and not q['enabled']:reason = '自动生产已关闭，可手动开工'
                elif q and app.output_stock(state, d) >= q['target']:reason = '目标库存已达到'
                else:
                    try:
                        if q and plans.planned(state.domains['disciples'], bid):check_policy(state, registry, bid, q)
                        app.start_candidate(state, bid, d.machine_id, policy_row=q)
                        reason = '等待开工'
                    except (ValidationError, ConflictError) as exc:reason = str(exc) if any('\u4e00' <= c <= '\u9fff' for c in str(exc)) else '等待材料、仓容或生产条件'
            rows.append({'recipe_id': d.machine_id, 'name': d.display_name, 'count': count,
                'working': active['workers'] if active and active['recipe_id'] == d.machine_id else 0,
                'pending_release': pending, 'status': reason,
                'can_add': not locked and (unbound > 0 or (globally_idle > 0 and occupied < capacity)),
                'can_remove': not locked and count > 0})
        unbound = assigned - sum(sum(group.values()) for group in part.get('recipe_assignments', {}).get(bid, {}).values())
        if not recipes or unbound:
            rows.append({'recipe_id': None, 'name': SPECIAL.get(b['definition_id'], '未指定配方岗位'),
                'count': unbound, 'working': active['workers'] if active and not recipes else 0,
                'pending_release': max(0, occupied-assigned) if not recipes else 0,
                'status': '按现有岗位与照料规则执行' if b['definition_id'] in SPECIAL else '可在配方行安排这些弟子' if recipes else '历史岗位可减员，新派工请选择已开放建筑',
                'can_add': not locked and globally_idle > 0 and occupied < capacity and (bool(recipes) or b['definition_id'] in SPECIAL),
                'can_remove': not locked and unbound > 0})
        result.append({'building_id': bid, 'name': buildings.definition(registry,b['definition_id']).display_name,
            'capacity': capacity, 'assigned': assigned, 'occupied': occupied,
            'pending_release': max(0, occupied-assigned), 'rows': rows,
            'recipe_mode': bool(recipes)})
    return {'buildings': result, 'idle': globally_idle, 'blocked': locked}

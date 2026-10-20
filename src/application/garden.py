"""Plot commands and read model over Ecology/Inventory/Work's existing owners."""
from dataclasses import replace
from src.core.state.envelope import thaw_json
from src.core.validation import ValidationError, integer
from src.core.time.world import paused
from src.data.registry import DefinitionKey
from src.data.economy.ecology import settings
from src.data.economy.sect_rules import settings as sect_settings
from src.systems.sect import ecology, garden, nutrition, buildings
from src.systems.sect.rules import development
from src.systems.disciples import work
from src.systems.resources import jobs
from src.systems.inventory import holdings, operations


def validate_state(state, registry):
    seen = set(state.domains['sect']['buildings']) | set(state.domains['disciples']['groups'])
    seen.update(j['job_id'] for j in state.domains['production']['jobs'].values())
    seen.update(state.domains.get('equipment', {}).get('instances', {}))
    seen.update(state.domains['ecology']['batches'])
    battle = state.domains.get('combat', {}).get('battle')
    if battle: seen.add(battle['battle_id'])
    for bid, policies in state.domains['ecology'].get('garden_repeat', {}).items():
        if bid not in state.domains['ecology'].get('garden', {}) or not set(policies) <= set(state.domains['ecology']['garden'][bid]):
            raise ValidationError('repeat policy requires cultivated plots')
    for bid, field in state.domains['ecology'].get('garden', {}).items():
        b = buildings.get_building(state.domains['sect'], registry, bid)
        if b['definition_id'] != 'garden' or b['level'] < 1:
            raise ValidationError('garden building required')
        capacity = ecology.capacity(state, registry, bid)
        for key, row in field.items():
            if int(key) >= capacity:
                raise ValidationError('plot exceeds garden capacity')
            if row is None:
                continue
            pieces = row['plant_id'].split(':')
            if len(pieces) != 4 or pieces[0] != state.save_id or pieces[2] != 'i':
                raise ValidationError('invalid plant namespace')
            for key, maximum in ((1, state.generation), (3, state.identity['instance_counter'])):
                if not pieces[key].isascii() or not pieces[key].isdecimal() or not 1 <= int(pieces[key]) <= maximum or str(int(pieces[key])) != pieces[key]:
                    raise ValidationError('unallocated plant identity')
            if row['plant_id'] in seen or row['planted_ms'] > state.time['sim_time_ms']:
                raise ValidationError('invalid plant identity/time')
            seen.add(row['plant_id'])


def legacy_job(state, bid):
    job = state.domains['production']['jobs'].get(bid)
    return job if job and job['status'] != 'COMPLETE' else None


def reasons(state, registry, bid, recipe_id, *, automatic=False):
    d = jobs.definition(registry, recipe_id)
    b = buildings.get_building(state.domains['sect'], registry, bid)
    cfg = sect_settings(registry)
    unlock = cfg['recipe_unlock_overrides'].get(recipe_id, {'floor': d.unlock_floor, 'realm': d.unlock_realm})
    rows = []
    if b['level'] < d.min_level or unlock['floor'] or unlock['realm']:
        rows.append(f'需要灵植园 {d.min_level} 级及配方解锁条件')
    minimum = cfg.get('recipe_sect_minimum', {}).get(recipe_id, 1)
    rank = development(state.domains['sect'], registry, state.domains.get('dungeon', {}).get('cleared_floor', 0))['level']
    if rank < minimum:
        rows.append(f'需要宗门 {minimum} 级')
    cap = work.capability(state.domains['disciples'], registry, bid)
    growing = sum(bool(row) and not garden.ready(row, registry) for row in garden.plots(state.domains['ecology'], bid).values())
    if growing >= cap['workers']:
        rows.append('请先安排空闲农务弟子，每人照料一块田')
    if legacy_job(state, bid):
        rows.append('原有批次或设施营造尚未完成')
    auto = state.domains['automation']['production'].get(bid, {})
    if auto.get('enabled'):
        rows.append('请先关闭原有整批自动生产，再逐格种植')
    if any(state.domains['inventory']['holdings'].get(rid, 0) < n for rid, n in d.inputs):
        rows.append('种植材料不足')
    if paused(state.time):
        rows.append('世界暂停')
    if state.time['pending'] and not automatic:
        rows.append('宗门进度续算中')
    return rows


def transition(app, state, name, payload, *, automatic=False):
    expected = {'building_id', 'plot_index'} | ({'recipe_id'} if name == 'garden_plant' else set())
    if name == 'garden_repeat': expected = {'building_id', 'plot_index', 'enabled'}
    if name == 'garden_plant' and 'repeat' in payload:
        expected.add('repeat')
        if type(payload['repeat']) is not bool: raise ValidationError('请选择是否重复种植')
    if set(payload) != expected:
        raise ValidationError('请选择田块和种植配方')
    bid, index = payload['building_id'], payload['plot_index']
    integer(index, 'plot index')
    b = buildings.get_building(state.domains['sect'], app.registry, bid)
    if b['definition_id'] != 'garden' or b['level'] < 1 or index >= ecology.capacity(state, app.registry, bid):
        raise ValidationError('该田块尚未解锁，请升级灵植园')
    part = thaw_json(state.domains['ecology'])
    field = part.setdefault('garden', {}).setdefault(bid, {})
    key = str(index)
    if name == 'garden_repeat':
        if type(payload['enabled']) is not bool or key not in field:
            raise ValidationError('请选择已开垦田块和重复种植开关')
        policy = part.setdefault('garden_repeat', {}).setdefault(bid, {})
        recipe = field[key]['recipe_id'] if field[key] else policy.get(key, {}).get('recipe_id')
        if not recipe: raise ValidationError('请先选择种植灵植')
        policy[key] = {'recipe_id': recipe, 'enabled': payload['enabled']}
        return replace(state, domains={**state.domains, 'ecology': part}), {'operation': name, **payload}
    if name == 'garden_reclaim':
        field.setdefault(key, None)
        return replace(state, domains={**state.domains, 'ecology': part}), {'operation': name, **payload}
    if key not in field:
        raise ValidationError('请先开垦此田块')
    if field[key] is not None:
        raise ValidationError('此田块已有灵植')
    recipe_id = payload['recipe_id']
    if recipe_id not in garden.crops(app.registry):
        raise ValidationError('请选择已开放的灵植')
    blocked = reasons(state, app.registry, bid, recipe_id, automatic=automatic)
    if blocked:
        raise ValidationError('；'.join(blocked))
    d = jobs.definition(app.registry, recipe_id)
    stock, _ = operations.consume(state.domains['inventory'], app.registry, dict(d.inputs))
    effect = nutrition.effects(state, app.registry, bid)
    counter = state.identity['instance_counter'] + 1
    part.setdefault('garden_repeat', {}).setdefault(bid, {})[key] = {'recipe_id': recipe_id, 'enabled': payload.get('repeat', True)}
    field[key] = {'plant_id': f'{state.save_id}:{state.generation}:i:{counter}', 'recipe_id': recipe_id,
                  'planted_ms': state.time['sim_time_ms'], 'progress_milli': 0, 'rate_milli': 0,
                  'base_rate_milli': effect['rate_milli'], 'yield_milli': jobs.yield_for_level(1000, b['level']),
                  'extra_bps': effect['extra_bps']}
    return replace(state, identity={**state.identity, 'instance_counter': counter},
                   domains={**state.domains, 'inventory': stock, 'ecology': part}), {'operation': name, **payload, 'cost': dict(d.inputs)}


def schedule(state, registry, part, deadlines):
    now = state.time['sim_time_ms']
    for bid, field in part.get('garden', {}).items():
        available = work.capability(state.domains['disciples'], registry, bid)['workers']
        if legacy_job(state, bid):
            available = 0
        for _, row in sorted(field.items(), key=lambda item: int(item[0])):
            if row is None:
                continue
            row['rate_milli'] = 0
            if garden.ready(row, registry):
                continue
            if available:
                available -= 1
                row['rate_milli'] = row['base_rate_milli']
                total = jobs.definition(registry, row['recipe_id']).duration_ms * 1000
                deadlines.append(now + (total - row['progress_milli'] + row['rate_milli'] - 1) // row['rate_milli'])


def deliver(app, state):
    from src.application import offline_reports
    part = thaw_json(state.domains['ecology'])
    stock = state.domains['inventory']
    capacity = app._capacity(state)
    for bid, field in part.get('garden', {}).items():
        for index, row in field.items():
            if row is None or not garden.ready(row, app.registry):
                continue
            amounts = jobs.outputs(row, app.registry)
            if app.roll(state, row['plant_id'], 'extra', row['extra_bps']):
                for rid, n in jobs.definition(app.registry, row['recipe_id']).outputs:
                    amounts[rid] = amounts.get(rid, 0) + n
            needed = sum(n for rid, n in amounts.items() if holdings.definition(app.registry, rid).warehouse_counted)
            if holdings.stock_size(stock, app.registry) + needed > capacity:
                continue
            stock, result = operations.grant(stock, app.registry, amounts, capacity=capacity)
            if any(result['discarded'].values()):
                raise ValidationError('灵植产物必须完整入库')
            state = offline_reports.observe_production(state, row, amounts, 0)
            part.setdefault('garden_repeat', {}).setdefault(bid, {}).setdefault(index, {'recipe_id': row['recipe_id'], 'enabled': True})
            field[index] = None
    return replace(state, domains={**state.domains, 'ecology': part, 'inventory': stock})


def view(state, registry, bid):
    part = state.domains['ecology']
    field = garden.plots(part, bid)
    capacity = ecology.capacity(state, registry, bid)
    choices = []
    resource_name = lambda rid: registry.lookup(DefinitionKey('resources', rid)).display_name
    for recipe_id in garden.crops(registry):
        d = jobs.definition(registry, recipe_id)
        blocked = reasons(state, registry, bid, recipe_id)
        quantities = jobs.outputs({'recipe_id': recipe_id, 'yield_milli': jobs.yield_for_level(1000, state.domains['sect']['buildings'][bid]['level'])}, registry)
        choices.append({'recipe_id': recipe_id, 'name': d.display_name, 'resource_id': d.outputs[0][0],
                        'duration_seconds': d.duration_ms / 1000,
                        'inputs': [{'resource_id': rid, 'name': resource_name(rid), 'quantity': n, 'current': state.domains['inventory']['holdings'].get(rid, 0)} for rid, n in d.inputs],
                        'outputs': [{'resource_id': rid, 'name': resource_name(rid), 'quantity': n} for rid, n in quantities.items()],
                        'can_plant': not blocked, 'blocking_reasons': blocked})
    plants = []
    for index in range(capacity):
        row = field.get(str(index))
        item = {'index': index, 'state': 'UNCULTIVATED' if str(index) not in field else 'EMPTY'}
        if row:
            d = jobs.definition(registry, row['recipe_id'])
            total = d.duration_ms * 1000
            item.update(state='READY' if garden.ready(row, registry) else 'GROWING' if row['rate_milli'] else 'WAITING',
                        recipe_id=row['recipe_id'], resource_id=d.outputs[0][0], name=d.display_name,
                        progress_percent=row['progress_milli'] * 100 // total,
                        remaining_seconds=(total-row['progress_milli']+max(1,row['rate_milli'])-1)//max(1,row['rate_milli'])//1000 if row['rate_milli'] else None)
        policy = part.get('garden_repeat', {}).get(bid, {}).get(str(index))
        item['repeat'] = policy['enabled'] if policy else bool(row)
        if policy and policy['enabled'] and row is None:
            crop = next(r for r in choices if r['recipe_id'] == policy['recipe_id'])
            item.update(state='REPLANT_WAIT', recipe_id=crop['recipe_id'], resource_id=crop['resource_id'], name=crop['name'], waiting_reason='；'.join(crop['blocking_reasons']))
        plants.append(item)
    building = state.domains['sect']['buildings'][bid]
    installed = part['facilities'].get(bid, {})
    expandable = building['level'] < buildings.definition(registry, 'garden').max_level or any(
        row['building_kind'] == 'garden' and installed.get(row['id'], 0) < (building['level'] if row['per_level'] else 1)
        for row in settings(registry)['facilities'])
    return {'expandable': expandable, 'building_id': bid, 'capacity': capacity, 'reclaimed': len(field), 'plots': plants, 'choices': choices,
            'legacy_job': thaw_json(legacy_job(state, bid)) if legacy_job(state, bid) else None,
            'auto_enabled': bool(state.domains['automation']['production'].get(bid, {}).get('enabled')),
            'available': not paused(state.time) and not state.time['pending']}


def replant(app, state):
    if paused(state.time): return state
    for bid, policies in state.domains['ecology'].get('garden_repeat', {}).items():
        for index, policy in sorted(policies.items(), key=lambda item:int(item[0])):
            if not policy['enabled'] or garden.plots(state.domains['ecology'], bid).get(index) is not None: continue
            try:
                state, _ = transition(app, state, 'garden_plant', {'building_id':bid, 'plot_index':int(index), 'recipe_id':policy['recipe_id'], 'repeat':True}, automatic=True)
            except ValidationError:
                continue
    return state

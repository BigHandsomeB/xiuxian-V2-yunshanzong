"""Grid admission and repeated husbandry reuse ecology buy/collect transactions."""
from dataclasses import replace
from src.core.state.envelope import thaw_json
from src.core.validation import ValidationError, integer
from src.core.time.world import paused
from src.data.economy.ecology import settings, lookup
from src.systems.sect import ecology, habitats, buildings
from src.systems.disciples import work


def used_workers(state, bid):
    return sum(row['count'] for row in state.domains['ecology']['batches'].values() if row['building_id'] == bid)


def transition(app, state, name, payload):
    if name == 'habitat_repeat':
        if set(payload) != {'batch_id', 'enabled'} or type(payload['enabled']) is not bool:
            raise ValidationError('请选择存栏和自动续养开关')
        part = thaw_json(state.domains['ecology']); row = part['batches'].get(payload['batch_id'])
        if row is None: raise ValidationError('该存栏已更新，请重新选择')
        row['repeat'] = payload['enabled']
        return replace(state, domains={**state.domains, 'ecology':part}), {'operation':name, **payload}
    if set(payload) != {'building_id', 'slot_index', 'species_id'}:
        raise ValidationError('请选择兽栏或灵池及品种')
    bid, index = payload['building_id'], payload['slot_index']; integer(index, 'habitat index')
    species = lookup(app.registry, 'species', payload['species_id'])
    building = buildings.get_building(state.domains['sect'], app.registry, bid)
    if building['definition_id'] != species['building_kind'] or building['level'] < 1:
        raise ValidationError('请选择已建设的对应设施')
    capacity = ecology.capacity(state, app.registry, bid)
    cells = habitats.layout(state.domains['ecology'], app.registry, bid, capacity)
    if index + species['slots'] > capacity or any(cells[index:index+species['slots']]):
        raise ValidationError(f'此品种需要连续 {species["slots"]} 格空栏或空池')
    if used_workers(state, bid) >= work.capability(state.domains['disciples'], app.registry, bid)['workers']:
        raise ValidationError('请先安排空闲照料弟子，每名弟子负责一只灵兽或水产')
    candidate, details = app.transition(state, 'ecology_buy', {'building_id':bid, 'species_id':species['id'], 'count':1})
    part = thaw_json(candidate.domains['ecology']); part['batches'][details['batch_id']].update(slot_index=index, repeat=True)
    return replace(candidate, domains={**candidate.domains,'ecology':part}), {**details,'operation':name,'slot_index':index}


def collect(app, state):
    if paused(state.time): return state
    for batch_id in list(state.domains['ecology']['batches']):
        row = state.domains['ecology']['batches'].get(batch_id)
        if row is None or not row.get('repeat') or row['stage'] == 'JUVENILE': continue
        species = lookup(app.registry, 'species', row['species_id'])
        periodic = bool(species['periodic_outputs'])
        if periodic and row['stage'] != 'READY': continue
        if row['last_collection_ms'] == state.time['sim_time_ms']: continue
        try:
            candidate, _ = app.transition(state, 'ecology_collect', {'batch_id':batch_id, 'mode':'periodic' if periodic else 'harvest', 'count':row['count']})
            if not periodic:
                candidate, detail = app.transition(candidate, 'ecology_buy', {'building_id':row['building_id'], 'species_id':row['species_id'], 'count':row['count']})
                part = thaw_json(candidate.domains['ecology']); renewed = part['batches'][detail['batch_id']]
                renewed['repeat'] = True
                if 'slot_index' in row: renewed['slot_index'] = row['slot_index']
                candidate = replace(candidate, domains={**candidate.domains, 'ecology':part})
            state = candidate
        except ValidationError as error:
            part = thaw_json(state.domains['ecology'])
            part['batches'][batch_id]['reason'] = '自动续养等待：'+str(error)
            state = replace(state, domains={**state.domains, 'ecology':part})
    return state


def view(state, registry, bid):
    building = state.domains['sect']['buildings'][bid]; capacity = ecology.capacity(state,registry,bid)
    part = state.domains['ecology']; cells = habitats.layout(part,registry,bid,capacity)
    installed = part['facilities'].get(bid,{})
    expandable = building['level'] < buildings.definition(registry,building['definition_id']).max_level or any(
        f['building_kind']==building['definition_id'] and installed.get(f['id'],0)<(building['level'] if f['per_level'] else 1) for f in settings(registry)['facilities'])
    return {'building_id':bid, 'kind':building['definition_id'], 'capacity':capacity, 'expandable':expandable,
            'free_workers':max(0,work.capability(state.domains['disciples'],registry,bid)['workers']-used_workers(state,bid)),
            'cells':[{'index':index, **(cell or {})} for index,cell in enumerate(cells)]}

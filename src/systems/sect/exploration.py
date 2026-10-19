"""One saved journey and bounded choices on shared simulation time; no clock/SQL."""
from collections.abc import Mapping
from src.core.state.envelope import thaw_json
from src.core.time.world import paused
from src.core.validation import ValidationError, integer
from src.data.exploration.definitions import settings, region
from src.data.registry import DefinitionKey
from src.systems.dungeons import progress
from src.systems.inventory import holdings
from .market import draw

COMMANDS = ('exploration_start', 'exploration_choose')


def initial():
    return {'sequence': 0, 'visits': {}, 'active': None, 'history': []}


def ledger(state):
    return thaw_json(state.domains['sect_management'].get('exploration', initial()))


def event_for(registry, row):
    return next(e for e in region(registry, row['region_id'])['events'] if e['id'] == row['event_id'])


def scheduled_event(registry, save_id, region_id, visit):
    events = sorted(region(registry, region_id)['events'],
                    key=lambda e: (draw(save_id, 0, 'exploration:'+e['id']), e['id']))
    return events[(visit-1) % len(events)]['id']


def validate(part, registry):
    cfg = settings(registry)
    if not isinstance(part, Mapping) or set(part) != {'sequence','visits','active','history'}:
        raise ValidationError('invalid exploration ledger')
    integer(part['sequence'], 'exploration sequence')
    if not isinstance(part['visits'], Mapping):
        raise ValidationError('invalid exploration visits')
    for rid, count in part['visits'].items():
        region(registry, rid); integer(count, 'exploration visits', 1)
    if sum(part['visits'].values()) != part['sequence']:
        raise ValidationError('exploration visit counter mismatch')
    active = part['active']
    if active is not None:
        if not isinstance(active, Mapping) or set(active) != {'id','sequence','region_id','event_id','started_ms','due_ms','roll'}:
            raise ValidationError('invalid exploration journey')
        if any(type(active[k]) is not str for k in ('id','region_id','event_id')):
            raise ValidationError('invalid exploration identity type')
        integer(active['sequence'], 'journey sequence', 1)
        if active['sequence'] != part['sequence'] or active['id'] != f"explore:{active['sequence']}":
            raise ValidationError('invalid exploration identity')
        if active['region_id'] not in part['visits']:
            raise ValidationError('exploration visit missing')
        if active['event_id'] not in {e['id'] for e in region(registry,active['region_id'])['events']}:
            raise ValidationError('invalid exploration event')
        for key in ('started_ms','due_ms','roll'):
            integer(active[key], key)
        if active['due_ms'] <= active['started_ms'] or active['roll'] >= 10000:
            raise ValidationError('invalid exploration deadline/roll')
    rows = part['history']
    if not isinstance(rows, (list,tuple)) or len(rows) > cfg['history_limit']:
        raise ValidationError('invalid exploration history')
    previous = 0
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != {'sequence','region_id','event_id','choice_id','success','sim_ms','rewards','cost'}:
            raise ValidationError('invalid exploration record')
        if any(type(row[k]) is not str for k in ('region_id','event_id','choice_id')):
            raise ValidationError('invalid exploration record identity')
        integer(row['sequence'], 'history sequence', 1); integer(row['sim_ms'], 'history time')
        if not previous < row['sequence'] <= part['sequence'] or (active and row['sequence'] >= active['sequence']):
            raise ValidationError('exploration history order invalid')
        previous = row['sequence']
        if row['event_id'] not in {e['id'] for e in region(registry,row['region_id'])['events']}:
            raise ValidationError('unknown exploration history event')
        event = event_for(registry,row)
        choice = next((c for c in event['choices'] if c['id']==row['choice_id']), None)
        if choice is None or type(row['success']) is not bool or row['cost'] != choice['cost']:
            raise ValidationError('invalid exploration history choice')
        if choice['success_bps'] == 10000 and not row['success']:
            raise ValidationError('guaranteed exploration choice cannot fail')
        if row['rewards'] != rewards(registry,row['region_id'],choice,row['success']):
            raise ValidationError('invalid exploration history reward')
    return part


def validate_state(state, registry):
    part = ledger(state); validate(part,registry)
    active = part['active']
    if active:
        r = region(registry,active['region_id'])
        if active['started_ms'] > state.time['sim_time_ms'] or active['due_ms'] != active['started_ms'] + r['duration_days']*state.time['day_length_ms']:
            raise ValidationError('exploration time mismatch')
        if active['event_id'] != scheduled_event(registry,state.save_id,r['id'],part['visits'][r['id']]) or active['roll'] != draw(state.save_id,part['sequence'],'exploration:result') % 10000:
            raise ValidationError('exploration frozen result mismatch')
        progress.require_dungeon(state.domains['dungeon'],registry,r['dungeon_id'])
    if any(row['sim_ms'] > state.time['sim_time_ms'] for row in part['history']):
        raise ValidationError('exploration history in future')


def rewards(registry, region_id, choice, success):
    amounts = dict(region(registry,region_id)['rewards'])
    if success:
        for rid, n in choice['rewards'].items():
            amounts[rid] = amounts.get(rid,0)+n
    return amounts


def fits(stock, registry, capacity, cost, amounts):
    needed = sum(n for rid,n in amounts.items() if holdings.definition(registry,rid).warehouse_counted)
    freed = sum(n for rid,n in cost.items() if holdings.definition(registry,rid).warehouse_counted)
    return holdings.stock_size(stock,registry)-freed+needed <= max(0,capacity)


def view(state, registry, capacity):
    cfg = settings(registry); part = ledger(state); now = state.time['sim_time_ms']
    blocked = paused(state.time) or bool(state.time['pending'])
    stock = state.domains['inventory']; reserves = state.domains['sect_management']['material_reserves']
    def amounts(rows):
        return [dict(resource_id=rid,name=registry.lookup(DefinitionKey('resources',rid)).display_name,quantity=n) for rid,n in rows.items()]
    regions = []
    for r in cfg['regions']:
        unlocked = progress.unlocked(state.domains['dungeon'],registry,r['dungeon_id'])
        requirement = progress.view(state.domains['dungeon'],registry,dungeon_id=r['dungeon_id'])['unlock_condition']
        lock = ''
        if not unlocked and requirement:
            lock = f"需通关{progress.definition(registry,requirement['dungeon_id']).display_name}{requirement['cleared_floor']}层"
        regions.append(dict(id=r['id'],name=r['name'],description=r['description'],duration_days=r['duration_days'],
                            dungeon_id=r['dungeon_id'],unlocked=unlocked,lock_reason=lock,
                            can_start=unlocked and not blocked and part['active'] is None,rewards=amounts(r['rewards']),
                            visits=part['visits'].get(r['id'],0)))
    current = None
    if part['active']:
        a = part['active']; r = region(registry,a['region_id']); ready = now >= a['due_ms']
        current = dict(id=a['id'],region_id=r['id'],name=r['name'],started_ms=a['started_ms'],due_ms=a['due_ms'],
                       remaining_ms=max(0,a['due_ms']-now),ready=ready,rewards=amounts(r['rewards']))
        if ready:
            e = event_for(registry,a); choices=[]
            for c in e['choices']:
                affordable = all(stock['holdings'].get(rid,0)-n >= reserves.get(rid,0) for rid,n in c['cost'].items())
                # Require room for the best possible outcome; no UI leak of the saved roll.
                space = fits(stock,registry,capacity,c['cost'],rewards(registry,r['id'],c,True))
                reason = '世界暂停或正在续算' if blocked else '材料不足或触及保留量' if not affordable else '仓库空间不足，探索与事件继续保留' if not space else ''
                choices.append(dict(id=c['id'],name=c['name'],cost=amounts(c['cost']),rewards=amounts(c['rewards']),
                                    success_bps=c['success_bps'],can_choose=not reason,blocking_reason=reason))
            current['event']=dict(id=e['id'],name=e['name'],description=e['description'],choices=choices)
    history=[]
    for h in reversed(part['history']):
        e = event_for(registry,h); c = next(c for c in e['choices'] if c['id']==h['choice_id'])
        history.append(dict(sequence=h['sequence'],region_name=region(registry,h['region_id'])['name'],event_name=e['name'],
                            choice_name=c['name'],success=h['success'],sim_ms=h['sim_ms'],
                            text=c['success_text'] if h['success'] else c['failure_text'],rewards=amounts(h['rewards']),cost=amounts(h['cost'])))
    return dict(regions=regions,active=current,history=history,blocked=blocked,history_limit=cfg['history_limit'])

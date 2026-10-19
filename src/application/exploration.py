"""Atomic exploration candidates through the existing command/receipt transaction."""
from dataclasses import replace
from src.core.state.envelope import thaw_json
from src.core.time.world import require_running
from src.core.validation import ValidationError
from src.data.exploration.definitions import settings, region
from src.systems.sect import exploration
from src.systems.sect.market import draw
from src.systems.dungeons import progress
from src.systems.inventory import operations


def transition(state, registry, name, payload, capacity):
    require_running(state.time)
    p = exploration.ledger(state); now = state.time['sim_time_ms']; stock = state.domains['inventory']
    if name == 'exploration_start':
        if set(payload) != {'region_id'} or type(payload['region_id']) is not str:
            raise ValidationError('请选择有效探索地点')
        r = region(registry,payload['region_id'])
        progress.require_dungeon(state.domains['dungeon'],registry,r['dungeon_id'])
        if p['active'] is not None:
            raise ValidationError('请先处理当前探索事件，再开始下一次探索')
        p['sequence'] += 1; visit = p['visits'].get(r['id'],0)+1; p['visits'][r['id']] = visit
        p['active'] = dict(id=f"explore:{p['sequence']}",sequence=p['sequence'],region_id=r['id'],
                           event_id=exploration.scheduled_event(registry,state.save_id,r['id'],visit),
                           started_ms=now,due_ms=now+r['duration_days']*state.time['day_length_ms'],
                           roll=draw(state.save_id,p['sequence'],'exploration:result') % 10000)
        details = dict(operation=name,journey_id=p['active']['id'],region_id=r['id'],due_ms=p['active']['due_ms'])
    elif name == 'exploration_choose':
        if set(payload) != {'journey_id','choice_id'} or any(type(v) is not str for v in payload.values()):
            raise ValidationError('请选择当前事件的有效选项')
        a = p['active']
        if not a or payload['journey_id'] != a['id']:
            raise ValidationError('探索事件已处理或已更新，请刷新')
        if now < a['due_ms']:
            raise ValidationError('探索尚未完成')
        e = exploration.event_for(registry,a)
        c = next((c for c in e['choices'] if c['id']==payload['choice_id']),None)
        if c is None:
            raise ValidationError('此事件没有该选项')
        reserves = state.domains['sect_management']['material_reserves']
        if any(stock['holdings'].get(rid,0)-n < reserves.get(rid,0) for rid,n in c['cost'].items()):
            raise ValidationError('材料不足或触及库存保留量')
        maximum = exploration.rewards(registry,a['region_id'],c,True)
        if not exploration.fits(stock,registry,capacity,c['cost'],maximum):
            raise ValidationError('仓库空间不足，探索与事件已保留，请腾出空间再处理')
        success = a['roll'] < c['success_bps']
        amounts = exploration.rewards(registry,a['region_id'],c,success)
        if c['cost']:
            stock,_ = operations.consume(stock,registry,c['cost'])
        stock,result = operations.grant(stock,registry,amounts,capacity=max(0,capacity))
        if any(result['discarded'].values()):
            raise ValidationError('探索收益必须完整入库')
        record = dict(sequence=a['sequence'],region_id=a['region_id'],event_id=e['id'],choice_id=c['id'],
                      success=success,sim_ms=now,rewards=amounts,cost=dict(c['cost']))
        p['history'] = (p['history']+[record])[-settings(registry)['history_limit']:]; p['active'] = None
        details = dict(operation=name,journey_id=a['id'],**record,
                       text=c['success_text'] if success else c['failure_text'])
    else:
        raise ValidationError('unknown exploration command')
    exploration.validate(p,registry)
    management = thaw_json(state.domains['sect_management']); management['exploration'] = p
    return replace(state,domains={**state.domains,'sect_management':management,'inventory':stock}),details

"""Atomic candidates only: activity ledger + existing inventory, no independent Store."""
from dataclasses import replace
from src.core.state.envelope import thaw_json
from src.core.validation import ValidationError,integer
from src.data.economy.activities import settings
from src.systems.sect import activities,market
from src.systems.inventory import operations,holdings

def transition(state,registry,name,payload,capacity):
    p=activities.today(state);stock=state.domains['inventory'];details={'operation':name}
    if name=='sect_commission_claim':
        if set(payload)!={'order_id','market_day','quote_id'}:raise ValidationError('请刷新并选择当前委托')
        if type(payload['order_id']) is not str or type(payload['quote_id']) is not str:raise ValidationError('无效委托报价')
        integer(payload['market_day'],'commission day')
        row=next((r for r in activities.orders(state,registry) if r['order_id']==payload['order_id']),None)
        if row is None or row['complete'] or payload['market_day']!=market.day(state) or payload['quote_id']!=row['quote_id']:raise ValidationError('委托已完成、过期或报价改变')
        rid=row['resource_id'];n=row['quantity']
        if stock['holdings'].get(rid,0)-n<state.domains['sect_management']['material_reserves'].get(rid,0):raise ValidationError('材料不足或触及库存保留量')
        stock,_=operations.consume(stock,registry,{rid:n});p['completed'].append(row['order_id']);p['contribution']+=row['contribution'];p['earned']+=row['contribution'];details.update(cost={rid:n},contribution=row['contribution'])
    elif name=='sect_contribution_exchange':
        if set(payload)!={'exchange_id'}:raise ValidationError('请选择贡献兑换项目')
        row=next((r for r in settings(registry)['exchanges'] if r['id']==payload['exchange_id']),None)
        if row is None or p['contribution']<row['cost']:raise ValidationError('贡献不足或兑换不存在')
        amounts=dict(row['rewards']);p['contribution']-=row['cost'];details.update(contribution_spent=row['cost'],rewards=amounts)
    elif name=='boss_chest_open':
        if set(payload)!={'chest_id','choice'}:raise ValidationError('请选择宝箱和奖励方向')
        did=payload['chest_id']
        if type(did) is not str or type(payload['choice']) is not str:raise ValidationError('请选择有效宝箱和奖励方向')
        if did not in p['chests']:raise ValidationError('宝箱不存在或已领取')
        amounts=activities.rewards(registry,did,payload['choice']);del p['chests'][did];details.update(chest_id=did,choice=payload['choice'],rewards=amounts)
    else:raise ValidationError('unknown activity command')
    if name!='sect_commission_claim':
        needed=sum(n for rid,n in amounts.items() if holdings.definition(registry,rid).warehouse_counted)
        if needed and holdings.stock_size(stock,registry)+needed>max(0,capacity):raise ValidationError('仓库空间不足，请腾出空间后领取；宝箱和贡献保留')
        stock,result=operations.grant(stock,registry,amounts,capacity=max(0,capacity))
        if any(result['discarded'].values()):raise ValidationError('奖励必须完整入库')
    activities.validate(p,registry);part=thaw_json(state.domains['sect_management']);part['activities']=p
    return replace(state,domains={**state.domains,'inventory':stock,'sect_management':part}),details

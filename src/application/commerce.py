"""Inventory and escrow candidates for orders, NPC auctions and consignment."""
from dataclasses import replace
from src.core.validation import ValidationError,integer
from src.core.state.envelope import thaw_json
from src.data.economy.market import settings
from src.systems.sect import market,commerce
from src.systems.inventory import operations,holdings

COMMANDS=('market_order','market_bid','market_auction_claim','market_consign','market_consignment_claim')

def transition(state,registry,name,payload,capacity):
    capacity=max(0,capacity);c=commerce.today(state);p=payload;stock=state.domains['inventory'];now=state.time['sim_time_ms'];cfg=settings(registry);details={'operation':name}
    def consume(amounts):
        nonlocal stock
        for rid,n in amounts.items():
            if rid!='coins' and stock['holdings'].get(rid,0)-n<state.domains['sect_management']['material_reserves'].get(rid,0):raise ValidationError('材料不足或触及库存保留量')
        stock,_=operations.consume(stock,registry,amounts)
    def grant(amounts):
        nonlocal stock
        needed=sum(n for rid,n in amounts.items() if holdings.definition(registry,rid).warehouse_counted)
        if needed and holdings.stock_size(stock,registry)+needed>capacity:raise ValidationError('仓库空间不足，可腾出空间后领取；托管物品与押款保留')
        stock,result=operations.grant(stock,registry,amounts,capacity=capacity)
        if any(result['discarded'].values()):raise ValidationError('交易物品必须完整入库')
    if name=='market_order':
        if set(p)!={'order_id','market_day','quote_id'}:raise ValidationError('请使用当前收购订单')
        integer(p['market_day'],'order day')
        order=next((r for r in commerce.orders(state,registry) if r['order_id']==p['order_id']),None)
        if p['market_day']!=market.day(state) or not order or order['complete'] or p['quote_id']!=order['quote_id']:raise ValidationError('订单已完成或过期')
        rid=order['resource_id'];consume({rid:order['quantity']});grant({'coins':order['coins']});c['orders'][order['order_id']]=True;commerce.history(c,state,'ORDER',rid,order['coins']);details.update(coins=order['coins'],resource_id=rid,quantity=order['quantity'])
    elif name=='market_bid':
        if set(p)!={'auction_id','bid'} or type(p['auction_id']) is not str:raise ValidationError('请选择珍品并填写出价')
        integer(p['bid'],'auction bid',1)
        offer=next((r for r in commerce.auction_offers(state,registry) if r['auction_id']==p['auction_id']),None)
        if not offer or now>=offer['end_ms']:raise ValidationError('拍卖已经结束或商品不在本届目录')
        previous=c['bids'].get(p['auction_id']);base=previous['bid'] if previous else offer['start_coins'];minimum=base+max(1,(base+9)//10)
        if p['bid']<minimum:raise ValidationError(f'本次出价至少 {minimum} 灵钱')
        if not previous and len(c['bids'])>=64:raise ValidationError('请先领取已结束拍卖')
        consume({'coins':p['bid']-(previous['bid'] if previous else 0)})
        c['bids'][p['auction_id']]={'resource_id':offer['resource_id'],'cycle':offer['cycle'],'bid':p['bid'],'end_ms':offer['end_ms'],'npc_bid':offer['npc_bid']};details.update(escrow=p['bid'],auction_id=p['auction_id'])
    elif name=='market_auction_claim':
        if set(p)!={'auction_id'} or type(p['auction_id']) is not str:raise ValidationError('请选择待领取拍卖')
        row=c['bids'].get(p['auction_id'])
        if not row or now<row['end_ms']:raise ValidationError('拍卖未结束或已经领取')
        won=row['bid']>row['npc_bid'];grant({row['resource_id']:1} if won else {'coins':row['bid']})
        del c['bids'][p['auction_id']];commerce.history(c,state,'BUY_WIN' if won else 'BUY_LOST',row['resource_id'],row['bid']);details.update(won=won,coins=0 if won else row['bid'],resource_id=row['resource_id'])
    elif name=='market_consign':
        if set(p)!={'resource_id'} or type(p['resource_id']) is not str:raise ValidationError('请选择寄卖珍品')
        if len(c['consignments'])>=cfg['consignment_limit']:raise ValidationError('请先结算已有寄卖，最多同时寄卖三件')
        row=commerce.consignment_quote(state,registry,p['resource_id']);consume({p['resource_id']:1});c['sequence']+=1;aid=f'consign:{c["sequence"]}';c['consignments'][aid]=row;details.update(consignment_id=aid,resource_id=p['resource_id'])
    elif name=='market_consignment_claim':
        if set(p)!={'consignment_id'} or type(p['consignment_id']) is not str:raise ValidationError('请选择寄卖记录')
        row=c['consignments'].get(p['consignment_id'])
        if not row or now<row['end_ms']:raise ValidationError('寄卖尚未结束或已经结算')
        sold=row['npc_bid']>=row['reserve'];coins=row['npc_bid']*(1000-cfg['auction_commission_permille'])//1000 if sold else 0
        grant({'coins':coins} if sold else {row['resource_id']:1});del c['consignments'][p['consignment_id']];commerce.history(c,state,'SELL' if sold else 'UNSOLD',row['resource_id'],coins);details.update(sold=sold,coins=coins,resource_id=row['resource_id'])
    else:raise ValidationError('unknown commerce command')
    part=thaw_json(state.domains['sect_management']);part['commerce']=c;commerce.validate(c,registry)
    return replace(state,domains={**state.domains,'inventory':stock,'sect_management':part}),details

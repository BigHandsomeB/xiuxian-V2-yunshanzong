"""Bounded commerce ledger and deterministic NPC orders/auctions; no clock or I/O."""
from collections.abc import Mapping
from src.core.validation import ValidationError,integer
from src.core.state.envelope import thaw_json
from src.data.economy.market import settings
from . import market

FIELDS={'day','purchases','orders','bids','consignments','sequence','history'}
def initial():return {'day':0,'purchases':{},'orders':{},'bids':{},'consignments':{},'sequence':0,'history':[]}
def ledger(state):return thaw_json(state.domains['sect_management'].get('commerce',initial()))
def today(state):
    c=ledger(state)
    if c['day']!=market.day(state):c.update(day=market.day(state),purchases={},orders={})
    return c

def validate(c,registry):
    cfg=settings(registry)
    if not isinstance(c,Mapping) or set(c)!=FIELDS:raise ValidationError('invalid commerce ledger')
    for k in ('day','sequence'):integer(c[k],k)
    for key in ('purchases','orders','bids','consignments'):
        if not isinstance(c[key],Mapping):raise ValidationError('commerce entries required')
    for rid,n in c['purchases'].items():
        if rid not in cfg['items']:raise ValidationError('unknown purchased material')
        integer(n,'purchased count',1)
        if n>min(cfg['max_purchase_quantity'],cfg['items'][rid]['daily_quantity']):raise ValidationError('invalid daily purchase total')
    for key,done in c['orders'].items():
        if type(key) is not str or done is not True:raise ValidationError('invalid fulfilled order')
        if key not in {f'{c["day"]}:{i}' for i in range(cfg['orders_per_day'])}:raise ValidationError('order outside current day')
    for rows,fields in ((c['bids'],{'resource_id','cycle','bid','end_ms','npc_bid'}),(c['consignments'],{'resource_id','end_ms','reserve','npc_bid'})):
        if len(rows)>64:raise ValidationError('请先领取已结束的拍卖')
        for key,row in rows.items():
            if type(key) is not str or not isinstance(row,Mapping) or set(row)!=fields or row['resource_id'] not in cfg['items']:raise ValidationError('invalid escrow entry')
            for field in fields-{'resource_id'}:integer(row[field],field,1 if field in ('bid','reserve','end_ms') else 0)
    if len(c['consignments'])>cfg['consignment_limit']:raise ValidationError('too many consignments')
    for key,row in c['bids'].items():
        if key!=f'{row["cycle"]}:{row["resource_id"]}':raise ValidationError('auction identity mismatch')
    for key in c['consignments']:
        if not key.startswith('consign:') or not key[8:].isdigit() or not 1<=int(key[8:])<=c['sequence']:raise ValidationError('consignment identity mismatch')
    if not isinstance(c['history'],(list,tuple)) or len(c['history'])>20:raise ValidationError('invalid commerce history')
    for r in c['history']:
        if not isinstance(r,Mapping) or set(r)!={'kind','resource_id','coins','sim_ms'} or r['kind'] not in ('ORDER','BUY_WIN','BUY_LOST','SELL','UNSOLD') or r['resource_id'] not in cfg['items']:raise ValidationError('invalid trade history')
        integer(r['coins'],'history coins');integer(r['sim_ms'],'history time')
    return c

def history(c,state,kind,rid,coins):c['history']=(c['history']+[{'kind':kind,'resource_id':rid,'coins':coins,'sim_ms':state.time['sim_time_ms']}])[-20:]

def orders(state,registry):
    cfg=settings(registry);d=market.day(state);pool=[rid for rid in market.eligible(state,registry) if not cfg['items'][rid]['boss_only'] and cfg['items'][rid]['level']<=3];out=[]
    for index in range(min(cfg['orders_per_day'],len(pool))):
        rid=pool.pop(market.draw(state.save_id,d,f'order:{index}')%len(pool));row=cfg['items'][rid]
        qty=2+market.draw(state.save_id,d,'order-count:'+rid)%min(19,row['daily_quantity'])
        factor=1000+market.price(registry,state.save_id,d,rid)['variation_permille']
        reward=max(1,row['value_coins']*cfg['order_reward_permille']*factor*qty//1000000)
        oid=f'{d}:{index}';out.append({'order_id':oid,'resource_id':rid,'quantity':qty,'coins':reward,'market_day':d,'quote_id':f'{rid}:{qty}:{reward}','end_ms':(d+1)*state.time['day_length_ms'],'complete':today(state)['orders'].get(oid,False)})
    return out

def cycle(state,registry):return market.day(state)//settings(registry)['auction_period_days']
def auction_offers(state,registry):
    cfg=settings(registry);cy=cycle(state,registry);pool=[rid for rid in market.eligible(state,registry) if cfg['items'][rid]['boss_only'] or cfg['items'][rid]['level']>=4];out=[]
    for index in range(min(cfg['auction_slots'],len(pool))):
        rid=pool.pop(market.draw(state.save_id,cy,f'auction:{index}')%len(pool));v=cfg['items'][rid]['value_coins']
        out.append({'auction_id':f'{cy}:{rid}','resource_id':rid,'cycle':cy,'end_ms':(cy*cfg['auction_period_days']+cfg['auction_duration_days'])*state.time['day_length_ms'],'start_coins':max(1,v*9//10),'npc_bid':v*(1100+market.draw(state.save_id,cy,'npc:'+rid)%701)//1000})
    return out

def consignment_quote(state,registry,rid):
    cfg=settings(registry)
    if rid not in market.eligible(state,registry) or not (cfg['items'][rid]['boss_only'] or cfg['items'][rid]['level']>=4):raise ValidationError('仅已解锁的珍品可寄卖')
    v=cfg['items'][rid]['value_coins'];bid=v*(750+market.draw(state.save_id,market.day(state),'consign:'+rid)%401)//1000
    return {'resource_id':rid,'reserve':max(1,v*9//10),'npc_bid':bid,'end_ms':state.time['sim_time_ms']+cfg['auction_duration_days']*state.time['day_length_ms']}

def public_auctions(state,registry):
    c=ledger(state);now=state.time['sim_time_ms'];offers=[]
    for r in auction_offers(state,registry):
        saved=c['bids'].get(r['auction_id']);bid=saved['bid'] if saved else r['start_coins'];minimum=bid+max(1,(bid+9)//10)
        offers.append({k:v for k,v in r.items() if k!='npc_bid'}|{'your_bid':saved['bid'] if saved else 0,'min_bid':minimum,'open':now<r['end_ms']})
    claims=[]
    for aid,r in c['bids'].items():
        claims.append({'auction_id':aid,'resource_id':r['resource_id'],'bid':r['bid'],'end_ms':r['end_ms'],'ready':now>=r['end_ms'],'won':r['bid']>r['npc_bid'] if now>=r['end_ms'] else None})
    consignments=[]
    for aid,r in c['consignments'].items():
        sold=r['npc_bid']>=r['reserve'];net=r['npc_bid']*(1000-settings(registry)['auction_commission_permille'])//1000
        consignments.append({'consignment_id':aid,'resource_id':r['resource_id'],'reserve':r['reserve'],'end_ms':r['end_ms'],'ready':now>=r['end_ms'],'sold':sold if now>=r['end_ms'] else None,'coins':net if now>=r['end_ms'] and sold else 0})
    return {'offers':offers,'claims':claims,'consignments':consignments,'next_ms':(cycle(state,registry)+1)*settings(registry)['auction_period_days']*state.time['day_length_ms'],'commission_percent':settings(registry)['auction_commission_permille']/10,'history':c['history']}

"""Pure gated daily offers, cumulative stock and fixed-point saved-time prices."""
import hashlib
from functools import lru_cache
from src.core.validation import ValidationError, integer
from src.data.economy.market import settings
from src.systems.sect.rules import development

def day(state):return state.time['sim_time_ms']//state.time['day_length_ms']
def draw(save_id,day_index,salt):
    return int.from_bytes(hashlib.sha256(f'market-v2|{save_id}|{day_index}|{salt}'.encode()).digest(),'big')

def identity(registry,rid):return settings(registry).get('identity_aliases',{}).get(rid,rid)

def eligible(state,registry):
    p=state.domains.get('dungeon',{});floors={'thorn_path':p.get('cleared_floor',0),**p.get('progress',{})}
    rank=development(state.domains['sect'],registry,floors['thorn_path'])['level']
    return tuple(sorted((rid for rid,r in settings(registry)['items'].items() if rid not in settings(registry).get('retired_items',()) and rank>=r['sect_level'] and all(floors.get(k,0)>=n for k,n in r['unlock'].items())),key=lambda rid:identity(registry,rid)))

@lru_cache(maxsize=256)
def offers(registry,save_id,day_index,eligible_ids=None):
    cfg=settings(registry);pool=list(eligible_ids) if eligible_ids is not None else sorted((rid for rid in cfg['items'] if rid not in cfg.get('retired_items',())),key=lambda rid:identity(registry,rid));selected=[];boss=False
    for index in range(min(cfg['offers_per_day'],len(pool))):
        if boss:pool=[rid for rid in pool if not cfg['items'][rid]['boss_only']]
        if not pool:break
        weights=[cfg['tier_weights'][cfg['items'][rid]['level']-1] for rid in pool]
        ticket=draw(save_id,day_index,f'offer:{index}')%sum(weights)
        for i,weight in enumerate(weights):
            if ticket<weight:break
            ticket-=weight
        rid=pool.pop(i);selected.append(rid);boss=boss or cfg['items'][rid]['boss_only']
    return tuple(selected)

def current_offers(state,registry):return offers(registry,state.save_id,day(state),eligible(state,registry))
def stock_total(registry,save_id,day_index,rid):
    row=settings(registry)['items'][rid]
    return 1+draw(save_id,day_index,'stock:'+rid)%2 if row['boss_only'] else row['daily_quantity']
def stock_remaining(state,registry,rid):
    c=state.domains.get('sect_management',{}).get('commerce',{})
    used=0
    if c.get('day')==day(state):
        purchases=c.get('purchases',{});used=purchases.get(rid,0)
        legacy=identity(registry,rid)
        if legacy!=rid:used+=purchases.get(legacy,0)
    return max(0,stock_total(registry,state.save_id,day(state),rid)-used)
def price(registry,save_id,day_index,rid):
    cfg=settings(registry)
    if type(rid) is not str or rid not in cfg['items']:raise ValidationError('材料不在正式交易目录')
    item=cfg['items'][rid];limit=cfg['price_variation_permille']
    variation=draw(save_id,day_index,'price:'+identity(registry,rid))%(2*limit+1)-limit
    return {'variation_permille':variation,'buy_price_milli':item['buy_coins']*(1000+variation),'sell_price_milli':item['sell_coins']*(1000+variation)}

def quote(state,registry,payload,*,buy):
    if set(payload)!={'resource_id','quantity','market_day','price_milli'}:raise ValidationError('请刷新万宝楼，使用当日交易报价')
    integer(payload['quantity'],'交易数量',1);integer(payload['market_day'],'交易日');integer(payload['price_milli'],'交易单价',1)
    rid=payload['resource_id']
    if type(rid) is not str:raise ValidationError('请选择正式交易材料')
    if payload['market_day']!=day(state):raise ValidationError('商店已进入新的一天，请刷新商品和价格')
    if buy and (rid not in current_offers(state,registry) or payload['quantity']>min(settings(registry)['max_purchase_quantity'],stock_remaining(state,registry,rid))):raise ValidationError('此材料今日未上架或剩余库存不足')
    current=price(registry,state.save_id,day(state),rid)['buy_price_milli' if buy else 'sell_price_milli']
    if current!=payload['price_milli']:raise ValidationError('报价已变化，请刷新后交易')
    total=current*payload['quantity'];coins=(total+999)//1000 if buy else total//1000
    if coins<1:raise ValidationError('本次数量折算不足1灵钱，请增加数量')
    return coins

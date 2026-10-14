"""Daily commissions and durable first-clear choices on existing saved world time."""
from collections.abc import Mapping
from src.core.state.envelope import thaw_json
from src.core.validation import ValidationError,integer
from src.data.registry import DefinitionKey
from src.data.economy.activities import settings
from . import market
from src.systems.dungeons import progress
from src.systems.inventory import holdings

COMMANDS=('sect_commission_claim','sect_contribution_exchange','boss_chest_open')
FIELDS={'contribution','earned','day','completed','issued','chests'}
def initial():return dict(contribution=0,earned=0,day=0,completed=[],issued=[],chests={})
def ledger(state):return thaw_json(state.domains['sect_management'].get('activities',initial()))
def today(state):
    p=ledger(state)
    if p['day']!=market.day(state):p.update(day=market.day(state),completed=[])
    return p

def validate(p,registry):
    c=settings(registry)
    if not isinstance(p,Mapping) or set(p)!=FIELDS:raise ValidationError('invalid activity ledger')
    for key in ('contribution','earned','day'):integer(p[key],key)
    if p['contribution']>p['earned']:raise ValidationError('contribution exceeds earned total')
    for key,allowed in (('completed',{r['id'] for r in c['orders']}),('issued',set(c['dungeons']))):
        if not isinstance(p[key],(list,tuple)) or len(p[key])!=len(set(p[key])) or not set(p[key])<=allowed:raise ValidationError('invalid activity identities')
    if not isinstance(p['chests'],Mapping) or not set(p['chests'])<=set(p['issued']):raise ValidationError('invalid pending chests')
    for did,row in p['chests'].items():
        if not isinstance(row,Mapping) or set(row)!={'tier','battle_id'} or row['tier']!=list(c['dungeons']).index(did)+1 or type(row['battle_id']) is not str or not row['battle_id']:raise ValidationError('invalid first-clear chest')
    return p

def orders(state,registry):
    p=today(state);eligible=set(market.eligible(state,registry));out=[];day=market.day(state)
    for row in settings(registry)['orders']:
        pool=sorted(rid for rid in row['items'] if rid in eligible)
        if not pool:continue
        rid=pool[market.draw(state.save_id,day,'commission:'+row['id'])%len(pool)]
        quantity=row['items'][rid];quote=f'{day}:{row["id"]}:{rid}:{quantity}:{row["contribution"]}'
        out.append(dict(order_id=row['id'],name=row['name'],resource_id=rid,quantity=quantity,contribution=row['contribution'],market_day=day,quote_id=quote,complete=row['id'] in p['completed'],end_ms=(day+1)*state.time['day_length_ms']))
    return out

def chest_quote(state,registry,battle):
    cfg=settings(registry)
    did=next((d for d in cfg['dungeons'] if progress.definition(registry,d).encounters[-1]==battle['encounter_id']),None)
    if did is None or progress.cleared(state.domains['dungeon'],did)>=100 or did in ledger(state)['issued']:return None
    return dict(chest_id=did,name=progress.definition(registry,did).display_name+'首通宝箱',tier=list(cfg['dungeons']).index(did)+1)

def issue_chest(before,candidate,registry,battle):
    quote=chest_quote(before,registry,battle)
    if quote is None:return None
    did=quote['chest_id'];p=ledger(candidate)
    if did in p['issued']:return None
    p['issued'].append(did);p['chests'][did]={'tier':quote['tier'],'battle_id':battle['battle_id']};validate(p,registry)
    return p

def rewards(registry,did,choice):
    cfg=settings(registry)
    if did not in cfg['dungeons']:raise ValidationError('unknown chest')
    row=next((r for r in cfg['chest_choices'] if r['id']==choice),None)
    if row is None:raise ValidationError('请选择装备成长、宗门经营或功法成长')
    factor=list(cfg['dungeons']).index(did)+1
    return {rid:n*factor for rid,n in row['rewards'].items()}

def view(state,registry,capacity):
    p=today(state);cfg=settings(registry);stock=state.domains['inventory']['holdings'];reserves=state.domains['sect_management']['material_reserves']
    blocked=bool(state.time['pending'])
    def amount_rows(amounts):return [dict(resource_id=rid,name=registry.lookup(DefinitionKey('resources',rid)).display_name,quantity=n) for rid,n in amounts.items()]
    rows=orders(state,registry)
    for r in rows:
        r['resource_name']=registry.lookup(DefinitionKey('resources',r['resource_id'])).display_name
        r['can_claim']=not blocked and not r['complete'] and stock.get(r['resource_id'],0)-r['quantity']>=reserves.get(r['resource_id'],0)
    free=max(0,capacity-holdings.stock_size(state.domains['inventory'],registry))
    def fits(amounts):return sum(n for rid,n in amounts.items() if holdings.definition(registry,rid).warehouse_counted)<=free
    exchanges=[dict(id=r['id'],name=r['name'],cost=r['cost'],rewards=amount_rows(r['rewards']),can_exchange=not blocked and p['contribution']>=r['cost'] and fits(r['rewards'])) for r in cfg['exchanges']]
    chests=[dict(chest_id=did,name=progress.definition(registry,did).display_name+'首通宝箱',tier=r['tier'],choices=[dict(id=choice['id'],name=choice['name'],rewards=amount_rows(rewards(registry,did,choice['id'])),can_open=not blocked and fits(rewards(registry,did,choice['id']))) for choice in cfg['chest_choices']]) for did,r in p['chests'].items()]
    rank=next(r for r in reversed(cfg['reputation']) if p['earned']>=r['threshold'])
    return dict(contribution=p['contribution'],earned=p['earned'],reputation=rank['name'],orders=rows,exchanges=exchanges,chests=chests,blocked=blocked,daily_cap=sum(r['contribution'] for r in cfg['orders']),warehouse_available=free)

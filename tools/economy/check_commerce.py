"""Level-1 deterministic pricing/shop/drop policy comparison; no production writes."""
import json,hashlib,statistics
from pathlib import Path
from types import SimpleNamespace
from collections import Counter
from src.data.dungeons.definitions import load_dungeons
from src.data.economy.market import settings
from src.data.registry import DefinitionKey
from src.data.dungeons import loot
from src.systems.sect import market
from src.systems.equipment import items
from src.systems.economy.valuation import craft_inputs
from src.application.danding import initial_slice

ROOT=Path(__file__).resolve().parents[2]

def old_draw(sid,d,salt):return int.from_bytes(hashlib.sha256(f'market-v1|{sid}|{d}|{salt}'.encode()).digest(),'big')
def old_offers(cfg,sid,d):
    pool=sorted(cfg['items']);out=[]
    for i in range(20):
        weights=[cfg['tier_weights'][cfg['items'][k]['level']-1] for k in pool];ticket=old_draw(sid,d,f'offer:{i}')%sum(weights)
        for pos,w in enumerate(weights):
            if ticket<w:break
            ticket-=w
        out.append(pool.pop(pos))
    return out

def run():
    r=load_dungeons(management=True);new=settings(r);old=json.loads((ROOT/'balance/commerce-v2-baseline.json').read_text());base=initial_slice(r,last_settled_at_ms=1000);out={'scope':'economy level 1; fixed successful kill cadence, no combat win-rate claim','seeds':100,'game_days_per_hour':30,'baseline':'market-v1 exact rules from saved JSON','shop':{},'drops':{},'spread_and_craft':{}}
    for stage in (1,2,3):
        before=[];after=[]
        for seed in range(100):
            sid=f'00000000-0000-4000-8000-{seed:012d}';sect={'buildings':{k:{**v,'level':5 if stage==3 else v['level']} for k,v in base.domains['sect']['buildings'].items()}}
            dungeon={'cleared_floor':100 if stage>1 else 0,'progress':{'red_copper_mine':100,'mist_marsh':100} if stage==3 else {}}
            s=SimpleNamespace(save_id=sid,time={'sim_time_ms':0,'day_length_ms':120000},domains={'sect':sect,'dungeon':dungeon,'sect_management':{}});a=b=0
            for d in range(30):
                s.time['sim_time_ms']=d*120000
                for rid in old_offers(old,sid,d):
                    factor=1000+old_draw(sid,d,'price:'+rid)%401-200;a+=(old['items'][rid]['buy_coins']*factor+999)//1000
                for rid in market.current_offers(s,r):b+=(market.price(r,sid,d,rid)['buy_price_milli']+999)//1000
            before.append(a);after.append(b)
        out['shop'][str(stage)]={'policy':'buy one of each daily offer, no repeat purchases','before_coins_out_mean':round(statistics.mean(before),2),'after_coins_out_mean':round(statistics.mean(after),2),'after_range':[min(after),max(after)],'warehouse_net_per_hour':600,'full_from_empty_5000_percent':0}
    for did,floor,cadence in [('thorn_path',99,30),('thorn_path',100,40),('red_copper_mine',100,40),('mist_marsh',100,40)]:
        definition=r.lookup(DefinitionKey('dungeons',did));enc=definition.encounters[floor-1];e=r.lookup(DefinitionKey('encounters',enc));reward=dict(r.lookup(DefinitionKey('monsters',e.monster_id)).reward);version='thorn-loot-v2' if did=='thorn_path' else ''
        if did!='thorn_path':
            from src.data.dungeons.expeditions import content
            version=content(did)['loot']['version']
        before=[];after=[];growth=[]
        for seed in range(100):
            a=b=0;count=0
            for i in range(3600//cadence):
                result=loot.plan(r,{'battle_id':f'economy-v2:{did}:{seed}:{i}','encounter_id':enc,'loot_version':version});a+=reward.get('coins',0);b+=reward.get('coins',0)
                for rid,n in result['amounts'].items():a+=n*old['items'][rid]['sell_coins'];b+=n*new['items'][rid]['sell_coins'];count+=n
                if result['equipment']:
                    d=items.definition(r,result['equipment']);a+=d.sell_coins;b+=items.sale_price(r,d.machine_id)
            before.append(a);after.append(b);growth.append(count)
        out['drops'][f'{did}:{floor}']={'policy':'sell all materials at baseline and all gear, all kills successful; cadence seconds stated','cadence_seconds':cadence,'before_coins_in_mean':round(statistics.mean(before),2),'after_coins_in_mean':round(statistics.mean(after),2),'after_range':[min(after),max(after)],'warehouse_net_if_sold':0,'material_growth_if_kept_mean':round(statistics.mean(growth),2),'full_if_kept_from_empty_5000_percent':sum(n>5000 for n in growth),'full_if_kept_from_4800_percent':sum(n>200 for n in growth)}
    worst_ratio=max(v['sell_coins']*1200/(v['buy_coins']*800) for v in new['items'].values())
    assert worst_ratio<1
    counts=Counter();eligible=tuple(sorted(new['items']))
    for d in range(1000):
        offers=market.offers(r,'fixed-commerce-frequency',d,eligible);assert len(offers)==20 and len(set(offers))==20;assert sum(new['items'][k]['boss_only'] for k in offers)<=1
        counts.update(offers)
    margins=[]
    from src.data.economy.sect_rules import settings as sect_settings
    cfg=sect_settings(r)
    for key in (*cfg['craft']['materials'],*cfg['craft']['boss_equipment'],*cfg['management']['craft_costs']):
        cost=craft_inputs(r,key);minimum=sum(n*(1 if rid=='coins' else new['items'][rid]['buy_coins']*.8) for rid,n in cost.items());sale=items.sale_price(r,key);assert sale<minimum;margins.append(minimum-sale)
    out['spread_and_craft']={'max_cross_day_sell_to_buy_ratio':round(worst_ratio,4),'min_immediate_craft_loop_loss':round(min(margins),2),'boss_offers_max_per_day':1,'boss_material_daily_appearances':{k:counts[k] for k in counts if new['items'][k]['boss_only']}}
    out['idle']={'coins_per_hour':0,'warehouse_net':0};out['limits']='Models exclude combat failure, all production/food expenses and voluntary auction bidding; not a full progression or long-run economy claim. Orders, escrow and capacity verified through real isolated SQLite/HTTP tests.'
    target=ROOT/'.tmp/task63-economy.json';target.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n');print(json.dumps(out,ensure_ascii=False))
if __name__=='__main__':run()

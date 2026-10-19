"""Bounded isolated exploration economy samples; no saves, services or wall clock."""
import json
from types import SimpleNamespace
from pathlib import Path
import sys
if __name__ == '__main__':
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from src.data.content_loader import load_current
from src.data.exploration.definitions import settings
from src.systems.sect import exploration
from src.systems.sect.market import draw
from src.systems.inventory.holdings import stock_size


def simulate(samples=1000):
    registry=load_current();rows=[]
    # 120-second day, 30 game days/hour; supplies pre-funded for comparison.
    initial={'coins':10000,'ordinary_wood':100,'spring_water':100}
    initial_size=stock_size({'holdings':initial},registry)
    for region in settings(registry)['regions']:
        for policy in (0,1):
            for spare in (20,200):
                coin_net=item_net=full=completed=0
                for seed in range(samples):
                    sid=f'economy-exploration-{seed}';stock=dict(initial);count=0
                    for visit in range(1,30//region['duration_days']+1):
                        eid=exploration.scheduled_event(registry,sid,region['id'],visit)
                        event=next(e for e in region['events'] if e['id']==eid);c=event['choices'][policy]
                        maximum=exploration.rewards(registry,region['id'],c,True)
                        if not exploration.fits({'holdings':stock},registry,initial_size+spare,c['cost'],maximum):
                            full+=1;break
                        if any(stock.get(rid,0)<n for rid,n in c['cost'].items()):
                            raise AssertionError('economic sample must be pre-funded')
                        success=draw(sid,visit,'exploration:result')%10000<c['success_bps']
                        for rid,n in c['cost'].items():stock[rid]-=n
                        for rid,n in exploration.rewards(registry,region['id'],c,success).items():stock[rid]=stock.get(rid,0)+n
                        count+=1
                    coin_net+=stock['coins']-initial['coins'];item_net+=stock_size({'holdings':stock},registry)-initial_size;completed+=count
                rows.append(dict(region=region['name'],policy='稳妥选项' if policy==0 else '第二选项',spare=spare,
                                 coin_net_mean=round(coin_net/samples,3),warehouse_net_mean=round(item_net/samples,3),
                                 full_rate=round(full/samples,4),completed_mean=round(completed/samples,3)))
    return {'samples_per_row':samples,'game_day_ms':120000,'hours':1,'baseline_without_exploration':{'coins':0,'warehouse':0,'full_rate':0},'rows':rows}


if __name__=='__main__':print(json.dumps(simulate(),ensure_ascii=False,indent=2))

"""Level-one bounded economic checks using disposable shipping fixtures only."""
import argparse,json
from pathlib import Path
from dataclasses import replace
from src.core.state.envelope import thaw_json
from src.data.economy.activities import settings
from src.data.economy.market import settings as market_settings
from src.application.sect_activities import transition
from src.systems.sect import activities
from src.systems.inventory import holdings
from tests.systems.test_sect_activities import ActivityTests

ROOT=Path(__file__).resolve().parents[2]
def audit():
    ActivityTests.setUpClass();case=ActivityTests();case.setUp()
    try:
        base=replace(case.read(),save_id='00000000-0000-4000-8000-000000000093');cfg=settings(case.registry);pricing=market_settings(case.registry)['items'];out={}
        value=lambda rid:1 if rid=='coins' else pricing[rid]['value_coins']
        for label,ms in [('30分钟',1800000),('24小时',86400000)]:
            state=base;days=ms//base.time['day_length_ms'];cost_value=0;claims=0;units=0
            for day in range(days):
                state=replace(state,time={**state.time,'sim_time_ms':day*state.time['day_length_ms']})
                for row in activities.orders(state,case.registry):
                    stock=thaw_json(state.domains['inventory']);stock['holdings'][row['resource_id']]=row['quantity']+10
                    state=replace(state,domains={**state.domains,'inventory':stock})
                    state,_=transition(state,case.registry,'sect_commission_claim',{k:row[k] for k in ('order_id','market_day','quote_id')},100000)
                    cost_value+=value(row['resource_id'])*row['quantity'];claims+=1
                    units+=row['quantity'] if holdings.definition(case.registry,row['resource_id']).warehouse_counted else 0
            points=activities.ledger(state)['contribution']
            out[label]={'game_days':days,'manual_claims':claims,'contribution_max':points,'input_nominal_coins':cost_value,'coins_exchange_max':points//100*200,'manual_page_exchange_max':points//100,'commission_stock_units_consumed':units,'coins_or_pages_warehouse_addition':0}
        ratios={r['id']:sum(value(k)*n for k,n in r['rewards'].items())/r['cost'] for r in cfg['exchanges'] if all(k=='coins' or k in pricing for k in r['rewards'])}
        assert max(ratios.values())<=2
        assert all(r['coins_exchange_max']<r['input_nominal_coins'] for r in out.values())
        out.update(seed=base.save_id,game_day_ms=base.time['day_length_ms'],exchange_nominal_value_per_contribution=ratios,boss_chests_lifetime_max=len(cfg['dungeons']),boss_repeat_additional_chests=0,context='经济级别1；库存无限供给且每单即时手动完成的上界，非自动收益或真实生产模拟。离线零免费贡献和满仓领取由shipping专项测试验证；战斗和原掉落不变。')
        return out
    finally:case.doCleanups()
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',default='docs/acceptance/TASK0093/economy.json');args=parser.parse_args()
    output=(ROOT/args.output).resolve()
    if not output.is_relative_to(ROOT):parser.error('output must stay in V2')
    output.parent.mkdir(parents=True,exist_ok=True);result=audit();output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))

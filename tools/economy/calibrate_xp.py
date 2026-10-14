"""Small deterministic sample only; never reads production saves."""
import json,csv,sys
from pathlib import Path
from statistics import mean
from src.data.dungeons.definitions import load_dungeons
from src.systems.cultivation import leveling
from src.systems.combat import battle,equipment_effects
from src.systems.equipment import items
ROOT=Path(__file__).resolve().parents[2]
SLOTS=['thorn_fang_blade','thorn_vine_gloves','thorn_travel_belt','thorn_scale_shirt','thorn_moss_boots','thorn_feather_hood']


def actor(registry,c,L,loadout):
    stats=leveling.stat_totals(L,(L-1)//500,c)
    for key in SLOTS:
        d=items.definition(registry,key)
        values=dict(d.stats) if loadout=='mean' else {k:v[0 if loadout=='low' else 1] for k,*v in d.stat_ranges}
        for k,n in values.items():stats[k]=stats.get(k,0)+n
    for key,limit in items.RATE_CAPS.items():
        if key in stats:stats[key]=min(stats[key],limit)
    return {'id':'design:hero','definition_id':'hero','name':'无名行者','asset_id':'player.combat.hero',**stats}


def sample(registry,c,f,L,loadout):
    p=actor(registry,c,L,loadout);wins=[];all_seconds=[]
    for i in range(64):
        b=battle.start(battle.initial(),registry,'design',f'balance-v1:{f}:{i}',f'thorn_path_v2_{f:03}',player_snapshot=p)
        end,_,rounds=battle.result_only(b,registry,'design');seconds=rounds*equipment_effects.interval(p)/1000
        all_seconds.append(seconds)
        if end['battle']['status']=='PLAYER_WIN':wins.append(seconds)
    return {'floor':f,'level':L,'loadout':loadout,'wins':len(wins),'runs':64,'win_pct':len(wins)*100/64,'mean_kill_seconds':mean(wins) if wins else None,'mean_battle_seconds':mean(all_seconds)}


if __name__=='__main__':
    registry=load_dungeons(management=True,cold_jade=True,ecology=True);c=json.loads((ROOT/'src/data/cultivation/leveling.json').read_text())
    if '--probe' in sys.argv:
        for coefficient in (2500,4000,5500,7000,10000):
            c['growth_coefficient_bps']=coefficient
            print(coefficient,sample(registry,c,100,1000,'mean'),flush=True)
    else:
        rows=[sample(registry,c,f,f*10*ratio//10,loadout) for f in (1,30,60,100) for ratio in (8,10,12) for loadout in ('low','mean','high')]
        out=ROOT/'docs/economy-export/xp-calibration-cases.csv'
        with out.open('w') as stream:
            writer=csv.DictWriter(stream,fieldnames=rows[0]);writer.writeheader();writer.writerows(rows)
        means=[row for row in rows if row['level']==row['floor']*10 and row['loadout']=='mean']
        # K counts successful kills per observed combat time, including defeats.
        K=round(3600*sum(row['wins'] for row in means)/sum(row['mean_battle_seconds']*64 for row in means))
        print(json.dumps({'K':K,'X0':c['X0'],'mean_samples':means},ensure_ascii=False),flush=True)

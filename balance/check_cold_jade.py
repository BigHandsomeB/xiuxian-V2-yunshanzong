"""Run from the V2 root: PYTHONPATH=. .venv/bin/python -B balance/check_cold_jade.py."""
import csv,json,statistics,time
from pathlib import Path
from src.data.dungeons.definitions import load_dungeons
from src.data.dungeons import loot,expeditions
from src.data.registry import DefinitionKey
from src.core.state.envelope import thaw_json
from src.systems.equipment import items
from src.systems.cultivation import growth
from src.systems.combat import battle
from src.systems.dungeons import progress
r=load_dungeons(cold_jade=True);floors=[1,9,10,20,29,30,40,49,50,60,69,70,80,89,90,99,100]
base=growth.projection({**growth.initial('design'),'current_realm':'realm_1','growth_revision':1},r,'design')
def player(did,level):
 part={'slots':{},'instances':{}}
 for index in (1,3,5,7,9,10):
  id=loot.content()['equipment'][index-1]['id'] if did=='thorn_path' else f'{did}_equipment_{index:02d}'
  d=items.definition(r,id);ranges={k:(lo,hi,step) for k,lo,hi,step in d.stat_ranges}
  stats={k:ranges[k][0 if level=='low' else 1] if level!='mean' else n for k,n in d.stats}
  part['slots'][d.slot]=id;part['instances'][id]={'stats':stats,'affixes':[]}
 return items.projection(part,base)
def fight(did,floor,i,p,seed,*,historical=False,registry=None):
 registry=registry or r
 id=f'{seed}:{floor}:{i}';eid=progress.definition(registry,did).encounters[floor-1];b=battle.start(battle.initial(),registry,'design',id,eid,player_snapshot=p)
 if historical:
  b=thaw_json(b);b['battle'].pop('rules_version')
 for _ in range(200):
  if b['battle']['status']!='ACTIVE':break
  b=battle.attack(b,registry,'design',id)
 row=b['battle'];return row['status']=='PLAYER_WIN',row['step'],100*row['player_hp_milli']/p['max_hp_milli']
prior=list(csv.DictReader(l for l in open('docs/economy-export/combat-baseline-summary.csv') if not l.startswith('#')))
baseline=[]
for level,label in [('low','筑基六件低值'),('mean','筑基六件均值'),('high','筑基六件高值')]:
 p=player('thorn_path',level);runs=[fight('thorn_path',100,i,p,'balance-v1',historical=True) for i in range(64)];wins=[x for x in runs if x[0]];reference=next(v for v in prior if v['floor']=='100' and v['loadout']==label)
 assert len(wins)==int(reference['wins']), (level,len(wins),reference)
 current=[fight('thorn_path',100,i,p,'balance-v1') for i in range(64)]
 prior_current=[fight('thorn_path',100,i,p,'balance-v1',registry=load_dungeons()) for i in range(64)]
 assert current==prior_current
 baseline.append({'loadout':label,'historical_wins':len(wins),'current_wins':sum(x[0] for x in current),'runs':64,'before_after_identical':True})
print('Historical Boss baseline reproduced:',baseline,flush=True)
summary=[];t=time.monotonic()
for did in ('mist_marsh','cold_jade_cave'):
 for level in ('low','mean','high'):
  p=player(did,level)
  for floor in floors:
   runs=[fight('cold_jade_cave',floor,i,p,'cold-jade-v1') for i in range(64)]
   wins=[x for x in runs if x[0]]
   if 0.05<len(wins)/64<0.95:runs.extend(fight('cold_jade_cave',floor,i,p,'cold-jade-v1') for i in range(64,1000));wins=[x for x in runs if x[0]]
   summary.append({'gear':did,'level':level,'floor':floor,'wins':len(wins),'runs':len(runs),'win_pct':round(100*len(wins)/len(runs),1),'mean_win_rounds':round(statistics.mean(x[1] for x in wins),1) if wins else None,'mean_win_hp_pct':round(statistics.mean(x[2] for x in wins),1) if wins else None})
  print('Finished',did,level,flush=True)
# Verify a reachable loadout using the previous dungeon's Boss equipment.
progression=[]
for stage in (0,4000):
 base=growth.projection({**growth.initial('design'),'current_realm':'realm_1','growth_revision':1,'progress':stage},r,'design')
 for level in ('mean','high'):
  part={'slots':{},'instances':{}}
  for did,index in [('mist_marsh',11),('cold_jade_cave',3),('cold_jade_cave',5),('mist_marsh',12),('cold_jade_cave',9),('cold_jade_cave',10)]:
   id=f'{did}_equipment_{index:02d}';d=items.definition(r,id);ranges={k:(lo,hi,step) for k,lo,hi,step in d.stat_ranges};stats={k:n if level=='mean' else ranges[k][1] for k,n in d.stats};part['slots'][d.slot]=id;part['instances'][id]={'stats':stats,'affixes':[]}
  p=items.projection(part,base)
  for floor in (70,80,90,100):
   runs=[fight('cold_jade_cave',floor,i,p,'cold-jade-v1') for i in range(64)];wins=[x for x in runs if x[0]]
   if 0.05<len(wins)/64<0.95:runs.extend(fight('cold_jade_cave',floor,i,p,'cold-jade-v1') for i in range(64,1000));wins=[x for x in runs if x[0]]
   progression.append({'stage':stage,'gear':'mist_boss_plus_cold_normal','level':level,'floor':floor,'wins':len(wins),'runs':len(runs),'win_pct':round(100*len(wins)/len(runs),1)})
# The new normal equipment pool uses the unchanged 15% roll and ten equal choices.
p=expeditions.content('cold_jade_cave');pool=[x for x in p['equipment'] if not x['boss_only']];collection=[]
for trial in range(10000):
 slots=set();attempts=0
 while len(slots)<6:
  attempts+=1;seed=f'cold-jade-collection:{trial}:{attempts}|'+p['loot']['version']
  if loot.roll(seed,'equipment')<p['loot']['rates']['normal']['equipment_bps']:slots.add(pool[loot.roll(seed,'choice')%len(pool)]['slot'])
 collection.append(attempts)
collection.sort();out={'baseline':baseline,'summary':summary,'progression':progression,'progression_battles':sum(x['runs'] for x in progression),'battles':sum(x['runs'] for x in summary),'collection':{'trials':10000,'p50_normal_wins':collection[4999],'p90_normal_wins':collection[8999],'assumptions':'胜利后的普通层领奖次数；不含战败、Boss、精英、强化与随机附加属性。'},'seconds':round(time.monotonic()-t,1)}
Path('balance/cold-jade-v1-validation.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in out.items() if k not in ('summary','progression')},ensure_ascii=False),flush=True)
print('Boss samples',json.dumps([x for x in summary if x['floor']==100],ensure_ascii=False),flush=True)

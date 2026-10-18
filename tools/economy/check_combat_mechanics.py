"""Bounded deterministic balance runner; pure Combat only, never a player database."""
import argparse
import csv
import json
from pathlib import Path
import re
import random
from statistics import mean
import sys
ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from src.data.content_loader import load_current
from src.data.registry import DefinitionKey
from src.data.dungeons.definitions import load_dungeons
from src.core.state.envelope import thaw_json
from src.data.economy.sect_rules import settings as sect_settings
from src.data.combat.mechanics import settings
from src.systems.combat import battle
from src.systems.cultivation import leveling,techniques
from src.systems.equipment import items

SLOTS=['thorn_fang_blade','thorn_vine_gloves','thorn_travel_belt','thorn_scale_shirt','thorn_moss_boots','thorn_feather_hood']
BUILDS={
 'shield':['逍遥无极身','护元功','万剑归宗诀','鸿蒙镇世印','养气诀','北冥玄功','鸿蒙养气经','太极混元功'],
 'fire':['踏雪无痕','寒玉护身诀','赤炎掌','五行灭世轮','纯阳真诀','青木养气诀','归元功','赤阳炼气诀'],
 'ice':['踏风步','金钟诀','寒霜指','万法寂灭诀','寒阴凝元诀','厚土培元功','阴阳调息诀','玄天炼元诀']}
GEAR=['离火焚丹刃','铜炉护手','熔芯腰甲','丹墟镇炉甲','烬火踏靴','朱砂丹冠']

def build_actor(registry,name,gear_quality="mean",enhancement=0):
 c=settings(registry);tc=techniques.config(registry);lc=leveling.config(registry)
 ids={v['name']:k for k,v in c['techniques'].items()};gear={v['name']:k for k,v in c['equipment'].items()}
 owned={}
 for n in BUILDS[name]:
  row=techniques.definition(tc,ids[n]);owned[ids[n]]=techniques.threshold(tc,tc['grades'][row['grade']],row)
 growth={'player_id':'design:hero','current_realm':'realm_1','total_xp':leveling.table(lc)[1000],
         'growth_revision':1,'techniques':{'owned':owned,'slots':dict(zip(tc['slots'],owned))}}
 actor=dict(leveling.projection(growth,registry,'design'));sources=[gear[n] for n in GEAR]
 for key in sources:
  for stat,low,high,step in items.equipment_ranges(key):
   n=low if gear_quality=='low' else high if gear_quality=='high' else (low+high)//2
   if stat in ('max_hp_milli','attack_milli','armor_milli'):n+=n*enhancement*sect_settings(registry)['management']['enhancement_bonus_bps_per_level']//10000
   actor[stat]=actor.get(stat,0)+n
 for key,cap in items.RATE_CAPS.items():
  if key in actor:actor[key]=min(cap,actor[key])
 return actor,growth,sources

def cases(registry,mode,build=None,dungeon=None,floor=None,gear_quality="mean",enhancement=0):
 if mode in ('baseline','historical'):
  # Frozen six historical actors measure formula changes; they are not a current progression model.
  actors=json.loads(re.search(r'```json\n(.*?)\n```',(ROOT/'balance/baseline-spec.md').read_text(),re.S).group(1))
  for f in [1,9,10,20,29,30,40,49,50,60,69,70,80,89,90,99,100]:
   for name,actor in actors.items():yield name,'thorn_path',f,actor,None,SLOTS if '六件' in name else []
 else:
  for name in ([build] if build else BUILDS):
   actor,growth,sources=build_actor(registry,name,gear_quality,enhancement)
   for did in ([dungeon] if dungeon else ['cold_jade_cave','fire_elixir_ruins']):
    for f in ([floor] if floor else [1,50,100]):yield name,did,f,actor,growth,sources

def slot_samples(registry,samples=10000):
 from src.data.dungeons.expeditions import content
 package=content('fire_elixir_ruins');rates=package['loot']['rates']
 normal=[r['slot'] for r in package['equipment'] if not r['boss_only']];boss=[r['slot'] for r in package['equipment'] if r['boss_only']]
 required=set(normal)|set(boss);rng=random.Random(0);totals=[]
 for _ in range(samples):
  collected=set();cycle=0
  while collected!=required:
   cycle+=1
   for f,tier in enumerate(registry.lookup(DefinitionKey('dungeons','fire_elixir_ruins')).tiers,1):
    if rng.randrange(10000)<rates[tier]['equipment_bps']:collected.add(rng.choice(boss if tier=='boss' else normal))
    if collected==required:break
   if cycle>10000:raise RuntimeError('slot simulation exceeded its work bound')
  totals.append((cycle-1)*100+f)
 totals.sort()
 return {'content_version':registry.content_version,'mode':'slots','cases':samples,'rng_seed':0,
         'assumptions':'Current fifth-dungeon drops only; full 100-floor loops; no forging, trade, failed fights or retention policy.',
         'p50_floor_clears':totals[samples//2],'p90_floor_clears':totals[(samples*9)//10],
         'p50_full_loops_equivalent':totals[samples//2]/100,'p90_full_loops_equivalent':totals[(samples*9)//10]/100}

def run(mode='baseline',runs=64,build=None,dungeon=None,floor=None,gear_quality='mean',enhancement=0,only=None):
 registry=load_dungeons(expansion_legacy=True) if mode=='historical' else load_current();rows=[]
 if mode=='historical' and runs!=64:raise ValueError('historical reference requires 64 fixed seeds')
 if mode=="slots":return slot_samples(registry)
 for name,did,f,actor,growth,sources in cases(registry,mode,build,dungeon,floor,gear_quality,enhancement):
  if only is not None and (name,did,f) not in only:continue
  encounters=registry.lookup(DefinitionKey('dungeons',did)).encounters
  wins=[];all_rounds=[]
  for seed in range(runs):
   identity=f'balance-v1:{f}:{seed}' if mode in ('baseline','historical') else f'new:{name}:{did}:{f}:{seed}'
   initial=battle.start(battle.initial(),registry,'design',identity,encounters[f-1],player_snapshot=actor,growth_snapshot=growth,equipment_sources=sources)
   if mode=='historical':
    initial=thaw_json(initial);snapshot=initial['battle'];snapshot['enemy_hp_scale_bps']=10000
    snapshot['enemy_hp_milli']=registry.lookup(DefinitionKey('monsters',snapshot['enemy_id'])).base_hp_milli;snapshot.pop('rules_version',None)
   result,_,count=battle.result_only(initial,registry,'design');all_rounds.append(count)
   if result['battle']['status']=='PLAYER_WIN':wins.append((count,result['battle']['player_hp_milli']/actor['max_hp_milli']))
  row={'build':name,'dungeon':did,'floor':f,'wins':len(wins),'runs':runs,'win_pct':100*len(wins)/runs,
       'mean_rounds':mean(r[0] for r in wins) if wins else None,'mean_hp':mean(r[1] for r in wins) if wins else None,
       'mean_all_rounds':mean(all_rounds)}
  rows.append(row)
 mismatches=[]
 if mode=='historical':
  reference=list(csv.DictReader((ROOT/'docs/economy-export/combat-baseline-summary.csv').read_text().splitlines()[1:]))
  expected={(int(r['floor']),r['loadout']):r for r in reference}
  for row in rows:
   ref=expected[(row['floor'],row['build'])]
   if row['wins']!=int(ref['wins']) or row['wins'] and (abs(row['mean_rounds']-float(ref['mean_win_rounds']))>1e-9 or abs(row['mean_hp']*100-float(ref['mean_win_hp_pct']))>1e-8):mismatches.append(row)
 return {'content_version':registry.content_version,'rules_version':settings(registry)['version'] if settings(registry) else 'pre-attributes-v2','reference_mismatches':mismatches,
         'mode':mode,'gear_quality':gear_quality,'enhancement':enhancement,'cases':sum(r['runs'] for r in rows),'rows':rows}

if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--mode',choices=['baseline','historical','builds','slots'],default='baseline')
 parser.add_argument('--runs',type=int,default=64);parser.add_argument('--build',choices=list(BUILDS));parser.add_argument('--dungeon',choices=['cold_jade_cave','fire_elixir_ruins']);parser.add_argument('--floor',type=int)
 parser.add_argument('--gear-quality',choices=['low','mean','high'],default='mean');parser.add_argument('--enhancement',type=int,default=0);parser.add_argument('--critical-from');parser.add_argument('--output',required=True);args=parser.parse_args()
 if not 0<=args.enhancement<=10:parser.error('enhancement 0..10')
 if not 1<=args.runs<=1000 or args.floor is not None and not 1<=args.floor<=100:parser.error('runs 1..1000; floor 1..100')
 output=(ROOT/args.output).resolve()
 if not output.is_relative_to(ROOT/'.tmp') or output.suffix!='.json':parser.error('output must be a JSON file under project .tmp')
 only=None
 if args.critical_from:
  source=(ROOT/args.critical_from).resolve()
  if not source.is_relative_to(ROOT/'.tmp') or source.suffix!='.json':parser.error('critical source must be project .tmp JSON')
  prior=json.loads(source.read_text());only={(r['build'],r['dungeon'],r['floor']) for r in prior['rows'] if 5<r['win_pct']<95}
 result=run(args.mode,args.runs,args.build,args.dungeon,args.floor,args.gear_quality,args.enhancement,only);output.parent.mkdir(exist_ok=True);output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'status':'FAIL' if result.get('reference_mismatches') else 'COMPLETE','cases':result['cases'],'output':str(output)},ensure_ascii=False))

 if result.get("reference_mismatches"):sys.exit(1)

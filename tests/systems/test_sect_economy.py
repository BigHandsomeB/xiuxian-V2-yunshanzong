"""Basic shipping-rule checks using real isolated SQLite commands and receipts."""
import unittest,tempfile,json
from pathlib import Path
from uuid import uuid4
from dataclasses import replace
from unittest.mock import patch
from src.application.dungeons import DungeonApplication
from src.application.danding import initial_slice
from src.application.memory import Command
from src.application.settlement import SettlementRequest
from src.application import equipment as equip,sect
from src.application.sect_economy import defaults
from src.core.save.sqlite import SQLiteSave,V2_ROOT
from src.core.state.envelope import thaw_json
from src.core.validation import ValidationError,ConflictError,NotFoundError
from src.core.time.model import Continuation
from src.data.dungeons.definitions import load_dungeons
from src.data.economy.sect_rules import settings
from src.systems.economy import policy
from src.systems.economy.overflow import rewards,conversion_coins
from src.systems.sect import rules
from src.systems.cultivation import growth
from src.systems.resources import jobs
from tests.fixtures.time import ManualClock

class SectEconomyTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(dir=V2_ROOT/'tests');self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.r=load_dungeons();self.clock=ManualClock()
  self.store=SQLiteSave.initialize(self.root/'test.sqlite3',allowed_root=self.root);self.addCleanup(self.store.close);self.app=DungeonApplication(self.store,self.r,self.clock)
  self.s=initial_slice(self.r,last_settled_at_ms=1000);self.sid=self.s.save_id
 def create(self,stock=None,legacy=False,progress=0,realm='realm_0'):
  s=self.s;domains=thaw_json(s.domains);domains['inventory']['holdings']={'herb':30,**(stock or {})};domains['cultivation']={**growth.initial(self.sid),'progress':progress,'current_realm':realm,'growth_revision':1 if realm!='realm_0' else 0}
  domains['inventory']['holdings']={k:n for k,n in domains['inventory']['holdings'].items() if n}
  domains['automation']=thaw_json(policy.initial())
  if not legacy:domains['automation'].update(material_overflow=True,overflow_log=[])
  if legacy:domains['sect']['buildings']={k:v for k,v in domains['sect']['buildings'].items() if v['definition_id']!='smelter'}
  domains['disciples']['assignments']={}
  s=replace(s,domains=domains);self.app.create(s);return s
 def state(self):return self.app.query(self.sid)
 def bid(self,kind):return next(k for k,v in defaults(self.state(),self.r).domains['sect']['buildings'].items() if v['definition_id']==kind)
 def request(self,name,p):
  s=self.state();return Command(self.sid,s.generation,s.revision,str(uuid4()),name,p)
 def command(self,name,p):return self.app.execute(self.request(name,p))
 def assign(self,kind,count=1):
  gid=next(k for k,v in self.state().domains['disciples']['groups'].items() if v['count']>=count)
  return self.command('work_assign',{'worker_id':gid,'building_id':self.bid(kind),'count':count})
 def settle(self,ms):
  self.clock.advance(ms)
  for _ in range(100):
   s=self.state();result=self.app.settle(SettlementRequest(self.sid,s.generation,s.revision,str(uuid4()),32,Continuation.for_state(s) if s.time['pending'] else None))
   if result.result.status=='COMPLETE':return
  self.fail('short settlement did not complete')
 def assertRejected(self,name,p):
  before=self.state()
  with self.assertRaises((ValidationError,ConflictError,NotFoundError)):self.command(name,p)
  self.assertEqual(before,self.state())
 def rich(self):return {'coins':100000,'wood':1000,'stone':1000,'ingot':1000,**{k:200 for k in settings(self.r)['material_caps'] if k!='wood'}}
 def test_new_defaults_and_legacy_pure_read(self):
  self.assertTrue(self.s.domains['automation']['material_overflow'])
  self.assertEqual(sorted(r['target'] for r in self.s.domains['automation']['production'].values()),[30,200,200,200])
  self.create(legacy=True,progress=700);before=self.state();v=self.app.view(self.sid)
  self.assertFalse(v['economy']['material_overflow']);self.assertEqual(v['cultivation']['stage']['name'],'中期');self.assertEqual(self.state(),before)
  self.assertEqual(sum(r['definition_id']=='smelter' for r in v['buildings'].values()),1)
  q=self.request('material_overflow',{'enabled':True});r=self.app.execute(q);self.assertEqual(r,self.app.execute(q));self.assertEqual(len(self.state().domains['sect']['buildings']),len(before.domains['sect']['buildings'])+1)
 def test_overflow_exact_above_multiple_and_disabled(self):
  for current,incoming,kept,converted in [(199,1,1,0),(199,3,1,2),(200,3,0,3),(300,3,0,3)]:
   amounts,fold=rewards({'material_overflow':True},{'thorn_spine':current},self.r,{'thorn_spine':incoming,'coins':3})
   self.assertEqual(amounts['thorn_spine'],kept);self.assertEqual(fold.get('thorn_spine',0),converted);self.assertEqual(amounts['coins'],3+converted)
  amounts,fold=rewards({'material_overflow':False},{'wood':600},self.r,{'wood':10});self.assertEqual(amounts,{'wood':10});self.assertEqual(fold,{})
  current=199
  for _ in range(2):
   amounts,_=rewards({'material_overflow':True},{'thorn_spine':current},self.r,{'thorn_spine':2});current+=amounts['thorn_spine']
  self.assertEqual(current,200)
 def test_overflow_actual_reward_replay_before_storage(self):
  self.create({'wood':600,'thorn_spine':200,'stone':6170});self.command('combat_start',{'encounter_id':'thorn_path_v2_001'})
  bid=self.state().domains['combat']['battle']['battle_id']
  for _ in range(20):
   if self.state().domains['combat']['battle']['status']!='ACTIVE':break
   self.command('combat_attack',{'battle_id':bid})
  with patch('src.application.dungeons.loot.plan',return_value={'amounts':{'thorn_spine':2},'equipment':None}):
   before=self.state();expected_overflow={'wood':before.domains['combat']['battle']['reward']['wood'],'thorn_spine':2};expected_coins=before.domains['combat']['battle']['reward']['coins']+conversion_coins(self.r,expected_overflow);q=self.request('combat_reward',{'battle_id':bid});r=self.app.execute(q);after=self.state();self.assertEqual(r,self.app.execute(q));self.assertEqual(after,self.state());self.assertEqual(r.result['combat']['material_overflow']['amounts'],expected_overflow);self.assertEqual(after.domains['inventory']['holdings']['coins'],expected_coins)
 def test_auto_capacity_counts_consumption_equipment_and_reservations(self):
  self.create({'stone':3497});self.assign('mine')
  before=self.state()
  automatic=self.app.start_candidate(before,self.bid('mine'),'ore',policy_row={'max_consumption':0,'reserves':{}});self.assertEqual(automatic.domains['production']['jobs'][self.bid('mine')]['status'],'WORKING')
  manual=self.app.start_candidate(before,self.bid('mine'),'ore');self.assertEqual(manual.domains['production']['jobs'][self.bid('mine')]['status'],'WORKING')
 def test_auto_uses_actual_capacity(self):
  self.create({'stone':6967});self.assign('mine');s=self.state();c=self.app.start_candidate(s,self.bid('mine'),'ore',policy_row={'max_consumption':0,'reserves':{}});self.assertEqual(sum(c.domains['inventory']['holdings'].values())+3,sect.capacity_source(s,self.r)['effective'])
 def test_auto_waits_when_reserved_output_exceeds_actual_capacity(self):
  self.create({'stone':6968});self.assign('mine');before=self.state()
  with self.assertRaises(ValidationError):self.app.start_candidate(before,self.bid('mine'),'ore',policy_row={'max_consumption':0,'reserves':{}})
  self.assertEqual(self.state(),before)
 def test_auto_pill_target_stops_at_thirty(self):
  self.create({'pill':28,'herb':100});self.assign('alchemy',2);self.command('automation_production',{'building_id':self.bid('alchemy'),'policy':{'enabled':True,'recipe_id':'pill','target':30,'max_consumption':10,'reserves':{}}});self.settle(30000);self.assertEqual(self.state().domains['inventory']['holdings']['pill'],30);self.settle(30000);self.assertEqual(self.state().domains['inventory']['holdings']['pill'],30)
 def test_stone_and_ingot_open_and_retired_recipes_stay_closed(self):
  self.create({'ore':30},legacy=True);self.assign('smelter');self.command('production_start',{'building_id':self.bid('smelter'),'recipe_id':'ingot'});self.settle(30000);self.assertEqual(self.state().domains['inventory']['holdings']['ingot'],1)
  gid=next(k for k,v in self.state().domains['disciples']['groups'].items() if v['definition_id']=='ordinary_gather');self.command('work_assign',{'worker_id':gid,'building_id':self.bid('quarry'),'count':1});self.command('production_start',{'building_id':self.bid('quarry'),'recipe_id':'stone'});self.settle(30000);self.assertEqual(self.state().domains['inventory']['holdings']['stone'],3)
  self.assertRejected('production_start',{'building_id':self.bid('forge'),'recipe_id':'forge_sword'})
 def test_upgrade_quotes_and_atomic_replay(self):
  self.create(self.rich());bid=self.bid('warehouse')
  for current in [1,4,9]:
   part=thaw_json(self.state().domains['sect']);part['buildings'][bid]['level']=current;q=rules.quote_upgrade(part,self.r,bid);t=current+1;self.assertEqual(q['cost']['coins'],150*t*t);self.assertEqual(q['cost']['stone'],10*t);self.assertEqual(q['cost']['wood'],15*t);self.assertEqual(q['cost']['thorn_earth_core'],4*t)
  q=self.request('building_upgrade',{'building_id':bid});receipt=self.app.execute(q);after=self.state();self.assertEqual(receipt,self.app.execute(q));self.assertEqual(after,self.state());self.assertEqual(sect.capacity_source(after,self.r)['effective'],9000)
 def test_upgrade_insufficient_max_and_unopened(self):
  self.create();self.assertRejected('building_upgrade',{'building_id':self.bid('garden')});self.assertRejected('building_upgrade',{'building_id':self.bid('forge')})
  p=thaw_json(self.state().domains['sect']);p['buildings'][self.bid('garden')]['level']=10
  with self.assertRaises(ValidationError):rules.quote_upgrade(p,self.r,self.bid('garden'))
 def test_upgrade_does_not_change_inflight_yield(self):
  self.create(self.rich());self.assign('mine');self.command('production_start',{'building_id':self.bid('mine'),'recipe_id':'ore'});before=self.state().domains['production']['jobs'];self.command('building_upgrade',{'building_id':self.bid('mine')});self.assertEqual(before,self.state().domains['production']['jobs']);self.settle(30000);self.assertEqual(self.state().domains['inventory']['holdings']['ore'],3)
 def test_craft_all_definitions_in_range_old_items_unchanged_and_replay(self):
  self.create(self.rich());old=None
  for key in (*settings(self.r)['craft']['materials'],*settings(self.r)['craft']['boss_equipment']):
   q=self.request('equipment_craft',{'equipment_id':key});r=self.app.execute(q);after=self.state();self.assertEqual(r,self.app.execute(q));self.assertEqual(after,self.state());row=after.domains['equipment']['instances'][r.result['instance_id']];d=equip.items.definition(self.r,key)
   for stat,low,high,step in d.stat_ranges:self.assertTrue(low<=row['stats'][stat]<=high and (row['stats'][stat]-low)%step==0)
   if old:self.assertEqual(old[1],after.domains['equipment']['instances'][old[0]])
   old=(r.result['instance_id'],row)
 def test_craft_requires_currency_but_personal_bag_has_no_capacity(self):
  self.create({'ingot':15,'thorn_boar_bone':15});self.assertRejected('equipment_craft',{'equipment_id':'thorn_fang_blade'})
  self.store.close();self.store=SQLiteSave.initialize(self.root/'full.sqlite3',allowed_root=self.root);self.addCleanup(self.store.close);self.app=DungeonApplication(self.store,self.r,self.clock)
  self.create({'coins':1500,'ingot':15,'thorn_boar_bone':15,'stone':7000});self.command('equipment_craft',{'equipment_id':'thorn_fang_blade'});self.assertEqual(len(self.state().domains['equipment']['instances']),1)
 def test_craft_uses_same_manager_and_transaction_rolls_back(self):
  self.create(self.rich());self.command('automation_equipment',{'policy':{'mode':'SELL','min_quality':'rare','keep_stat':'attack_milli','min_stat':100000,'keep_upgrades':False}})
  q=self.request('equipment_craft',{'equipment_id':'thorn_fang_blade'});before=self.state()
  with patch.object(self.store,'_insert_receipt',side_effect=RuntimeError('injected failure')):
   with self.assertRaises(RuntimeError):self.app.execute(q)
  self.assertEqual(before,self.state());self.assertIsNone(self.store.receipt(self.sid,before.generation,q.request_id));r=self.app.execute(q);self.assertEqual(self.state().domains['equipment']['instances'][r.result['instance_id']]['evaluation'],'PENDING');self.settle(0);self.assertNotIn(r.result['instance_id'],self.state().domains['equipment']['instances'])
 def test_pause_rejects_all_new_mutations(self):
  self.create(self.rich());self.command('world_pause',{})
  for name,p in [('equipment_craft',{'equipment_id':'thorn_fang_blade'}),('building_upgrade',{'building_id':self.bid('garden')}),('material_overflow',{'enabled':False}),('production_start',{'building_id':self.bid('smelter'),'recipe_id':'ingot'})]:self.assertRejected(name,p)
 def test_stage_boundaries_and_only_hp_attack_bonus(self):
  self.create()
  for progress,bonus,name in [(599,0,'初期'),(600,500,'中期'),(1199,500,'中期'),(1200,1000,'后期'),(1799,1000,'后期'),(1800,1000,'后期')]:
   p={**growth.initial(self.sid),'progress':progress};view=growth.view(p,self.r,self.sid,{});hero=growth.projection(p,self.r,self.sid);self.assertEqual(view['stage']['name'],name);self.assertEqual(hero['max_hp_milli'],80000*(10000+bonus)//10000);self.assertEqual(hero['attack_milli'],10000*(10000+bonus)//10000);self.assertEqual(hero['armor_milli'],500)
 def test_pill_gain_clamps_and_keeps_legacy_progress(self):
  self.create({'pill':3},progress=1790);q=self.request('cultivation_train',{});r=self.app.execute(q);self.assertEqual(r,self.app.execute(q));self.assertEqual(self.state().domains['cultivation']['progress'],1800);self.assertEqual(self.state().domains['inventory']['holdings']['pill'],2)
 def test_breakthrough_each_missing_condition_no_charge(self):
  stock={'coins':3000,'pill':10,'breakthrough_pill':1}
  for missing in stock:
   with self.subTest(missing=missing):
    p={**growth.initial(self.sid),'progress':1800};h={**stock,missing:0}
    with self.assertRaises(growth.CultivationBlocked):growth.breakthrough(p,self.r,self.sid,h)
    self.assertEqual(p['progress'],1800);self.assertEqual(h[missing],0)
  self.create(stock,progress=1799);self.assertRejected('cultivation_breakthrough',{})
 def test_breakthrough_real_cost_replay_and_advanced_legacy_unchanged(self):
  self.create({'coins':3000,'pill':10,'breakthrough_pill':1},progress=1800);q=self.request('cultivation_breakthrough',{});r=self.app.execute(q);after=self.state();self.assertEqual(r,self.app.execute(q));self.assertEqual(after,self.state());self.assertEqual(after.domains['cultivation']['current_realm'],'realm_1');self.assertEqual(after.domains['inventory']['holdings'].get('coins',0),0);self.assertEqual(growth.projection(after.domains['cultivation'],self.r,self.sid)['max_hp_milli'],210000)
 def test_breakthrough_pill_level_gate_and_capacity(self):
  self.create({'herb':100,'ingot':20,**self.rich()});self.assign('alchemy');self.assertRejected('production_start',{'building_id':self.bid('alchemy'),'recipe_id':'breakthrough_pill'})
  for _ in range(4):self.command('building_upgrade',{'building_id':self.bid('alchemy')})
  self.command('production_start',{'building_id':self.bid('alchemy'),'recipe_id':'breakthrough_pill'});self.settle(600000);self.assertEqual(self.state().domains['inventory']['holdings']['breakthrough_pill'],1)

 def test_new_commands_reject_stale_pending_and_untrusted_payload(self):
  self.create(self.rich());q=self.request('equipment_craft',{'equipment_id':'thorn_fang_blade'});self.command('material_overflow',{'enabled':False})
  with self.assertRaises(ConflictError):self.app.execute(q)
  self.assertRejected('equipment_craft',{'equipment_id':'thorn_fang_blade','coins':0})
  self.assertRejected('building_upgrade',{'building_id':self.bid('garden'),'target_level':10})
  self.assertRejected('equipment_craft',{'equipment_id':'basic_left'})
 def test_max_building_rejects_actual_command(self):
  d=thaw_json(self.s.domains);bid=next(k for k,v in d['sect']['buildings'].items() if v['definition_id']=='garden');d['sect']['buildings'][bid]['level']=10;d['inventory']['holdings']=self.rich();self.app.create(replace(self.s,domains=d));self.assertRejected('building_upgrade',{'building_id':bid})
 def test_old_random_equipment_and_progress_are_preserved(self):
  s,identity=equip.acquire(self.s,self.r,'thorn_fang_blade','old-saved-roll',roll_version='thorn-roll-v2');d=thaw_json(s.domains);d['cultivation']={**growth.initial(self.sid),'progress':1199};d['automation'].pop('material_overflow');d['automation'].pop('overflow_log');d['automation']['production']={};d['sect']['buildings']={k:v for k,v in d['sect']['buildings'].items() if v['definition_id']!='smelter'};self.app.create(replace(s,domains=d));before=self.state();v=self.app.view(self.sid);self.assertEqual(self.state(),before);self.assertEqual(v['cultivation']['stage']['name'],'中期');self.command('material_overflow',{'enabled':True});after=self.state();self.assertEqual(before.domains['equipment'],after.domains['equipment']);self.assertEqual(after.domains['cultivation']['progress'],1199)
 def test_atomic_breakthrough_each_missing_cost(self):
  for index,missing in enumerate(['coins','pill','breakthrough_pill']):
   with self.subTest(missing=missing):
    if index:
     self.store.close();self.store=SQLiteSave.initialize(self.root/f'missing-{index}.sqlite3',allowed_root=self.root);self.addCleanup(self.store.close);self.app=DungeonApplication(self.store,self.r,self.clock)
    stock={'coins':3000,'pill':10,'breakthrough_pill':1};stock[missing]=0;self.create(stock,progress=1800);self.assertRejected('cultivation_breakthrough',{})
 def test_craft_missing_material_does_not_deduct_money(self):
  self.create({'coins':1500,'ingot':15});self.assertRejected('equipment_craft',{'equipment_id':'thorn_fang_blade'})
 def test_legacy_pending_read_keeps_authoritative_continuation(self):
  self.create(legacy=True);self.command('dungeon_auto',{'enabled':True,'mode':'farm','floor':1});self.clock.advance(10000);s=self.state();self.app.settle(SettlementRequest(self.sid,s.generation,s.revision,str(uuid4()),1));pending=self.state();self.assertIsNotNone(pending.time['pending']);v=self.app.view(self.sid);self.assertEqual(v['time']['continuation']['state_fingerprint'],Continuation.for_state(pending).state_fingerprint);before=self.state();q=self.request('building_upgrade',{'building_id':self.bid('garden')})
  with self.assertRaises(ConflictError):self.app.execute(q)
  self.assertEqual(before,self.state())

 def test_rebuilt_registry_has_exact_new_costs(self):
  from src.application.sect_economy import craft_cost
  rebuilt=load_dungeons();self.assertIsNot(rebuilt,self.r)
  self.assertEqual(growth.action(rebuilt).gain,15)
  self.assertEqual(craft_cost(rebuilt,'thorn_fang_blade'),{'ingot':15,'thorn_boar_bone':15,'coins':1500})
  self.assertEqual(craft_cost(rebuilt,'thorn_king_blade'),{'ingot':60,'thorn_king_tusk':3,'thorn_king_core':3,'coins':15000})
  recipe=jobs.definition(rebuilt,'breakthrough_pill');self.assertEqual((dict(recipe.inputs),recipe.duration_ms,recipe.min_level),({'herb':60,'ingot':20},600000,5))
  self.assertEqual(dict(growth.realm(rebuilt,'realm_0').cost),{'breakthrough_pill':1,'pill':10,'coins':3000})
 def test_batch_pills_atomic_replay_and_insufficient(self):
  self.create({'pill':20},progress=599);q=self.request('cultivation_train',{'count':10});r=self.app.execute(q);after=self.state()
  self.assertEqual(after.domains['cultivation']['progress'],749);self.assertEqual(after.domains['inventory']['holdings']['pill'],10);self.assertEqual(r,self.app.execute(q));self.assertEqual(after,self.state())
  self.assertRejected('cultivation_train',{'count':11})
  for n in (0,-1,True,1.5,'10'):self.assertRejected('cultivation_train',{'count':n})
  q=self.request('cultivation_train',{'count':10})
  with patch.object(self.store,'_insert_receipt',side_effect=RuntimeError('injected failure')):
   with self.assertRaises(RuntimeError):self.app.execute(q)
  self.assertEqual(after,self.state())
  self.command('world_pause',{});self.assertRejected('cultivation_train',{'count':10})
 def test_batch_pills_stop_at_threshold_without_wasting(self):
  self.create({'pill':10},progress=1780);self.command('cultivation_train',{'count':10});s=self.state();self.assertEqual(s.domains['cultivation']['progress'],1800);self.assertEqual(s.domains['inventory']['holdings']['pill'],8);self.assertRejected('cultivation_train',{'count':1})
 def make_equipment(self,amount=3):
  s=self.s;identities=[]
  for i in range(amount):
   s,identity=equip.acquire(s,self.r,'thorn_fang_blade','batch-fixture-'+str(i),roll_version='thorn-roll-v2');identities.append(identity)
  self.s=s;self.create(self.rich());return identities
 def test_batch_equipment_sale_atomic_replay_and_protection(self):
  ids=self.make_equipment();self.command('equipment_lock',{'instance_id':ids[1],'value':True})
  self.assertRejected('equipment_sell',{'instance_ids':ids});self.command('equipment_lock',{'instance_id':ids[1],'value':False})
  self.assertRejected('equipment_sell',{'instance_ids':[ids[0],ids[0]]});self.assertRejected('equipment_sell',{'instance_ids':[]});self.assertRejected('equipment_sell',{'instance_ids':[ids[0],'unknown']})
  before=self.state();q=self.request('equipment_sell',{'instance_ids':ids})
  with patch.object(self.store,'_insert_receipt',side_effect=RuntimeError('injected failure')):
   with self.assertRaises(RuntimeError):self.app.execute(q)
  self.assertEqual(before,self.state());r=self.app.execute(q);after=self.state();self.assertEqual(r,self.app.execute(q));self.assertEqual(after,self.state());self.assertEqual(after.domains['equipment']['instances'],{});self.assertEqual(after.domains['inventory']['holdings']['coins'],before.domains['inventory']['holdings']['coins']+equip.items.definition(self.r,'thorn_fang_blade').sell_coins*3)
 def test_batch_salvage_atomic_capacity_and_pause(self):
  ids=self.make_equipment();before=self.state();self.command('equipment_salvage',{'instance_ids':ids});after=self.state();d=equip.items.definition(self.r,'thorn_fang_blade')
  for key,n in d.salvage:self.assertEqual(after.domains['inventory']['holdings'][key],before.domains['inventory']['holdings'].get(key,0)+n*3)
 def test_batch_equipment_pause_and_capacity_rejection(self):
  ids=self.make_equipment();self.command('world_pause',{});self.assertRejected('equipment_sell',{'instance_ids':ids});self.assertRejected('equipment_salvage',{'instance_ids':ids});self.command('world_resume',{})
  s=self.state();domains=thaw_json(s.domains);domains['inventory']['holdings']={'stone':7001};full=replace(s,domains=domains)
  # Capacity failure must reject the whole candidate, leaving all original instances.
  with self.assertRaises(ValidationError):equip.command(full,self.r,'equipment_salvage',{'instance_ids':ids})
  self.assertEqual(len(full.domains['equipment']['instances']),3)
 def test_work_numeric_batch_replay_and_excess_rejection(self):
  self.create();gid=next(k for k,v in self.state().domains['disciples']['groups'].items() if v['count']>=3);bid=self.bid('garden');q=self.request('work_assign',{'worker_id':gid,'building_id':bid,'count':3});r=self.app.execute(q);after=self.state();self.assertEqual(after.domains['disciples']['assignments'][gid][bid],3);self.assertEqual(r,self.app.execute(q));self.assertEqual(after,self.state());self.assertRejected('work_assign',{'worker_id':gid,'building_id':self.bid('mine'),'count':10})

 def test_batch_does_not_bypass_retired_equipment_gate(self):
  self.s,retired=equip.acquire(self.s,self.r,'basic_head','legacy-retired')
  self.s,live=equip.acquire(self.s,self.r,'thorn_fang_blade','live-item',roll_version='thorn-roll-v2');self.create(self.rich());self.assertRejected('equipment_sell',{'instance_ids':[live,retired]})

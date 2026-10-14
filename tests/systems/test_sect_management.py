import unittest,tempfile
from pathlib import Path
from dataclasses import replace
from uuid import uuid4
from unittest.mock import patch
from src.application.danding import initial_slice
from src.application.sect_management import ManagementApplication
from src.application import equipment as equip
from src.application.memory import Command
from src.application.settlement import SettlementRequest
from src.core.save.sqlite import SQLiteSave,V2_ROOT
from src.core.state.envelope import thaw_json
from src.core.time.model import Continuation
from src.core.validation import ValidationError,ConflictError
from src.data.dungeons.definitions import load_dungeons
from src.systems.sect import management
from src.systems.equipment import items
from tests.fixtures.time import ManualClock

class ManagementTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(dir=V2_ROOT/'tests');self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.db=self.root/'test.sqlite3';self.r=load_dungeons(management=True);self.clock=ManualClock();s=initial_slice(self.r,last_settled_at_ms=1000);self.sid=s.save_id
  stock=thaw_json(s.domains['inventory']);stock['holdings'].update(coins=100000,grain=1000,food=100,wood=100,stone=100,ingot=100,spirit_stone_low=100,ordinary_wood=100,spring_water=100,spirit_iron_ingot=100)
  s=replace(s,domains={**s.domains,'inventory':stock})
  with SQLiteSave.initialize(self.db,allowed_root=self.root) as st:ManagementApplication(st,self.r,self.clock).create(s)
 def app(self,store):return ManagementApplication(store,self.r,self.clock)
 def read(self):
  with SQLiteSave(self.db,allowed_root=self.root) as st:return self.app(st).query(self.sid)
 def view(self):
  with SQLiteSave(self.db,allowed_root=self.root) as st:return self.app(st).view(self.sid)
 def q(self,name,payload):
  if name in ('material_sell','sect_stone_buy','market_buy') and 'market_day' not in payload and type(payload.get('resource_id')) is str:
   from src.systems.sect import market
   state=self.read();day=market.day(state);price=market.price(self.r,self.sid,day,payload['resource_id'])
   payload={**payload,'market_day':day,'price_milli':price['sell_price_milli' if name=='material_sell' else 'buy_price_milli']}
  s=self.read();return Command(self.sid,s.generation,s.revision,str(uuid4()),name,payload)
 def offer_day(self,rid):
  from src.systems.sect import market
  state=self.read();start=market.day(state)
  for day in range(start,start+10000):
   if rid in market.offers(self.r,self.sid,day,market.eligible(state,self.r)):break
  else:self.fail('fixture could not find an offer day')
  if day!=start:self.fixture(lambda s:replace(s,time={**s.time,'sim_time_ms':day*s.time['day_length_ms']}))
 def execute(self,q):
  with SQLiteSave(self.db,allowed_root=self.root) as st:return self.app(st).execute(q)
 def cmd(self,name,p):return self.execute(self.q(name,p))
 def settle(self):
  with SQLiteSave(self.db,allowed_root=self.root) as st:
   app=self.app(st);s=app.query(self.sid);return app.settle(SettlementRequest(self.sid,s.generation,s.revision,str(uuid4()),32,Continuation.for_state(s) if s.time['pending'] else None))
 def drain(self):
  self.settle()
  for _ in range(500):
   if not self.read().time['pending']:return
   self.settle()
  self.fail('bounded fixture failed to finish')
 def test_read_defaults_and_meal_off_no_mutation(self):
  before=self.read();v=self.view();self.assertEqual(before,self.read());self.assertFalse(v['sect_services']['supply']['enabled']);self.assertEqual(v['sect_services']['housing']['reserved'],0)
 def test_recruit_real_deadline_idle_and_replay(self):
  before=self.read();gid=next(iter(before.domains['disciples']['groups']));q=self.q('sect_recruit',{'group_id':gid,'count':1});receipt=self.execute(q);started=self.read();self.assertEqual(self.execute(q),receipt);self.assertEqual(self.read(),started)
  self.assertEqual(self.view()['sect_services']['housing']['reserved'],1);self.assertEqual(started.domains['disciples'],before.domains['disciples'])
  self.clock.advance(management.config(self.r)['recruit_duration_ms']);self.drain();after=self.read();self.assertIsNone(after.domains['sect_management']['recruit']);self.assertEqual(after.domains['disciples']['groups'][gid]['count'],before.domains['disciples']['groups'][gid]['count']+1);self.assertEqual(after.domains['disciples']['assignments'],before.domains['disciples']['assignments'])
 def test_recruit_order_single_and_capacity(self):
  gid=next(iter(self.read().domains['disciples']['groups']))
  with self.assertRaises(ValidationError):self.cmd('sect_recruit',{'group_id':gid,'count':11})
  self.cmd('sect_recruit',{'group_id':gid,'count':1});before=self.read()
  with self.assertRaises(ValidationError):self.cmd('sect_recruit',{'group_id':gid,'count':1})
  self.assertEqual(before,self.read())
 def test_meal_once_reserve_and_disabled_no_penalty(self):
  before=self.read();q=self.q('sect_supply',{'enabled':True,'reserve':5});r=self.execute(q);after=self.read();people=self.view()['sect_services']['housing']['people'];self.assertEqual(before.domains['inventory']['holdings']['food']-after.domains['inventory']['holdings']['food'],people);self.assertEqual(self.execute(q),r);self.assertEqual(self.read(),after)
  self.cmd('sect_supply',{'enabled':False,'reserve':5});v=self.view()['sect_services']['supply'];self.assertFalse(v['active']);self.assertIsNone(v['wake'])
 def test_supply_shortage_preserves_stock_and_no_negative(self):
  before=self.read();self.cmd('sect_supply',{'enabled':True,'reserve':1000});after=self.read();self.assertEqual(before.domains['inventory'],after.domains['inventory']);self.assertFalse(self.view()['sect_services']['supply']['active'])
 def test_pause_allows_supply_and_recruit_start_and_reads_pure(self):
  self.cmd('world_pause',{});before=self.read();self.cmd('sect_supply',{'enabled':True,'reserve':0})
  q=self.q('sect_recruit',{'count':1});receipt=self.execute(q);after=self.read()
  self.assertTrue(after.domains['sect_management']['supply']['enabled']);self.assertIsNotNone(after.domains['sect_management']['recruit'])
  self.assertEqual(after.time,before.time);self.assertEqual(receipt,self.execute(q));self.assertEqual(after,self.read())
  self.view();self.assertEqual(after,self.read())
 def test_supply_expiry_offline_and_resume_excludes_pause(self):
  self.cmd('sect_supply',{'enabled':True,'reserve':5});self.cmd('world_pause',{});s=self.read();self.clock.advance(1000000);self.cmd('world_resume',{});self.assertEqual(self.read().time['sim_time_ms'],s.time['sim_time_ms']);self.assertEqual(self.read().domains,s.domains)
 def test_command_write_failure_rolls_back_fee_and_order(self):
  gid=next(iter(self.read().domains['disciples']['groups']));before=self.read()
  with patch.object(SQLiteSave,'commit',side_effect=RuntimeError('fixture write fault')):
   with self.assertRaises(RuntimeError):self.cmd('sect_recruit',{'group_id':gid,'count':1})
  self.assertEqual(before,self.read())

 def fixture(self,change):
  from src.core.save.codec import StoredReceipt
  with SQLiteSave(self.db,allowed_root=self.root) as st:
   with st.transaction():
    original=self.app(st).query(self.sid);changed=change(original)
    if changed==original:return
    candidate=replace(changed,revision=original.revision+1);self.app(st).foundation.validate_state(candidate)
    st.commit(original,candidate,StoredReceipt(self.sid,candidate.generation,str(uuid4()),'0'*64,candidate.revision,'command',{}))
 def rank_two(self,*,thorn=30,forge=3):
  def change(s):
   sect=thaw_json(s.domains['sect'])
   for r in sect['buildings'].values():
    if r['definition_id'] in ('house','warehouse','forge'):r['level']=forge if r['definition_id']=='forge' else 3
   inventory=thaw_json(s.domains['inventory']);inventory['holdings']['crafting_essence']=30
   return replace(s,domains={**s.domains,'sect':sect,'inventory':inventory,'dungeon':{**s.domains['dungeon'],'cleared_floor':thorn}})
  self.fixture(change)
 def test_material_sell_reserve_replay_atomic(self):
  rid='thorn_boar_bone';self.fixture(lambda s:replace(s,domains={**s.domains,'inventory':{**s.domains['inventory'],'holdings':{**s.domains['inventory']['holdings'],rid:20}}}))
  self.cmd('material_reserve',{'resource_id':rid,'quantity':12});before=self.read()
  with self.assertRaises(ValidationError):self.cmd('material_sell',{'resource_id':rid,'quantity':9})
  self.assertEqual(self.read(),before);q=self.q('material_sell',{'resource_id':rid,'quantity':8});receipt=self.execute(q);after=self.read();self.assertEqual(after.domains['inventory']['holdings'][rid],12);self.assertEqual(after.domains['inventory']['holdings']['coins'],before.domains['inventory']['holdings']['coins']+8*q.payload['price_milli']//1000);self.assertEqual(self.execute(q),receipt);self.assertEqual(after,self.read())
 def test_material_sell_commit_failure_rolls_back(self):
  rid='thorn_boar_bone';self.fixture(lambda s:replace(s,domains={**s.domains,'inventory':{**s.domains['inventory'],'holdings':{**s.domains['inventory']['holdings'],rid:2}}}));before=self.read();q=self.q('material_sell',{'resource_id':rid,'quantity':2})
  with patch.object(SQLiteSave,'commit',side_effect=RuntimeError('injected transaction failure')):
   with self.assertRaises(RuntimeError):self.execute(q)
  self.assertEqual(self.read(),before)
 def test_overflow_honors_material_reserve(self):
  from src.systems.economy.overflow import rewards
  rid='thorn_boar_bone';kept,converted=rewards({'material_overflow':True},{rid:200},self.r,{rid:10},reserves={rid:205});self.assertEqual(kept[rid],5);self.assertEqual(converted[rid],5)
 def test_ordinary_building_cost_has_no_dungeon_core(self):
  from src.systems.sect import rules
  for bid,r in self.read().domains['sect']['buildings'].items():
   if r['definition_id'] in management.config(self.r)['upgrade_costs']:
    quote=rules.quote_upgrade(self.read().domains['sect'],self.r,bid);self.assertEqual(set(quote['cost']),{'coins','wood','stone',next(iter(management.config(self.r)['building_stone_costs'][str(quote['target_level'])]))}|set(management.config(self.r)['upgrade_additional_costs'][str(quote['target_level'])]))
 def test_zero_stone_is_registered_and_read_does_not_change_save(self):
  self.fixture(lambda s:replace(s,domains={**s.domains,'inventory':{**s.domains['inventory'],'holdings':{k:v for k,v in s.domains['inventory']['holdings'].items() if k!='stone'}}}))
  before=self.read();self.assertEqual(self.view()['inventory']['stone'],{'name':'石材','quantity':0,'source_label':'宗门生产与加工','use_label':'宗门建设、日常供给或加工辅料'});self.assertEqual(before,self.read())
 def test_building_stone_stage_boundaries_and_old_levels(self):
  from src.systems.sect import rules
  before=self.read();bid=next(k for k,r in before.domains['sect']['buildings'].items() if r['definition_id']=='warehouse')
  for target,rid in [(2,'spirit_stone_low'),(3,'spirit_stone_low'),(4,'spirit_stone_mid'),(5,'spirit_stone_mid'),(6,'spirit_stone_high'),(7,'spirit_stone_high'),(8,'spirit_stone_supreme'),(9,'spirit_stone_supreme'),(10,'spirit_stone_immortal')]:
   sect=thaw_json(before.domains['sect']);sect['buildings'][bid]['level']=target-1;cost=rules.quote_upgrade(sect,self.r,bid)['cost'];self.assertEqual(cost[rid],target);self.assertEqual(set(cost),{'coins','wood','stone',rid}|set(management.config(self.r)['upgrade_additional_costs'][str(target)]));self.assertNotIn('ingot',cost)
  self.assertEqual(before,self.read())
 def test_low_stone_mining_delivers_and_higher_grades_are_trade_only(self):
  recipes=self.view()['economy']['recipes'];self.assertFalse(any(any(r['resource_id'] in ('spirit_stone_mid','spirit_stone_high','spirit_stone_supreme','spirit_stone_immortal') for r in row['outputs']) for row in recipes))
  row=next(r for r in recipes if r['recipe_id']=='sect_spirit_stone_low');bid=row['building_id'];before=self.read();self.cmd('production_start',{'building_id':bid,'recipe_id':'sect_spirit_stone_low'});job=self.read().domains['production']['jobs'][bid];self.clock.advance(job['due_ms']+1000);self.drain();self.assertGreater(self.read().domains['inventory']['holdings']['spirit_stone_low'],before.domains['inventory']['holdings']['spirit_stone_low'])
 def test_high_stone_trade_atomic_and_replay(self):
  for rid in ('spirit_stone_mid','spirit_stone_high','spirit_stone_supreme','spirit_stone_immortal'):
   if rid!='spirit_stone_mid':
    def unlock(s):
     sect=thaw_json(s.domains['sect'])
     for r in sect['buildings'].values():r['level']=max(5,r['level'])
     return replace(s,domains={**s.domains,'sect':sect,'dungeon':{**s.domains['dungeon'],'cleared_floor':100}})
    self.fixture(unlock)
   self.offer_day(rid)
   q=self.q('sect_stone_buy',{'resource_id':rid,'quantity':1});before=self.read();receipt=self.execute(q);after=self.read();self.assertEqual(after.domains['inventory']['holdings'][rid],before.domains['inventory']['holdings'].get(rid,0)+1);self.assertEqual(before.domains['inventory']['holdings']['coins']-after.domains['inventory']['holdings']['coins'],(q.payload['price_milli']+999)//1000);self.assertEqual(receipt,self.execute(q));self.assertEqual(after,self.read())
 def test_high_stone_trade_rejects_missing_coins_pause_and_invalid_item(self):
  for payload in ({'resource_id':'spirit_stone_low','quantity':1},{'resource_id':'spirit_stone_mid','quantity':0},{'resource_id':'spirit_stone_mid','quantity':101}):
   before=self.read()
   with self.assertRaises(ValidationError):self.cmd('sect_stone_buy',payload)
   self.assertEqual(before,self.read())
  self.fixture(lambda s:replace(s,domains={**s.domains,'inventory':{**s.domains['inventory'],'holdings':{**s.domains['inventory']['holdings'],'coins':1}}}));before=self.read()
  with self.assertRaises(ValidationError):self.cmd('sect_stone_buy',{'resource_id':'spirit_stone_mid','quantity':1})
  self.assertEqual(before,self.read());self.cmd('world_pause',{});before=self.read()
  with self.assertRaises(ValidationError):self.cmd('sect_stone_buy',{'resource_id':'spirit_stone_mid','quantity':1})
  self.assertEqual(before,self.read())
 def test_high_stone_trade_commit_failure_rolls_back(self):
  self.offer_day('spirit_stone_mid')
  q=self.q('sect_stone_buy',{'resource_id':'spirit_stone_mid','quantity':1});before=self.read()
  with patch.object(SQLiteSave,'commit',side_effect=RuntimeError('fixture trade commit failure')):
   with self.assertRaises(RuntimeError):self.execute(q)
  self.assertEqual(before,self.read())
 def test_high_stone_trade_full_warehouse_rolls_back_fee(self):
  self.offer_day('spirit_stone_mid')
  from src.application.sect import capacity_source
  from src.systems.inventory import holdings
  def fill(s):
   stock=thaw_json(s.domains['inventory']);stock['holdings']['stone']+=capacity_source(s,self.r)['effective']-holdings.stock_size(stock,self.r);return replace(s,domains={**s.domains,'inventory':stock})
  self.fixture(fill);before=self.read()
  with self.assertRaises(ValidationError):self.cmd('sect_stone_buy',{'resource_id':'spirit_stone_mid','quantity':1})
  self.assertEqual(before,self.read());self.assertTrue(all(row['max_quantity']==0 for row in self.view()['sect_services']['stone_trades']))
 def test_old_save_missing_stone_balances_show_zero_without_writes(self):
  self.fixture(lambda s:replace(s,domains={**s.domains,'inventory':{**s.domains['inventory'],'holdings':{k:v for k,v in s.domains['inventory']['holdings'].items() if not k.startswith('spirit_stone_')}}}))
  before=self.read();v=self.view()
  for rid in ('spirit_stone_low','spirit_stone_mid','spirit_stone_high','spirit_stone_supreme','spirit_stone_immortal'):self.assertEqual(v['inventory'][rid]['quantity'],0)
  self.assertEqual(before,self.read())
 def test_fifth_stone_grade_keeps_old_supreme_balance_and_defaults_new_grade(self):
  self.fixture(lambda s:replace(s,domains={**s.domains,'inventory':{**s.domains['inventory'],'holdings':{**s.domains['inventory']['holdings'],'spirit_stone_supreme':7}}}))
  before=self.read();v=self.view();self.assertEqual(v['inventory']['spirit_stone_supreme']['name'],'极品灵石');self.assertEqual(v['inventory']['spirit_stone_supreme']['quantity'],7);self.assertEqual(v['inventory']['spirit_stone_immortal']['name'],'仙品灵石');self.assertEqual(v['inventory']['spirit_stone_immortal']['quantity'],0);self.assertEqual(before,self.read())
 def test_added_construction_material_boundaries_and_facility_unlock_path(self):
  from src.systems.sect import rules
  before=self.read();bid=next(k for k,r in before.domains['sect']['buildings'].items() if r['definition_id']=='warehouse')
  for target in (2,3,4,5):
   sect=thaw_json(before.domains['sect']);sect['buildings'][bid]['level']=target-1;cost=rules.quote_upgrade(sect,self.r,bid)['cost'];self.assertEqual(cost['ordinary_wood'],10*target);self.assertEqual('spring_water' in cost,target>=3);self.assertEqual('spirit_iron_ingot' in cost,target>=5)
  with SQLiteSave(self.db,allowed_root=self.root) as st:quote=self.app(st).facility_quote(before,'spring')
  self.assertNotIn('spring_water',quote['cost']);self.assertNotIn('spirit_iron_ingot',quote['cost']);self.assertEqual(before,self.read())
 def test_added_construction_fee_missing_material_and_replay(self):
  bid=next(k for k,r in self.read().domains['sect']['buildings'].items() if r['definition_id']=='warehouse');self.fixture(lambda s:replace(s,domains={**s.domains,'inventory':{**s.domains['inventory'],'holdings':{k:v for k,v in s.domains['inventory']['holdings'].items() if k!='ordinary_wood'}}}));before=self.read()
  with self.assertRaises(ValidationError):self.cmd('building_upgrade',{'building_id':bid})
  self.assertEqual(before,self.read());self.fixture(lambda s:replace(s,domains={**s.domains,'inventory':{**s.domains['inventory'],'holdings':{**s.domains['inventory']['holdings'],'ordinary_wood':100}}}));before=self.read();q=self.q('building_upgrade',{'building_id':bid});receipt=self.execute(q);after=self.read();self.assertEqual(after.domains['inventory']['holdings']['ordinary_wood'],80);self.assertEqual(self.execute(q),receipt);self.assertEqual(after,self.read())
 def test_plain_wood_and_spring_water_real_harvest_and_seedless_grain(self):
  from src.systems.disciples import work
  from src.data.registry import DefinitionKey
  self.rank_two(thorn=10);self.cmd('sect_facility_build',{'building_kind':'spring'})
  def reset(s):
   d=thaw_json(s.domains['disciples']);d['assignments']={};d['commitments']={};auto=thaw_json(s.domains['automation']);auto['production']={};return replace(s,domains={**s.domains,'disciples':d,'automation':auto,'production':{'jobs':{}}})
  self.fixture(reset);gid=next(k for k,r in self.read().domains['disciples']['groups'].items() if r['definition_id']=='ordinary_gather')
  for kind,rid,recipe in [('forest','ordinary_wood','sect_ordinary_wood'),('spring','spring_water','sect_spring_water')]:
   bid=next(k for k,r in self.read().domains['sect']['buildings'].items() if r['definition_id']==kind);self.cmd('work_assign',{'worker_id':gid,'building_id':bid,'count':1});before=self.read();self.cmd('production_start',{'building_id':bid,'recipe_id':recipe});job=self.read().domains['production']['jobs'][bid];self.clock.advance(job['due_ms']+1000);self.drain();self.assertGreater(self.read().domains['inventory']['holdings'][rid],before.domains['inventory']['holdings'][rid])
  self.assertNotIn('seed_grain',dict(self.r.lookup(DefinitionKey('production','grain')).inputs))
 def test_old_save_new_building_resources_are_zero_in_pure_view(self):
  ids=('ordinary_wood','spring_water','spirit_iron_ingot');self.fixture(lambda s:replace(s,domains={**s.domains,'inventory':{**s.domains['inventory'],'holdings':{k:v for k,v in s.domains['inventory']['holdings'].items() if k not in ids}}}));before=self.read();v=self.view()
  for rid in ids:self.assertEqual(v['inventory'][rid]['quantity'],0)
  self.assertEqual(before,self.read())
 def test_facility_construction_real_inventory_and_replay(self):
  self.rank_two(thorn=10)
  for kind,recipe in (('pasture','sect_egg'),('spring','sect_fish')):
   before=self.read();q=self.q('sect_facility_build',{'building_kind':kind});r=self.execute(q);after=self.read();self.assertEqual(self.execute(q),r);self.assertEqual(self.read(),after);bid=r.result['building_id'];self.assertEqual(after.domains['sect']['buildings'][bid]['definition_id'],kind)
   self.assertTrue(any(x['recipe_id']==recipe and x['building_id']==bid for x in self.view()['economy']['recipes']))
   with self.assertRaises(ValidationError):self.cmd('sect_facility_build',{'building_kind':kind})
   self.assertLess(after.domains['inventory']['holdings']['coins'],before.domains['inventory']['holdings']['coins'])
   self.assertEqual(after.domains['inventory']['holdings']['ingot'],before.domains['inventory']['holdings']['ingot'])
 def test_cooking_supply_new_rate_and_existing_jobs_frozen(self):
  from src.systems.disciples import work
  def change(s):
   d=thaw_json(s.domains['disciples']);d['assignments']={};d['commitments']={};bid=next(k for k,r in s.domains['sect']['buildings'].items() if r['definition_id']=='canteen');gid=next(k for k,r in d['groups'].items() if r['definition_id']=='ordinary_cook');d=work.assign(d,self.r,gid,bid,1);auto=thaw_json(s.domains['automation']);auto['production']={}
   return replace(s,domains={**s.domains,'disciples':d,'production':{'jobs':{}},'automation':auto})
  self.fixture(change);s=self.read();bid=next(k for k,r in s.domains['sect']['buildings'].items() if r['definition_id']=='canteen');self.cmd('production_start',{'building_id':bid,'recipe_id':'sect_food'});before=self.read();j=before.domains['production']['jobs'][bid];self.cmd('sect_supply',{'enabled':True,'reserve':5});self.assertEqual(j,self.read().domains['production']['jobs'][bid]);self.clock.advance(j['due_ms']+1000);self.drain();food=self.read().domains['inventory']['holdings']['food'];self.cmd('production_start',{'building_id':bid,'recipe_id':'sect_food'});enhanced=self.read().domains['production']['jobs'][bid];self.assertEqual(enhanced['work_rate_milli'],j['work_rate_milli']*11500//10000);self.assertLess(enhanced['due_ms']-enhanced['started_ms'],j['due_ms']-j['started_ms']);self.cmd('sect_supply',{'enabled':False,'reserve':5});self.assertEqual(enhanced,self.read().domains['production']['jobs'][bid]);self.clock.advance(enhanced['due_ms']-enhanced['started_ms']);self.drain();self.assertGreater(self.read().domains['inventory']['holdings']['food'],food)
 def test_supply_period_actual_food_fee(self):
  self.cmd('sect_supply',{'enabled':True,'reserve':5});before=self.read();self.clock.advance(management.config(self.r)['meal_period_ms']);self.drain();after=self.read();self.assertEqual(before.domains['inventory']['holdings']['food']-after.domains['inventory']['holdings']['food'],8);self.assertEqual(sum(r['operation']=='MEAL' for r in after.domains['sect_management']['log']),2)
 def test_legacy_overcapacity_preserves_every_person(self):
  def change(s):
   d=thaw_json(s.domains['disciples']);next(iter(d['groups'].values()))['count']=40;return replace(s,domains={**s.domains,'disciples':d})
  self.fixture(change);before=self.read();h=self.view()['sect_services']['housing'];self.assertEqual(h['people'],46);self.assertEqual(h['available'],0);self.assertEqual(before,self.read())
  with self.assertRaises(ValidationError):self.cmd('sect_recruit',{'group_id':next(iter(before.domains['disciples']['groups'])),'count':1})
 def test_craft_gates_and_correct_saved_roll(self):
  cfg=management.config(self.r);key=next(iter(cfg['craft_costs']));cost=cfg['craft_costs'][key]
  self.fixture(lambda s:replace(s,domains={**s.domains,'inventory':{**s.domains['inventory'],'holdings':{**s.domains['inventory']['holdings'],**{k:max(n,100) for k,n in cost.items() if k!='coins'}}}}))
  with self.assertRaises(ValidationError):self.cmd('equipment_craft',{'equipment_id':key})
  self.rank_two(thorn=99)
  with self.assertRaises(ValidationError):self.cmd('equipment_craft',{'equipment_id':key})
  self.rank_two(thorn=100);q=self.q('equipment_craft',{'equipment_id':key});r=self.execute(q);s=self.read();row=s.domains['equipment']['instances'][r.result['instance_id']];self.assertEqual(row['roll_version'],'red_copper_mine-roll-v1');self.assertTrue(items.known_stats(row,items.definition(self.r,key)));self.assertEqual(self.execute(q),r);self.assertEqual(s,self.read())
 def test_enhancement_atomic_replay_base_unchanged_and_cap(self):
  self.rank_two(forge=5);identity=[]
  def change(s):
   s,i=equip.acquire(s,self.r,'thorn_fang_blade','unchanged-roll',roll_version='thorn-roll-v2');identity.append(i);return s
  self.fixture(change);i=identity[0];base=dict(self.read().domains['equipment']['instances'][i]['stats']);q=self.q('equipment_enhance',{'instance_id':i});r=self.execute(q);s=self.read();self.assertEqual(self.execute(q),r);self.assertEqual(s,self.read());self.assertEqual(base,dict(s.domains['equipment']['instances'][i]['stats']));self.assertEqual(items.effective_stats(s.domains['equipment']['instances'][i])['attack_milli'],base['attack_milli']+base['attack_milli']*500//10000)
  for _ in range(4):self.cmd('equipment_enhance',{'instance_id':i})
  with self.assertRaises(ValidationError):self.cmd('equipment_enhance',{'instance_id':i})
  self.assertEqual(base,dict(self.read().domains['equipment']['instances'][i]['stats']))
 def test_enhanced_battle_snapshot_survives_unequip_and_sale(self):
  from src.systems.dungeons import progress
  self.rank_two();identity=[]
  def change(s):
   s,i=equip.acquire(s,self.r,'thorn_fang_blade','snapshot-gear',roll_version='thorn-roll-v2');identity.append(i);return s
  self.fixture(change);i=identity[0];self.cmd('equipment_enhance',{'instance_id':i});self.cmd('equipment_equip',{'instance_id':i});bid=self.cmd('combat_start',{'encounter_id':progress.definition(self.r).encounters[0]}).result['combat']['battle_id'];before=self.read()
  with self.assertRaises(ValidationError):self.cmd('equipment_enhance',{'instance_id':i})
  self.assertEqual(before,self.read());self.cmd('combat_abandon',{'battle_id':bid});snapshot=self.read().domains['combat']['battle']['player_snapshot'];self.cmd('equipment_unequip',{'instance_id':i});self.cmd('equipment_sell',{'instance_id':i});self.assertEqual(snapshot,self.read().domains['combat']['battle']['player_snapshot']);self.view()
 def test_high_pills_need_dungeon_core_basic_pill_unchanged(self):
  from src.data.registry import DefinitionKey
  old=load_dungeons();self.assertEqual(self.r.lookup(DefinitionKey('production','pill')),old.lookup(DefinitionKey('production','pill')))
  for key in management.config(self.r)['pill_inputs']:
   self.assertIn('thorn_boar_bone',dict(self.r.lookup(DefinitionKey('production',key)).inputs))

 def test_invalid_payloads_fail_without_partial_writes(self):
  before=self.read()
  for name,payload in [('sect_recruit',{'group_id':[],'count':1}),('sect_recruit',{'group_id':next(iter(before.domains['disciples']['groups'])),'count':True}),('material_sell',{'resource_id':[],'quantity':1}),('material_reserve',{'resource_id':'thorn_boar_bone','quantity':-1}),('equipment_enhance',{'instance_id':[]}),('equipment_craft',{'equipment_id':[]})]:
   with self.assertRaises(ValidationError):self.cmd(name,payload)
   self.assertEqual(before,self.read())
 def test_enhancement_failed_commit_restores_fees_and_level(self):
  self.rank_two();identities=[]
  def change(s):
   s,i=equip.acquire(s,self.r,'thorn_fang_blade','rollback-enhance',roll_version='thorn-roll-v2');identities.append(i);return s
  self.fixture(change);before=self.read();q=self.q('equipment_enhance',{'instance_id':identities[0]})
  with patch.object(SQLiteSave,'commit',side_effect=RuntimeError('injected failure')):
   with self.assertRaises(RuntimeError):self.execute(q)
  self.assertEqual(before,self.read());self.execute(q);self.assertEqual(self.read().domains['equipment']['instances'][identities[0]]['enhancement']['level'],1)
 def test_recruit_delivery_failure_can_resume_without_double_person(self):
  gid=next(iter(self.read().domains['disciples']['groups']));self.cmd('sect_recruit',{'group_id':gid,'count':1});before=self.read();self.clock.advance(management.config(self.r)['recruit_duration_ms'])
  with patch.object(SQLiteSave,'commit',side_effect=RuntimeError('injected delivery failure')):
   with self.assertRaises(RuntimeError):self.settle()
  self.assertEqual(before,self.read());self.drain();after=self.read();self.assertEqual(after.domains['disciples']['groups'][gid]['count'],before.domains['disciples']['groups'][gid]['count']+1);self.assertIsNone(after.domains['sect_management']['recruit']);self.settle();self.assertEqual(self.read().domains['disciples'],after.domains['disciples'])
 def test_housing_exact_boundary_and_reserved_capacity(self):
  def change(s):
   d=thaw_json(s.domains['disciples']);next(iter(d['groups'].values()))['count']+=7;return replace(s,domains={**s.domains,'disciples':d})
  self.fixture(change);self.assertEqual(self.view()['sect_services']['housing']['available'],1);gid=next(iter(self.read().domains['disciples']['groups']));self.cmd('sect_recruit',{'group_id':gid,'count':1});self.assertEqual(self.view()['sect_services']['housing']['available'],0);self.clock.advance(management.config(self.r)['recruit_duration_ms']);self.drain();self.assertEqual(self.view()['sect_services']['housing']['people'],16);self.assertEqual(self.view()['sect_services']['housing']['available'],0)
 def test_mixed_enhanced_snapshot_and_probability_caps(self):
  from src.systems.combat import battle
  from src.systems.dungeons import progress
  from src.data.dungeons import expeditions
  s=self.read();seen=set()
  for did in expeditions.IDS:
   for row in expeditions.content(did)['equipment']:
    if row['slot'] in seen:continue
    seen.add(row['slot']);s,i=equip.acquire(s,self.r,row['id'],'mixed-enhanced',roll_version=expeditions.content(did)['loot']['roll_version']);e=thaw_json(equip.equipment(s));e['instances'][i]['enhancement']={'level':5,'bonus_bps':2500,'version':'sect-enhance-v1'};e=items.equip(e,self.r,i,False);s=replace(s,domains={**s.domains,'equipment':e})
  with SQLiteSave(self.db,allowed_root=self.root) as st:
   app=self.app(st);player=app.player_projection(s);counter=s.identity['instance_counter']+1;b=battle.start(battle.initial(),self.r,self.sid,f'{self.sid}:1:i:{counter}',progress.definition(self.r).encounters[0],player_snapshot=player);candidate=replace(s,identity={**s.identity,'instance_counter':counter},domains={**s.domains,'combat':b});app.foundation.validate_state(candidate)
   for key,cap in items.RATE_CAPS.items():self.assertLessEqual(player.get(key,0),cap)

 def test_spring_unlock_boundary_and_real_fish_delivery(self):
  before=self.read()
  with self.assertRaises(ValidationError):self.cmd('sect_facility_build',{'building_kind':'spring'})
  self.assertEqual(before,self.read());self.rank_two(thorn=10);bid=self.cmd('sect_facility_build',{'building_kind':'spring'}).result['building_id'];gid=next(iter(self.read().domains['disciples']['groups']));self.cmd('sect_recruit',{'group_id':gid,'count':1});self.clock.advance(management.config(self.r)['recruit_duration_ms']);self.drain();self.cmd('work_assign',{'worker_id':gid,'building_id':bid,'count':1});before=self.read();self.cmd('production_start',{'building_id':bid,'recipe_id':'sect_fish'});self.assertEqual(before.domains['inventory']['holdings']['grain']-self.read().domains['inventory']['holdings']['grain'],3);j=self.read().domains['production']['jobs'][bid];self.clock.advance(j['due_ms']-j['started_ms']);self.drain();self.assertEqual(self.read().domains['inventory']['holdings']['fish'],2);self.assertEqual(self.read().domains['production']['jobs'][bid]['status'],'COMPLETE')

"""Phase16 economic invariants on isolated Save fixtures, never live grants."""
from src.core.time.config import OFFLINE_CAP_MS
import unittest,tempfile
from pathlib import Path
from contextlib import contextmanager
from uuid import uuid4
from dataclasses import replace
from src.application.economy import EconomyApplication
from src.data.economy.definitions import load_economy
from src.application.danding import initial_slice
from src.application.memory import Command
from src.application.settlement import SettlementRequest
from src.core.save.sqlite import SQLiteSave,V2_ROOT
from src.core.time.model import Continuation
from src.core.validation import ValidationError,ConflictError
from tests.fixtures.time import ManualClock

class EconomyFixture:
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(dir=V2_ROOT/'.tmp');self.root=Path(self.temp.name);self.path=self.root/'economy.sqlite3';self.registry=load_economy();self.clock=ManualClock(1000)
  s=initial_slice(self.registry,last_settled_at_ms=1000);self.save=s.save_id
  with SQLiteSave.initialize(self.path,allowed_root=self.root) as store:EconomyApplication(store,self.registry,self.clock).create(s)
 def tearDown(self):self.temp.cleanup()
 @contextmanager
 def application(self):
  with SQLiteSave(self.path,allowed_root=self.root) as store:yield EconomyApplication(store,self.registry,self.clock)
 def state(self):
  with self.application() as a:return a.query(self.save)
 def view(self):
  with self.application() as a:return a.view(self.save)
 def q(self,name,payload=None):
  s=self.state();return Command(self.save,s.generation,s.revision,str(uuid4()),name,payload or {})
 def execute(self,q):
  with self.application() as a:return a.execute(q)
 def command(self,name,payload=None):return self.execute(self.q(name,payload))
 def building(self,kind):return next(k for k,v in self.state().domains['sect']['buildings'].items() if v['definition_id']==kind)
 def group(self,kind):return next(k for k,v in self.state().domains['disciples']['groups'].items() if v['definition_id']==kind)
 def assign(self,kind,group='ordinary_gather'):
  self.command('work_assign',{'building_id':self.building(kind),'worker_id':self.group(group),'count':1})
 def start(self,recipe,kind):return self.command('production_start',{'building_id':self.building(kind),'recipe_id':recipe})
 def settle(self,budget=32):
  with self.application() as a:
   s=a.query(self.save);return a.settle(SettlementRequest(self.save,s.generation,s.revision,str(uuid4()),budget,Continuation.for_state(s) if s.time['pending'] else None))
 def auto(self,kind,recipe,target=12,reserves=None,maximum=100):
  return self.command('automation_production',{'building_id':self.building(kind),'policy':{'enabled':True,'recipe_id':recipe,'target':target,'reserves':reserves or {},'max_consumption':maximum}})
 def finish_pending(self,budget=32):
  for _ in range(100):
   r=self.settle(budget)
   if r.result.status=='COMPLETE':return r
  self.fail('bounded schedule did not converge')

class EconomyTests(EconomyFixture,unittest.TestCase):
 def test_real_herb_source_without_seed(self):
  self.assign('garden','ordinary_farm');self.start('herb','garden');self.clock.advance(30000);self.settle();self.assertEqual(self.state().domains['inventory']['holdings']['herb'],33)
 def test_ore_and_wood_share_workforce_and_inventory(self):
  for kind,r in [('mine','ore'),('forest','wood')]:self.assign(kind);self.start(r,kind)
  self.clock.advance(30000);self.settle();p=self.state().domains['inventory']['holdings'];self.assertEqual((p['ore'],p['wood']),(3,3));self.assertEqual(len(self.state().domains['disciples']['commitments']),0)
 def test_workers_required(self):
  s=self.state()
  with self.assertRaises(ValidationError):self.start('ore','mine')
  self.assertEqual(self.state(),s)
 def test_no_client_workers_or_unlocks(self):
  self.assign('mine');s=self.state()
  with self.assertRaises(ValidationError):self.command('production_start',{'building_id':self.building('mine'),'recipe_id':'ore','workers':99})
  self.assertEqual(self.state(),s)
 def test_job_start_replay_and_no_duplicate_active(self):
  self.assign('mine');q=self.q('production_start',{'building_id':self.building('mine'),'recipe_id':'ore'});r=self.execute(q);s=self.state();self.assertEqual(self.execute(q),r);self.assertEqual(self.state(),s)
  with self.assertRaises(ConflictError):self.start('ore','mine')
 def test_completion_once_across_reopen(self):
  self.assign('mine');self.start('ore','mine');self.clock.advance(30000);self.settle();s=self.state();self.settle();self.assertEqual(self.state().domains['inventory'],s.domains['inventory'])
 def test_pause_freezes_then_resumes(self):
  self.assign('garden','ordinary_farm');self.start('herb','garden');self.clock.advance(10000);self.command('world_pause');s=self.state();self.clock.advance(100000);self.assertEqual(self.state().time,s.time)
  with self.assertRaises(ValidationError):self.settle()
  self.command('world_resume');self.clock.advance(20000);self.settle();self.assertEqual(self.state().domains['inventory']['holdings']['herb'],33)
 def test_offline_job_recovers(self):
  self.assign('forest');self.start('wood','forest');self.clock.advance(3600000);self.settle();self.assertEqual(self.state().domains['inventory']['holdings']['wood'],3)
 def test_garden_to_alchemy_consumes_real_herb(self):
  self.assign('garden','ordinary_farm');self.start('herb','garden');self.clock.advance(30000);self.settle();b=self.building('alchemy');self.command('alchemy_start',{'building_id':b,'recipe_id':'pill'});self.assertEqual(self.state().domains['inventory']['holdings']['herb'],28);self.clock.advance(30000);self.settle();self.assertEqual(self.view()['holdings']['pill']['quantity'],1)
 def test_automation_defaults_off(self):self.assertEqual(self.state().domains['automation']['production'],{});self.assertEqual(self.state().domains['automation']['equipment']['mode'],'OFF')
 def test_auto_offline_ore_stops_at_target(self):
  self.assign('mine');self.auto('mine','ore');self.settle();self.clock.advance(3600000);self.finish_pending();self.assertEqual(self.state().domains['inventory']['holdings']['ore'],12)
 def test_bounded_pending_resume_budget_one(self):
  self.assign('forest');self.auto('forest','wood',target=15);self.settle();self.clock.advance(3600000);r=self.settle(1);self.assertEqual(r.result.status,'PENDING');self.assertEqual(len(r.result.processed_events),1);self.finish_pending(1);self.assertEqual(self.state().domains['inventory']['holdings']['wood'],15)
 def test_legacy_reserve_does_not_block_threshold_production(self):
  self.auto('alchemy','pill',target=10,reserves={'herb':25},maximum=5);self.settle();self.clock.advance(300000);self.finish_pending();self.assertEqual(self.state().domains['inventory']['holdings']['pill'],6);self.assertEqual(self.state().domains['inventory']['holdings'].get('herb',0),0)
 def test_legacy_consumption_limit_does_not_block_threshold_production(self):
  self.auto('alchemy','pill',target=10,maximum=4);self.settle();self.clock.advance(300000);self.finish_pending();self.assertEqual(self.state().domains['inventory']['holdings']['pill'],6)
 def test_threshold_only_policy_restarts_after_stock_falls(self):
  from src.core.state.envelope import thaw_json
  self.assign('mine');bid=self.building('mine')
  self.command('automation_production',{'building_id':bid,'policy':{'enabled':True,'recipe_id':'ore','target':6}})
  self.settle();self.clock.advance(120000);self.finish_pending()
  self.assertEqual(self.state().domains['inventory']['holdings']['ore'],6)
  with self.application() as a:
   s=a.query(self.save);domains=thaw_json(s.domains);domains['inventory']['holdings']['ore']=3
   restarted=a.engine.dispatch(replace(s,domains=domains))
   self.assertEqual(restarted.domains['production']['jobs'][bid]['status'],'WORKING')
   self.assertEqual(restarted.domains['inventory']['holdings']['ore'],3)
 def test_configure_then_assign_starts_production(self):
  self.auto('mine','ore',target=6);self.settle()
  self.assertFalse(self.state().domains['production']['jobs'])
  self.assign('mine');self.settle()
  self.assertEqual(self.state().domains['production']['jobs'][self.building('mine')]['status'],'WORKING')
 def test_auto_missing_workers_waits(self):
  self.auto('mine','ore');self.clock.advance(100000);self.settle();self.assertNotIn('ore',self.state().domains['inventory']['holdings']);self.assertFalse(self.state().domains['production']['jobs'])
 def test_auto_pause_offline_no_catchup(self):
  self.assign('mine');self.auto('mine','ore');self.settle();self.clock.advance(10000);self.command('world_pause');before=self.state();self.clock.advance(3600000);self.assertEqual(self.state(),before);self.command('world_resume');self.clock.advance(20000);self.finish_pending();self.assertEqual(self.state().domains['inventory']['holdings']['ore'],3)
 def test_target_and_shared_assignment_policy_validation(self):
  for bad in (0,10001,True):
   with self.assertRaises(ValidationError):self.auto('mine','ore',target=bad)
  with self.assertRaises(ValidationError):self.auto('garden','ore')
 def test_policy_idempotency_restart(self):
  p={'building_id':self.building('mine'),'policy':{'enabled':True,'recipe_id':'ore','target':12,'reserves':{},'max_consumption':0}};q=self.q('automation_production',p);r=self.execute(q);before=self.state();self.assertEqual(self.execute(q),r);self.assertEqual(self.state(),before)
 def test_auto_running_offline_cap_unchanged(self):
  self.assign('mine');self.auto('mine','ore',target=10000);self.settle();self.clock.advance(100*3600000);r=self.settle(1);self.assertEqual(r.result.accepted_ms,OFFLINE_CAP_MS);self.assertEqual(r.result.discarded_ms,100*3600000-OFFLINE_CAP_MS)

 def test_stale_generation_revision_production_rejected(self):
  from dataclasses import replace
  self.assign('mine');q=self.q('production_start',{'building_id':self.building('mine'),'recipe_id':'ore'});self.command('world_pause');self.command('world_resume');before=self.state()
  with self.assertRaises(ConflictError):self.execute(q)
  with self.assertRaises(ConflictError):self.execute(replace(q,generation=2))
  self.assertEqual(self.state(),before)
 def test_auto_disable_does_not_cancel_real_active_job(self):
  self.assign('mine');self.auto('mine','ore');self.settle();self.command('automation_production',{'building_id':self.building('mine'),'policy':{'enabled':False,'recipe_id':'ore','target':12,'reserves':{},'max_consumption':0}});self.clock.advance(3600000);self.finish_pending();self.assertEqual(self.state().domains['inventory']['holdings']['ore'],3)
 def test_simultaneous_sources_release_workforce_once(self):
  self.assign('garden','ordinary_farm');self.assign('mine');self.assign('forest');self.auto('garden','herb',target=36);self.auto('mine','ore',target=6);self.auto('forest','wood',target=6);self.settle();self.clock.advance(300000);self.finish_pending(1);s=self.state();self.assertEqual((s.domains['inventory']['holdings']['herb'],s.domains['inventory']['holdings']['ore'],s.domains['inventory']['holdings']['wood']),(36,6,6));self.assertFalse(s.domains['disciples']['commitments'])
 def test_output_reservation_at_admission(self):
  from src.systems.inventory import holdings
  self.assign('mine');capacity=self.view()['capacity']['effective'];used=holdings.stock_size(self.state().domains['inventory'],self.registry);self.command('inventory_grant',{'amounts':{'herb':capacity-used-2}});before=self.state()
  with self.assertRaises(ValidationError):self.start('ore','mine')
  self.assertEqual(self.state(),before)
 def test_gather_full_bag_waiting_no_discard_or_repeat(self):
  from src.systems.inventory import holdings
  self.assign('mine');self.start('ore','mine');capacity=self.view()['capacity']['effective'];used=holdings.stock_size(self.state().domains['inventory'],self.registry);self.command('inventory_grant',{'amounts':{'herb':capacity-used}});self.clock.advance(30000);self.settle();self.assertEqual(self.state().domains['production']['jobs'][self.building('mine')]['status'],'OUTPUT_READY');self.assertNotIn('ore',self.state().domains['inventory']['holdings']);self.command('inventory_consume',{'amounts':{'herb':3}});self.settle();self.settle();self.assertEqual(self.state().domains['inventory']['holdings']['ore'],3)
 def test_split_vs_merged_offline_same_economic_result(self):
  # Clone only this isolated fixture into another isolated SQLite, never the live Save.
  from src.application.economy import EconomyApplication
  self.assign('mine');self.auto('mine','ore',target=18);self.settle();start=self.state();other=self.root/'comparison.sqlite3'
  with SQLiteSave.initialize(other,allowed_root=self.root) as store:EconomyApplication(store,self.registry,self.clock).create(start)
  self.clock.advance(600000);self.finish_pending(1)
  with SQLiteSave(other,allowed_root=self.root) as store:
   app=EconomyApplication(store,self.registry,self.clock)
   for _ in range(50):
    s=app.query(self.save);r=app.settle(SettlementRequest(self.save,s.generation,s.revision,str(uuid4()),32,Continuation.for_state(s) if s.time['pending'] else None))
    if r.result.status=='COMPLETE':break
   other_state=app.query(self.save)
  own=self.state()
  # Report completion revisions differ with chunking; all original domains remain equal.
  self.assertEqual({k:v for k,v in own.domains.items() if k!='offline_reports'},{k:v for k,v in other_state.domains.items() if k!='offline_reports'});self.assertEqual(own.time,other_state.time);self.assertEqual(own.identity,other_state.identity)

if __name__=='__main__':unittest.main()

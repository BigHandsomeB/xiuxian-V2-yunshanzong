"""Real Growth/Inventory/Combat transactions in isolated V2 fixtures; no live supplies."""
import json,tempfile,unittest,subprocess,sys
from pathlib import Path
from dataclasses import replace
from contextlib import contextmanager
from unittest.mock import patch
from uuid import uuid4
from src.application.cultivation import CultivationApplication
from src.application.cultivation_upgrade import upgrade
from src.application.game import GameApplication
from src.application.memory import Command
from src.application.danding import initial_slice,worker,target
from src.application.settlement import SettlementRequest
from src.data.cultivation.definitions import load_cultivation
from src.data.combat.definitions import load_combat
from src.data.registry import DefinitionKey
from src.core.save.sqlite import SQLiteSave,V2_ROOT
from src.core.save.codec import PersistenceError,StoredReceipt
from src.core.state.envelope import thaw_json,freeze_json
from src.core.validation import ValidationError,ConflictError,NotFoundError
from src.systems.cultivation import growth
from src.systems.inventory import operations
from tests.fixtures.time import ManualClock

class CultivationTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(dir=V2_ROOT/'.tmp');self.root=Path(self.temp.name);self.path=self.root/'growth.sqlite3';self.registry=load_cultivation();self.clock=ManualClock(1000)
  s=initial_slice(self.registry,last_settled_at_ms=1000);inv,_=operations.grant(s.domains['inventory'],self.registry,{'pill':26,'coins':80},capacity=1000);s=replace(s,domains={**s.domains,'inventory':inv});self.save=s.save_id
  with SQLiteSave.initialize(self.path,allowed_root=self.root) as store:CultivationApplication(store,self.registry,self.clock).create(s)
 def tearDown(self):self.temp.cleanup()
 @contextmanager
 def application(self):
  with SQLiteSave(self.path,allowed_root=self.root) as store:yield CultivationApplication(store,self.registry,self.clock)
 def state_now(self):
  with self.application() as a:return a.query(self.save)
 def view(self):
  with self.application() as a:return thaw_json(a.view(self.save))
 def command(self,name,payload=None,**extra):
  s=self.state_now();k=dict(save_id=self.save,generation=s.generation,expected_revision=s.revision,request_id=str(uuid4()),name=name,payload=payload or {});k.update(extra);return Command(**k)
 def execute(self,q):
  with self.application() as a:return a.execute(q)
 def train(self):return self.execute(self.command('cultivation_train'))
 def full(self):
  for _ in range(23):self.train()
 def breakthrough(self):return self.execute(self.command('cultivation_breakthrough'))
 def start(self):return self.execute(self.command('combat_start',{'encounter_id':'thorn_first'})).result['combat']['battle_id']
 def test_realm_and_action_validation(self):
  original=json.loads((V2_ROOT/'src/data/cultivation/content.json').read_text())
  changes=[lambda p:p['realms'][0].update(threshold=-1),lambda p:p['realms'][0].update(index=True),lambda p:p['realms'][0].update(next_realm_id='missing'),lambda p:p['realms'][1].update(next_realm_id='realm_0'),lambda p:p['action'].update(quantity=2),lambda p:p['action'].update(quantity=True),lambda p:p['action'].update(required_item_id='cultivation_pill'),lambda p:p['action'].update(gain=0)]
  for change in changes:
   p=json.loads(json.dumps(original));change(p)
   with self.assertRaises((ValidationError,NotFoundError)):load_cultivation(json.dumps(p))
  with self.assertRaises(ValidationError):load_cultivation('{"schema_version":NaN}')
 def test_exact_two_realms_and_existing_pill_definition(self):
  old=load_combat()
  for k,d in old._definitions.items():self.assertEqual(self.registry.lookup(k),d)
  self.assertTrue(self.registry.contains(DefinitionKey('resources','pill')));self.assertFalse(self.registry.contains(DefinitionKey('resources','cultivation_pill')))
  self.assertEqual(growth.realm(self.registry,'realm_0').threshold,1800);self.assertFalse(self.registry.contains(DefinitionKey('realms','realm_2')))
 def test_initialization_view_is_pure_and_no_clock(self):
  before=self.state_now()
  with self.application() as a,patch.object(self.clock,'now_ms',side_effect=AssertionError('no time growth')):
   v=a.view(self.save)['cultivation'];self.assertEqual((v['realm_name'],v['progress'],v['pill']['quantity']),('炼气',0,26));self.assertEqual(v['threshold'],1800)
  self.assertEqual(self.state_now(),before);self.assertNotIn('cultivation',before.domains)
 def test_use_one_pill_real_progress_and_inventory(self):
  self.train();v=self.view();self.assertEqual(v['cultivation']['progress'],80);self.assertEqual(v['holdings']['pill']['quantity'],25);self.assertEqual(v['cultivation']['growth_revision'],1)
 def test_unbroken_training_does_not_change_combat_stats(self):
  before=self.view()['cultivation']['combat_projection'];self.train();self.assertEqual(self.view()['cultivation']['combat_projection'],before)
 def test_pill_replay_consumes_once(self):
  q=self.command('cultivation_train');r=self.execute(q);s=self.state_now();self.assertEqual(self.execute(q),r);self.assertEqual(self.state_now(),s)
 def test_old_revision_cannot_consume(self):
  a=self.command('cultivation_train');b=self.command('cultivation_train');self.execute(a);s=self.state_now()
  with self.assertRaises(ConflictError):self.execute(b)
  self.assertEqual(self.state_now(),s)
 def test_old_generation_rejected(self):
  q=self.command('cultivation_train',generation=2);s=self.state_now()
  with self.assertRaises(ConflictError):self.execute(q)
  self.assertEqual(self.state_now(),s)
 def test_changed_request_intent_rejected(self):
  q=self.command('cultivation_train');self.execute(q)
  with self.assertRaises(ConflictError):self.execute(self.command('cultivation_breakthrough',request_id=q.request_id))
 def test_no_client_quantity_gain_or_realm(self):
  s=self.state_now()
  for p in [{'quantity':10},{'gain':9999},{'realm':'realm_1'}]:
   with self.assertRaises(ValidationError):self.execute(self.command('cultivation_train',p))
  self.assertEqual(self.state_now(),s)
 def test_missing_pill_rejected_without_mutation(self):
  self.execute(self.command('inventory_consume',{'amounts':{'pill':26}}));s=self.state_now()
  with self.assertRaises(growth.CultivationBlocked):self.train()
  self.assertEqual(self.state_now(),s);self.assertFalse(self.view()['cultivation']['can_use_pill'])
 def test_threshold_clamp_and_full_no_consume(self):
  self.full();v=self.view()['cultivation'];self.assertEqual(v['progress'],1800);self.assertEqual(v['pill']['quantity'],3);self.assertEqual(v['status'],'BREAKTHROUGH_AVAILABLE')
  s=self.state_now()
  with self.assertRaises(growth.CultivationBlocked):self.train()
  self.assertEqual(self.state_now(),s)
 def test_last_pill_reports_actual_clamped_gain(self):
  for _ in range(22):self.train()
  r=self.train();self.assertEqual(r.result['events'][1]['amount'],40);self.assertTrue(any(e['kind']=='breakthrough_available' for e in r.result['events']))
 def test_below_threshold_cannot_break(self):
  s=self.state_now()
  with self.assertRaises(growth.CultivationBlocked):self.breakthrough()
  self.assertEqual(self.state_now(),s)
 def test_breakthrough_materials_checked(self):
  self.full();self.execute(self.command('inventory_consume',{'amounts':{'coins':1}}));s=self.state_now()
  with self.assertRaises(growth.CultivationBlocked):self.breakthrough()
  self.assertEqual(self.state_now(),s);self.assertFalse(self.view()['cultivation']['can_breakthrough'])
 def test_breakthrough_pill_materials_checked(self):
  self.full();self.execute(self.command('inventory_consume',{'amounts':{'pill':1}}));s=self.state_now()
  with self.assertRaises(growth.CultivationBlocked):self.breakthrough()
  self.assertEqual(self.state_now(),s)
 def test_breakthrough_real_realm_reset_and_materials(self):
  self.full();self.assertTrue(self.view()['cultivation']['can_breakthrough']);self.breakthrough();v=self.view();self.assertEqual((v['cultivation']['realm_name'],v['cultivation']['progress'],v['cultivation']['growth_revision']),('筑基',0,24));self.assertNotIn('pill',v['holdings']);self.assertNotIn('coins',v['holdings'])
 def test_breakthrough_replay_once(self):
  self.full();q=self.command('cultivation_breakthrough');r=self.execute(q);s=self.state_now();self.assertEqual(self.execute(q),r);self.assertEqual(self.state_now(),s)
 def test_max_phase_rejects_new_breakthrough_and_training(self):
  self.full();self.breakthrough();s=self.state_now()
  for fn in (self.breakthrough,self.train):
   with self.assertRaises(growth.CultivationBlocked):fn()
  self.assertEqual(self.state_now(),s);v=self.view()['cultivation'];self.assertEqual(v['status'],'MAX_FOR_PHASE');self.assertIsNone(v['next_realm'])
 def test_stable_player_identity_and_no_extra_player_authority(self):
  before=self.view()['cultivation']['player']['id'];self.full();self.breakthrough();self.assertEqual(self.view()['cultivation']['player']['id'],before);self.assertNotIn('player',self.state_now().domains)
 def test_growth_stat_projection_before_and_after(self):
  self.assertEqual(self.view()['cultivation']['combat_projection'],{'max_hp':80,'attack':10,'armor':.5});self.full();r=self.breakthrough();self.assertEqual(r.result['stats_after'],{'max_hp':210,'attack':26,'armor':1});self.assertEqual(self.view()['cultivation']['combat_projection'],r.result['stats_after'])
 def test_new_battle_reads_projection_and_damage(self):
  self.full();self.breakthrough();bid=self.start();v=self.view()['combat'];self.assertEqual((v['player']['max_hp'],v['player']['attack'],v['player']['armor']),(210,26,1));self.execute(self.command('combat_attack',{'battle_id':bid}));v=self.view()['combat'];self.assertEqual((v['player']['hp'],v['enemy']['hp']),(205,9));self.assertEqual(v['latest_events'][1]['formula_damage'],26)
 def test_upgraded_combat_reward_unchanged(self):
  self.full();self.breakthrough();bid=self.start()
  for _ in range(2):self.execute(self.command('combat_attack',{'battle_id':bid}))
  self.execute(self.command('combat_reward',{'battle_id':bid}));v=self.view();self.assertEqual(v['holdings']['coins']['quantity'],3);self.assertEqual(v['holdings']['dewleaf']['quantity'],1)
 def test_active_battle_denies_pill(self):
  self.start();s=self.state_now()
  with self.assertRaises(growth.CultivationBlocked):self.train()
  self.assertEqual(self.state_now(),s);self.assertEqual(self.view()['cultivation']['blocking_reasons']['train'][0]['code'],'ACTIVE_BATTLE')
 def test_active_battle_denies_breakthrough(self):
  self.full();bid=self.start();s=self.state_now()
  with self.assertRaises(growth.CultivationBlocked):self.breakthrough()
  self.assertEqual(self.state_now(),s);self.assertEqual(self.view()['combat']['player']['max_hp'],80)
  self.execute(self.command('combat_abandon',{'battle_id':bid}));self.breakthrough();self.assertEqual(self.view()['combat']['player']['max_hp'],80);self.assertEqual(self.view()['cultivation']['combat_projection']['max_hp'],210)
 def test_abandon_then_growth_allowed(self):
  bid=self.start();self.execute(self.command('combat_abandon',{'battle_id':bid}));self.train();self.assertEqual(self.view()['cultivation']['progress'],80)
 def test_completed_battle_then_growth_allowed(self):
  bid=self.start()
  for _ in range(4):self.execute(self.command('combat_attack',{'battle_id':bid}))
  self.train();self.assertEqual(self.view()['cultivation']['progress'],80)
 def test_inventory_failure_rolls_back_growth(self):
  q=self.command('cultivation_train');s=self.state_now()
  with patch('src.application.cultivation.operations.consume',side_effect=ValidationError('inventory failure')):
   with self.assertRaises(ValidationError):self.execute(q)
  self.assertEqual(self.state_now(),s);self.execute(q);self.assertEqual(self.view()['cultivation']['progress'],80)
 def test_growth_validation_failure_rolls_back_inventory(self):
  q=self.command('cultivation_train');s=self.state_now()
  with patch('src.application.cultivation.validate_growth',side_effect=lambda state,reg: (_ for _ in ()).throw(ValidationError('candidate rejection')) if 'cultivation' in state.domains else state):
   with self.assertRaises(ValidationError):self.execute(q)
  self.assertEqual(self.state_now(),s)
 def test_post_write_failure_rolls_back_both_and_receipt(self):
  q=self.command('cultivation_train');s=self.state_now();original=SQLiteSave.commit
  def fail(store,*args):original(store,*args);raise PersistenceError('failure after write')
  with patch.object(SQLiteSave,'commit',fail):
   with self.assertRaises(PersistenceError):self.execute(q)
  self.assertEqual(self.state_now(),s)
  with self.application() as a:self.assertIsNone(a.store.receipt(self.save,s.generation,q.request_id))
  self.execute(q);self.execute(q);self.assertEqual(self.view()['cultivation']['progress'],80)
 def test_breakthrough_write_failure_rolls_back_materials_realm_receipt(self):
  self.full();q=self.command('cultivation_breakthrough');s=self.state_now();original=SQLiteSave.commit
  def fail(store,*args):original(store,*args);raise PersistenceError('breakthrough commit failure')
  with patch.object(SQLiteSave,'commit',fail):
   with self.assertRaises(PersistenceError):self.execute(q)
  self.assertEqual(self.state_now(),s);self.execute(q);self.assertEqual(self.view()['cultivation']['realm_name'],'筑基')
 def test_alchemy_pill_immediately_usable_and_recipe_unchanged(self):
  self.execute(self.command('inventory_consume',{'amounts':{'pill':26}}));self.execute(self.command('alchemy_start',{'building_id':target(self.state_now()),'recipe_id':'pill'}));self.clock.advance(30000)
  with self.application() as a:
   s=a.query(self.save);a.settle(SettlementRequest(self.save,s.generation,s.revision,str(uuid4()),32,None))
  self.assertEqual(self.view()['cultivation']['pill']['quantity'],1);self.train();self.assertEqual(self.view()['cultivation']['progress'],80);self.assertEqual(self.view()['cultivation']['pill']['quantity'],0)
 def test_no_offline_or_query_gains(self):
  self.train();s=self.state_now();self.clock.advance(72000000)
  with self.application() as a:
   a.view(self.save);a.settle(SettlementRequest(self.save,s.generation,s.revision,str(uuid4()),32,None))
  self.assertEqual(self.state_now().domains['cultivation'],s.domains['cultivation'])
 def test_real_subprocess_restart_and_old_receipt_replay(self):
  q=self.command('cultivation_train');r=self.execute(q);script="""import json,sys
from pathlib import Path
from src.core.save.sqlite import SQLiteSave
from src.data.cultivation.definitions import load_cultivation
from src.application.cultivation import CultivationApplication
from src.application.memory import Command
from src.core.state.envelope import thaw_json
from tests.fixtures.time import ManualClock
p=Path(sys.argv[1]);q=json.loads(sys.argv[2])
with SQLiteSave(p,allowed_root=p.parent) as s:
 a=CultivationApplication(s,load_cultivation(),ManualClock(1000));a.execute(Command(**q));print(json.dumps(thaw_json(a.view(q['save_id'])['cultivation'])))
"""
  intent={'save_id':q.save_id,'generation':q.generation,'expected_revision':q.expected_revision,'request_id':q.request_id,'name':q.name,'payload':{}}
  v=json.loads(subprocess.check_output([sys.executable,'-B','-c',script,str(self.path),json.dumps(intent)],cwd=V2_ROOT));self.assertEqual((v['progress'],v['pill']['quantity']),(80,25))
 def test_breakthrough_restart_projection_consistency(self):
  self.full();q=self.command('cultivation_breakthrough');self.execute(q);s=self.state_now()
  script="""import json,sys
from pathlib import Path
from src.core.save.sqlite import SQLiteSave
from src.data.cultivation.definitions import load_cultivation
from src.application.cultivation import CultivationApplication
from src.application.memory import Command
from src.core.state.envelope import thaw_json
from tests.fixtures.time import ManualClock
p=Path(sys.argv[1]);q=json.loads(sys.argv[2])
with SQLiteSave(p,allowed_root=p.parent) as store:
 a=CultivationApplication(store,load_cultivation(),ManualClock(1000));before=a.query(q['save_id']);a.execute(Command(**q));assert a.query(q['save_id'])==before;print(json.dumps(thaw_json(a.view(q['save_id']))))
"""
  intent={'save_id':q.save_id,'generation':q.generation,'expected_revision':q.expected_revision,'request_id':q.request_id,'name':q.name,'payload':{}}
  v=json.loads(subprocess.check_output([sys.executable,'-B','-c',script,str(self.path),json.dumps(intent)],cwd=V2_ROOT));self.assertEqual(v['cultivation']['realm_name'],'筑基');self.assertEqual(v['cultivation']['progress'],0);self.assertEqual(v['cultivation']['combat_projection']['attack'],26);self.assertNotIn('pill',v['holdings']);self.assertNotIn('coins',v['holdings']);self.assertEqual(self.state_now(),s)
 def test_recovery_preserves_growth_and_inventory_and_stops_old_generation(self):
  from src.application.recovery import RecoveryApplication
  from src.core.save.recovery import RecoveryRequest
  q=self.command('cultivation_train');self.execute(q);before=self.state_now()
  with self.application() as a:
   a.checkpoint(self.save);life=RecoveryApplication(a.foundation,self.clock);p=life.inspect(self.save);self.assertEqual(life.recover(RecoveryRequest(self.save,p.current_generation,p.current_fingerprint,p.source_fingerprint,str(uuid4()),'isolated growth recovery')).status,'SUCCESS')
  self.assertEqual(self.state_now().domains,before.domains)
  with self.assertRaises(ConflictError):self.execute(q)
 def test_old_phase14_save_upgrade_preserves_active_battle_and_domains(self):
  path=self.root/'old.sqlite3';old=load_combat();s=initial_slice(old,last_settled_at_ms=1000)
  with SQLiteSave.initialize(path,allowed_root=self.root) as store:
   a=GameApplication(store,old,self.clock);a.create(s);a.execute(Command(s.save_id,1,0,str(uuid4()),'combat_start',{'encounter_id':'thorn_first'}));before=a.query(s.save_id)
   # Legacy Phase14 serialized Battle had no stat-input field.
   b=thaw_json(before.domains['combat']);b['battle'].pop('player_snapshot',None);legacy=replace(before,revision=before.revision+1,domains={**before.domains,'combat':b});
   fixture_q=Command(before.save_id,before.generation,before.revision,str(uuid4()),'test_legacy_shape',{})
   with store.transaction():store.commit(before,legacy,StoredReceipt(legacy.save_id,legacy.generation,fixture_q.request_id,fixture_q.digest(),legacy.revision,'command',{'operation':'test_legacy_shape'}))
   before=legacy
   q=Command(s.save_id,1,before.revision,str(uuid4()),'cultivation_content_upgrade',{});r=upgrade(store,self.clock,q);app=CultivationApplication(store,self.registry,self.clock);after=app.query(s.save_id)
   self.assertEqual(after.domains,before.domains);self.assertEqual(after.time,before.time);self.assertEqual(after.identity,before.identity);self.assertEqual(upgrade(store,self.clock,q),r);self.assertEqual(app.view(s.save_id)['combat']['player']['max_hp'],80);self.assertNotIn('cultivation',after.domains)
 def test_upgrade_failure_atomic(self):
  path=self.root/'old.sqlite3';old=load_combat();s=initial_slice(old,last_settled_at_ms=1000)
  with SQLiteSave.initialize(path,allowed_root=self.root) as store:
   GameApplication(store,old,self.clock).create(s);q=Command(s.save_id,1,0,str(uuid4()),'cultivation_content_upgrade',{})
   with patch.object(SQLiteSave,'commit',side_effect=PersistenceError('upgrade failure')):
    with self.assertRaises(PersistenceError):upgrade(store,self.clock,q)
   self.assertEqual(GameApplication(store,old,self.clock).query(s.save_id),s)
 def test_malformed_battle_snapshot_is_not_legacy_fallback(self):
  from src.systems.combat import battle
  self.start();partition=thaw_json(self.state_now().domains['combat'])
  for bad in (None,{}):
   candidate={**partition,'battle':{**partition['battle'],'player_snapshot':bad}}
   with self.assertRaises(ValidationError):battle.validate(candidate,self.registry,self.save)
 def test_malformed_growth_state_rejected(self):
  p=thaw_json(growth.initial(self.save))
  for change in [{'progress':-1},{'progress':1801},{'progress':True},{'player_id':'fake'},{'current_realm':'realm_2'}]:
   with self.assertRaises((ValidationError,NotFoundError)):growth.validate({**p,**change},self.registry,self.save)
if __name__=='__main__':unittest.main()

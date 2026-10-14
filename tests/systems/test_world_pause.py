"""Isolated single-clock global pause, atomicity and compatibility regressions."""
import unittest,json,subprocess,sys
from pathlib import Path
from contextlib import contextmanager
from dataclasses import replace
from unittest.mock import patch
from tests.systems import test_cultivation as f
from src.application.world import WorldApplication
from src.application.memory import Command
from src.application.settlement import SettlementRequest
from src.core.save.sqlite import SQLiteSave,V2_ROOT
from src.core.save.codec import PersistenceError
from src.core.state.envelope import thaw_json,StateEnvelope
from src.core.time import world
from src.core.time.model import plan_window
from src.core.time.config import OFFLINE_CAP_MS,DEFAULT_GAME_DAY_MS
from src.core.validation import ValidationError,ConflictError
from uuid import uuid4
class WorldTests(unittest.TestCase):
 setUp=f.CultivationTests.setUp
 tearDown=f.CultivationTests.tearDown
 state_now=f.CultivationTests.state_now
 view=f.CultivationTests.view
 command=f.CultivationTests.command
 execute=f.CultivationTests.execute
 start=f.CultivationTests.start
 @contextmanager
 def application(self):
  with SQLiteSave(self.path,allowed_root=self.root) as s:yield WorldApplication(s,self.registry,self.clock)
 def pause(self):return self.execute(self.command('world_pause'))
 def resume(self):return self.execute(self.command('world_resume'))
 def settle(self):
  s=self.state_now()
  with self.application() as a:return a.settle(SettlementRequest(self.save,s.generation,s.revision,str(uuid4()),32,None))
 def alchemy(self):
  from src.application.danding import target
  return self.execute(self.command('alchemy_start',{'building_id':target(self.state_now()),'recipe_id':'pill'}))
 def test_old_save_defaults_running_pure_query(self):
  before=self.state_now();self.assertFalse(self.view()['world']['paused']);self.assertNotIn('world_paused',before.time);self.assertEqual(self.state_now(),before)
 def test_pause_real_command(self):
  self.pause();self.assertTrue(self.state_now().time['world_paused']);self.assertTrue(self.view()['world']['paused'])
 def test_resume_command_excludes_wall_interval(self):
  self.pause();before=self.state_now();self.clock.advance(3600000);self.resume();s=self.state_now();self.assertFalse(s.time['world_paused']);self.assertEqual(s.time['sim_time_ms'],before.time['sim_time_ms']);self.assertEqual(s.time['last_settled_at_ms'],3601000)
 def test_pause_replay_safe(self):
  q=self.command('world_pause');r=self.execute(q);s=self.state_now();self.clock.advance(100000);self.assertEqual(self.execute(q),r);self.assertEqual(self.state_now(),s)
 def test_repeat_pause_new_id_no_state_or_clock_change(self):
  self.pause();s=self.state_now();self.clock.advance(100000)
  with patch.object(self.clock,'now_ms',side_effect=AssertionError('duplicate pause must not read clock')):self.pause()
  self.assertEqual(self.state_now(),s)
 def test_resume_replay_safe(self):
  self.pause();q=self.command('world_resume');r=self.execute(q);s=self.state_now();self.clock.advance(100000);self.assertEqual(self.execute(q),r);self.assertEqual(self.state_now(),s)
 def test_repeat_resume_new_id_does_not_skip_running_time(self):
  self.pause();self.resume();s=self.state_now();self.clock.advance(10000)
  with patch.object(self.clock,'now_ms',side_effect=AssertionError('duplicate resume')):self.resume()
  self.assertEqual(self.state_now(),s);self.settle();self.assertEqual(self.state_now().time['sim_time_ms'],10000)
 def test_stale_pause_rejected(self):
  q=self.command('world_pause');self.execute(self.command('cultivation_train'))
  with self.assertRaises(ConflictError):self.execute(q)
 def test_old_generation_resume_rejected(self):
  self.pause()
  with self.assertRaises(ConflictError):self.execute(self.command('world_resume',generation=2))
 def test_changed_intent_same_request_rejected(self):
  q=self.command('world_pause');self.execute(q)
  with self.assertRaises(ConflictError):self.execute(self.command('world_resume',request_id=q.request_id))
 def test_invalid_world_payload_no_state_change(self):
  s=self.state_now()
  with self.assertRaises(ValidationError):self.execute(self.command('world_pause',{'now_ms':999}))
  self.assertEqual(self.state_now(),s)
 def test_pause_settles_only_pre_pause_elapsed(self):
  self.clock.advance(5000);self.pause();self.assertEqual(self.state_now().time['sim_time_ms'],5000)
 def test_pause_frozen_alchemy_remaining20(self):
  self.alchemy();self.clock.advance(10000);self.pause();self.assertEqual(self.view()['alchemy']['current']['remaining_ms'],20000);before=self.state_now();self.clock.advance(3600000);self.assertEqual(self.view()['alchemy']['current']['remaining_ms'],20000);self.assertEqual(self.state_now(),before)
 def test_paused_settlement_rejected_no_production_delivery(self):
  self.alchemy();self.pause();s=self.state_now();self.clock.advance(72000000)
  with self.assertRaises(world.WorldPaused):self.settle()
  self.assertEqual(self.state_now(),s)
 def test_resume_alchemy_remaining_then_one_delivery(self):
  self.alchemy();self.clock.advance(10000);self.pause();self.clock.advance(3600000);self.resume();self.assertEqual(self.view()['alchemy']['current']['remaining_ms'],20000);self.clock.advance(19000);self.settle();self.assertEqual(self.view()['alchemy']['current']['remaining_ms'],1000);self.clock.advance(1000);self.settle();self.assertEqual(self.view()['holdings']['pill']['quantity'],27);self.settle();self.assertEqual(self.view()['holdings']['pill']['quantity'],27)
 def test_paused_offline_reopen_does_not_catch_up(self):
  self.alchemy();self.pause();self.clock.advance(OFFLINE_CAP_MS*2);self.assertEqual(self.view()['alchemy']['current']['remaining_ms'],30000);self.resume();self.settle();self.assertEqual(self.view()['alchemy']['current']['remaining_ms'],30000)
 def test_running_offline_rules_unchanged(self):
  self.alchemy();self.clock.advance(OFFLINE_CAP_MS+123);r=self.settle();self.assertEqual((r.result.accepted_ms,r.result.discarded_ms),(OFFLINE_CAP_MS,123));self.assertEqual(self.view()['holdings']['pill']['quantity'],27)
 def test_day_length_unchanged_and_new_offline_cap(self):self.assertEqual((DEFAULT_GAME_DAY_MS,OFFLINE_CAP_MS),(120000,24*3600000))
 def test_time_window_paused_accepts_zero(self):
  self.pause();s=self.state_now();w=plan_window(s.time,99999999);self.assertEqual((w.accepted_ms,w.discarded_ms,w.target_sim_ms),(0,0,s.time['sim_time_ms']))
 def test_time_and_historical_foundation_commands_rejected_while_paused(self):
  self.pause();s=self.state_now()
  for name,payload in [('combat_start',{'encounter_id':'thorn_first'}),('inventory_consume',{'amounts':{'pill':1}}),('alchemy_start',{}),('work_assign',{})]:
   with self.assertRaises(world.WorldPaused):self.execute(self.command(name,payload))
  self.assertEqual(self.state_now(),s)
 def test_active_battle_preserved_and_attack_denied(self):
  bid=self.start();self.pause();s=self.state_now()
  for name in ['combat_attack','combat_abandon','combat_reward']:
   with self.assertRaises(world.WorldPaused):self.execute(self.command(name,{'battle_id':bid}))
  self.assertEqual(self.state_now(),s);self.assertEqual(self.view()['combat']['player']['hp'],80);self.resume();self.execute(self.command('combat_attack',{'battle_id':bid}));self.assertEqual(self.view()['combat']['enemy']['hp'],25)
 def test_paused_view_allows_instant_growth_but_blocks_combat_and_legacy_start(self):
  self.pause();v=self.view();self.assertTrue(v['cultivation']['can_use_pill']);self.assertFalse(v['alchemy']['recipes'][0]['can_start']);self.assertEqual(v['combat']['available_commands'],[]);self.assertEqual(v['cultivation']['blocking_reasons']['train'],[])
 def test_pause_candidate_write_fault_rolls_back_time_jobs_and_receipt(self):
  self.alchemy();self.clock.advance(10000);q=self.command('world_pause');s=self.state_now();original=SQLiteSave.commit
  def fail(store,*args):original(store,*args);raise PersistenceError('after write')
  with patch.object(SQLiteSave,'commit',fail):
   with self.assertRaises(PersistenceError):self.execute(q)
  self.assertEqual(self.state_now(),s);self.execute(q);self.assertEqual(self.view()['alchemy']['current']['remaining_ms'],20000)
 def test_resume_write_fault_rolls_back_anchor(self):
  self.pause();s=self.state_now();self.clock.advance(10000)
  with patch.object(SQLiteSave,'commit',side_effect=PersistenceError('write failure')):
   with self.assertRaises(PersistenceError):self.resume()
  self.assertEqual(self.state_now(),s)
 def test_restart_process_keeps_pause_job_and_receipt(self):
  self.alchemy();self.clock.advance(10000);q=self.command('world_pause');self.execute(q)
  script="""import json,sys
from pathlib import Path
from src.core.save.sqlite import SQLiteSave
from src.application.world import WorldApplication
from src.data.cultivation.definitions import load_cultivation
from tests.fixtures.time import ManualClock
from src.core.state.envelope import thaw_json
from src.application.memory import Command
p=Path(sys.argv[1])
with SQLiteSave(p,allowed_root=p.parent) as store:
 a=WorldApplication(store,load_cultivation(),ManualClock(99999999));a.execute(Command(**json.loads(sys.argv[2])));print(json.dumps(thaw_json(a.view(sys.argv[3]))))
"""
  intent=dict(save_id=q.save_id,generation=q.generation,expected_revision=q.expected_revision,request_id=q.request_id,name=q.name,payload={});v=json.loads(subprocess.check_output([sys.executable,'-B','-c',script,str(self.path),json.dumps(intent),self.save],cwd=V2_ROOT));self.assertTrue(v['world']['paused']);self.assertEqual(v['alchemy']['current']['remaining_ms'],20000)
 def test_recovery_preserves_paused_checkpoint(self):
  from src.application.recovery import RecoveryApplication
  from src.core.save.recovery import RecoveryRequest
  self.pause();self.clock.advance(999999)
  with self.application() as a:
   a.checkpoint(self.save);r=RecoveryApplication(a.foundation,self.clock);o=r.inspect(self.save);self.assertEqual(r.recover(RecoveryRequest(self.save,o.current_generation,o.current_fingerprint,o.source_fingerprint,str(uuid4()),'isolated pause recovery')).status,'SUCCESS')
  self.assertTrue(self.view()['world']['paused']);self.assertEqual(self.state_now().time['sim_time_ms'],0)
 def test_clock_rollback_resume_never_rewinds_watermark(self):
  self.clock.advance(10000);self.pause();self.clock.value=1000;self.resume();self.assertEqual(self.state_now().time['last_settled_at_ms'],11000)
 def test_paused_pending_or_invalid_flag_rejected(self):
  s=self.state_now()
  for value in [1,'true',None]:
   with self.assertRaises(ValidationError):replace(s,time={**s.time,'world_paused':value})
  with self.assertRaises(ValidationError):replace(s,time={**s.time,'world_paused':True,'pending':{}})
 def test_committed_gameplay_replay_while_paused_does_not_mutate(self):
  q=self.command('cultivation_train');r=self.execute(q);self.pause();s=self.state_now();self.assertEqual(self.execute(q),r);self.assertEqual(self.state_now(),s)
 def test_building_quotes_are_real_and_pure(self):
  s=self.state_now();v=self.view();self.assertTrue(any(b['upgrade_requirements'] for b in v['buildings'].values()));self.assertTrue(all(not b['upgrade_available'] for b in v['buildings'].values()));self.assertEqual(self.state_now(),s)
if __name__=='__main__':unittest.main()

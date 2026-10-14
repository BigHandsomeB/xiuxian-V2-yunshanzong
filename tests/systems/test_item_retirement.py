"""Authorized retirement behavior; only isolated EconomyFixture Save files."""
import unittest
from contextlib import contextmanager
from unittest.mock import patch
from uuid import uuid4
from src.application.item_retirement import RetiredEconomyApplication,discard_retired
from src.application.economy import EconomyApplication
from src.application.memory import Command
from src.core.save.sqlite import SQLiteSave
from src.core.save.codec import PersistenceError
from src.core.validation import ValidationError,ConflictError
from tests.systems.test_equipment_economy import EquipmentFixture

class RetirementTests(EquipmentFixture,unittest.TestCase):
 @contextmanager
 def retired(self):
  with SQLiteSave(self.path,allowed_root=self.root) as store:yield RetiredEconomyApplication(store,self.registry,self.clock)
 def old_win(self):
  bid=self.command('combat_start',{'encounter_id':'thorn_first'}).result['combat']['battle_id']
  for _ in range(4):self.command('combat_attack',{'battle_id':bid})
  self.command('combat_reward',{'battle_id':bid});return bid
 def retire(self,q=None):
  q=q or self.q('retire_three_items')
  with self.retired() as a:return a.retire_owned(q)
 def live_command(self,name,p=None):
  q=self.q(name,p)
  with self.retired() as a:return a.execute(q)
 def test_authorized_stock_and_head_removed_no_compensation(self):
  self.old_win();s=self.state();r=self.retire();after=self.state()
  self.assertNotIn('dewleaf',after.domains['inventory']['holdings']);self.assertFalse(after.domains['equipment']['instances']);self.assertEqual(after.domains['inventory']['holdings']['coins'],s.domains['inventory']['holdings']['coins']);self.assertEqual(r.result['compensation'],{})
  self.assertEqual((after.time,after.identity,after.domains['combat']),(s.time,s.identity,s.domains['combat']))
 def test_replay_and_new_noop_safe(self):
  self.old_win();q=self.q('retire_three_items');r=self.retire(q);s=self.state();self.assertEqual(self.retire(q),r);self.retire();self.assertEqual(self.state(),s)
 def test_stale_revision_rejected(self):
  q=self.q('retire_three_items');self.command('world_pause');s=self.state()
  with self.assertRaises(ConflictError):self.retire(q)
  self.assertEqual(self.state(),s)
 def test_old_generation_rejected(self):
  s=self.state();q=Command(self.save,s.generation+1,s.revision,str(uuid4()),'retire_three_items',{})
  with self.assertRaises(ConflictError):self.retire(q)
 def test_atomic_receipt_failure_rolls_back(self):
  self.old_win();s=self.state()
  with self.retired() as a:
   with patch.object(a.store,'_insert_receipt',side_effect=PersistenceError('fixture')):
    with self.assertRaises(PersistenceError):a.retire_owned(self.q('retire_three_items'))
  self.assertEqual(self.state(),s)
 def test_retirement_works_while_paused_no_clock_change(self):
  self.old_win();self.command('world_pause');before=self.state();self.retire();self.assertEqual(self.state().time,before.time)
 def test_recipe_commands_rejected_without_consumption(self):
  self.supplies();s=self.state()
  for recipe in ['forge_sword','forge_ingot_sword']:
   with self.assertRaises(ValidationError):self.live_command('production_start',{'building_id':self.building('forge'),'recipe_id':recipe})
  self.assertEqual(self.state(),s)
 def test_retired_policy_rejected(self):
  with self.assertRaises(ValidationError):self.live_command('automation_production',{'building_id':self.building('forge'),'policy':{'enabled':True,'recipe_id':'forge_sword','target':5,'reserves':{},'max_consumption':100}})
 def test_retired_equipment_all_commands_rejected(self):
  self.old_win();i=next(iter(self.state().domains['equipment']['instances']));s=self.state()
  for name in ['equipment_equip','equipment_unequip','equipment_sell','equipment_salvage','equipment_lock','equipment_favorite']:
   with self.assertRaises(ValidationError):self.live_command(name,{'instance_id':i,'value':True} if name in ('equipment_lock','equipment_favorite') else {'instance_id':i})
  self.assertEqual(self.state(),s)
 def test_get_hides_old_items_without_mutation(self):
  self.old_win();s=self.state()
  with self.retired() as a:
   v=a.view(self.save);self.assertNotIn('dewleaf',v['inventory']);self.assertNotIn('dewleaf',v['holdings']);self.assertFalse(v['equipment']['instances']);self.assertFalse(any(r['recipe_id'].startswith('forge') for r in v['economy']['recipes']));self.assertEqual(v['capacity']['used'],29)
  self.assertEqual(self.state(),s)
 def test_new_battle_rewards_money_only_once(self):
  bid=self.live_command('combat_start',{'encounter_id':'thorn_first'}).result['combat']['battle_id']
  for _ in range(4):self.live_command('combat_attack',{'battle_id':bid})
  q=self.q('combat_reward',{'battle_id':bid})
  with self.retired() as a:
   r=a.execute(q);s=a.query(self.save);self.assertEqual(a.execute(q),r);self.assertEqual(a.query(self.save),s);self.assertEqual([x['resource_id'] for x in a.view(self.save)['combat']['reward']],['coins'])
  self.assertEqual(s.domains['inventory']['holdings'].get('coins'),3);self.assertNotIn('dewleaf',s.domains['inventory']['holdings']);self.assertFalse(s.domains['equipment']['instances'])
 def test_old_reward_receipt_replay_does_not_recreate_items(self):
  bid=self.command('combat_start',{'encounter_id':'thorn_first'}).result['combat']['battle_id']
  for _ in range(4):self.command('combat_attack',{'battle_id':bid})
  q=self.q('combat_reward',{'battle_id':bid});self.execute(q);self.retire();before=self.state()
  with self.retired() as a:a.execute(q)
  self.assertEqual(self.state(),before)
 def test_active_battle_snapshot_not_hot_swapped(self):
  i=self.forge();self.command('equipment_equip',{'instance_id':i});self.command('combat_start',{'encounter_id':'thorn_first'});snapshot=self.state().domains['combat'];self.retire();self.assertEqual(self.state().domains['combat'],snapshot)
  with self.retired() as a:self.assertEqual(a.view(self.save)['combat']['player']['attack'],14);self.assertEqual(a.player_projection(a.query(self.save))['attack_milli'],10000)
 def test_active_legacy_job_fails_closed(self):
  self.supplies();self.assign('forge','ordinary_build');self.start('forge_sword','forge');before=self.state()
  with self.assertRaises(ConflictError):self.retire()
  self.assertEqual(self.state(),before)
 def test_checkpoint_remains_compatible_and_retired_on_settlement(self):
  self.old_win()
  with self.application() as a:a.checkpoint(self.save)
  self.retire()
  from src.application.recovery import RecoveryApplication
  from src.core.save.recovery import RecoveryRequest
  with self.retired() as a:
   life=RecoveryApplication(a.foundation,self.clock);o=life.inspect(self.save);r=life.recover(RecoveryRequest(self.save,o.current_generation,o.current_fingerprint,o.source_fingerprint,str(uuid4()),'isolated retirement recovery'));self.assertEqual(r.status,'SUCCESS');self.assertNotIn('dewleaf',a.view(self.save)['inventory'])
  from src.application.settlement import SettlementRequest
  with self.retired() as a:
   s=a.query(self.save);a.settle(SettlementRequest(self.save,s.generation,s.revision,str(uuid4()),32,None));s=a.query(self.save);self.assertNotIn('dewleaf',s.domains['inventory']['holdings']);self.assertFalse(s.domains['equipment']['instances'])
 def test_restart_same_state_and_receipt(self):
  self.old_win();q=self.q('retire_three_items');r=self.retire(q);s=self.state()
  with self.retired() as a:self.assertEqual(a.query(self.save),s);self.assertEqual(a.retire_owned(q),r)

 def test_recovered_settled_claim_does_not_report_retired_equipment(self):
  bid=self.old_win();q=self.q('combat_reward',{'battle_id':bid});before=self.state()
  with self.retired() as a:r=a.execute(q)
  self.assertIsNone(r.result['equipment_reward']);self.assertFalse(any(x['resource_id'] in ('dewleaf','basic_head') for x in r.result['combat']['reward']));self.assertEqual(self.state(),before)

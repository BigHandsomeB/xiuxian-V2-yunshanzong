"""Equipment reward claim, capacity, explicit upgrade and restart safety."""
import json,subprocess,sys
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
from uuid import uuid4
from tests.systems.test_equipment_economy import EquipmentFixture
import unittest
from src.application.economy import EconomyApplication
from src.application.economy_upgrade import upgrade
from src.application.world import WorldApplication
from src.application.danding import initial_slice
from src.application.memory import Command
from src.data.cultivation.definitions import load_cultivation
from src.core.save.sqlite import SQLiteSave,V2_ROOT
from src.core.save.codec import PersistenceError
from src.core.validation import ValidationError
from src.systems.inventory import holdings

class EconomyLootTests(EquipmentFixture,unittest.TestCase):
 def win(self):
  bid=self.command('combat_start',{'encounter_id':'thorn_first'}).result['combat']['battle_id']
  for _ in range(4):self.command('combat_attack',{'battle_id':bid})
  return bid
 def test_loot_original_reward_plus_unique_equipment(self):
  bid=self.win();q=self.q('combat_reward',{'battle_id':bid});r=self.execute(q);before=self.state();self.assertEqual(self.execute(q),r);self.command('combat_reward',{'battle_id':bid});self.assertEqual(self.state(),before);self.assertEqual(len(before.domains['equipment']['instances']),1);self.assertEqual((before.domains['inventory']['holdings']['coins'],before.domains['inventory']['holdings']['dewleaf']),(3,1));self.assertEqual(next(iter(before.domains['equipment']['instances'].values()))['definition_id'],'basic_head')
 def test_loot_equipment_changes_hp_armor_not_formula(self):
  bid=self.win();self.command('combat_reward',{'battle_id':bid});i=next(iter(self.state().domains['equipment']['instances']));self.command('equipment_equip',{'instance_id':i});bid=self.command('combat_start',{'encounter_id':'thorn_first'}).result['combat']['battle_id'];p=self.view()['combat']['player'];self.assertEqual((p['hp'],p['attack'],p['armor']),(88,10,2.5));self.command('combat_attack',{'battle_id':bid});v=self.view()['combat'];self.assertEqual((v['player']['hp'],v['enemy']['hp']),(84.5,25))
 def test_claim_separate_from_auto_sale_receipt(self):
  self.policy(upgrade=False);bid=self.win();self.command('combat_reward',{'battle_id':bid});self.assertEqual(len(self.state().domains['equipment']['instances']),1);self.assertEqual(self.state().domains['inventory']['holdings']['coins'],3);self.settle();self.assertEqual(len(self.state().domains['equipment']['instances']),0);self.assertEqual(self.state().domains['inventory']['holdings']['coins'],28)
 def test_auto_failure_does_not_lose_claim(self):
  self.policy(upgrade=False);bid=self.win();self.command('combat_reward',{'battle_id':bid})
  with patch('src.application.equipment.process',side_effect=ValidationError('sale unavailable')):self.settle()
  self.assertEqual(self.state().domains['combat']['battle']['status'],'SETTLED');self.assertEqual(len(self.state().domains['equipment']['instances']),1);self.assertEqual(self.state().domains['inventory']['holdings']['coins'],3)
 def test_loot_full_bag_waits_and_claims_once(self):
  bid=self.win();capacity=self.view()['capacity']['effective'];used=holdings.stock_size(self.state().domains['inventory'],self.registry);self.command('inventory_grant',{'amounts':{'herb':capacity-used}});before=self.state()
  with self.assertRaises(ValidationError):self.command('combat_reward',{'battle_id':bid})
  self.assertEqual(self.state(),before);self.command('inventory_consume',{'amounts':{'herb':5}});self.command('combat_reward',{'battle_id':bid});self.assertEqual(len(self.state().domains['equipment']['instances']),1)
 def test_forge_full_warehouse_keeps_equipment_in_personal_bag(self):
  self.supplies();self.assign('forge','ordinary_build');self.start('forge_sword','forge');capacity=self.view()['capacity']['effective'];used=holdings.stock_size(self.state().domains['inventory'],self.registry);self.command('inventory_grant',{'amounts':{'herb':capacity-used}});self.clock.advance(120000);self.settle();s=self.state();self.assertEqual(s.domains['production']['jobs'][self.building('forge')]['status'],'COMPLETE');self.assertEqual(len(s.domains['equipment']['instances']),1);self.assertEqual(holdings.stock_size(s.domains['inventory'],self.registry),capacity);self.command('inventory_consume',{'amounts':{'herb':2}});self.settle();self.assertEqual(len(self.state().domains['equipment']['instances']),1)
 def test_claim_atomic_instance_creation_failure(self):
  bid=self.win();before=self.state()
  with patch('src.application.equipment.items.add',side_effect=ValidationError('instance failure')):
   with self.assertRaises(ValidationError):self.command('combat_reward',{'battle_id':bid})
  self.assertEqual(self.state(),before)
 def test_old_save_upgrade_preserves_all_real_domains_and_pause(self):
  path=self.root/'old.sqlite3';old=load_cultivation();s=initial_slice(old,last_settled_at_ms=1000)
  with SQLiteSave.initialize(path,allowed_root=self.root) as store:
   app=WorldApplication(store,old,self.clock);app.create(s);app.execute(Command(s.save_id,1,s.revision,str(uuid4()),'world_pause',{}));before=app.query(s.save_id);q=Command(s.save_id,1,before.revision,str(uuid4()),'economy_content_upgrade',{});r=upgrade(store,self.clock,q);new=EconomyApplication(store,self.registry,self.clock).query(s.save_id)
   for k,v in before.domains.items():self.assertEqual(new.domains[k],v)
   self.assertEqual(new.time,before.time);self.assertEqual(new.identity,before.identity);self.assertEqual(upgrade(store,self.clock,q),r);self.assertFalse(new.domains['equipment']['instances']);self.assertFalse(new.domains['automation']['production'])
 def test_upgrade_rollback_keeps_old_save(self):
  path=self.root/'old.sqlite3';old=load_cultivation();s=initial_slice(old,last_settled_at_ms=1000)
  with SQLiteSave.initialize(path,allowed_root=self.root) as store:
   a=WorldApplication(store,old,self.clock);a.create(s);q=Command(s.save_id,1,s.revision,str(uuid4()),'economy_content_upgrade',{})
   with patch.object(SQLiteSave,'commit',side_effect=PersistenceError('isolated upgrade failure')):
    with self.assertRaises(PersistenceError):upgrade(store,self.clock,q)
   self.assertEqual(a.query(s.save_id),s)
 def test_real_process_restart_preserves_equipment_policy_and_receipt(self):
  i=self.forge();self.command('equipment_equip',{'instance_id':i});self.policy();q=self.q('equipment_lock',{'instance_id':i,'value':True});self.execute(q);before=self.state()
  code="""import sys,json
from pathlib import Path
from src.core.save.sqlite import SQLiteSave
from src.application.economy import EconomyApplication
from src.application.memory import Command
from src.data.economy.definitions import load_economy
from tests.fixtures.time import ManualClock
p=Path(sys.argv[1]);q=json.loads(sys.argv[2])
with SQLiteSave(p,allowed_root=p.parent) as store:
 a=EconomyApplication(store,load_economy(),ManualClock(1000));s=a.query(q['save_id']);a.execute(Command(**q));assert s==a.query(q['save_id']);print(json.dumps(a.query(q['save_id']).to_dict()))
"""
  intent={'save_id':q.save_id,'generation':q.generation,'expected_revision':q.expected_revision,'request_id':q.request_id,'name':q.name,'payload':{'instance_id':i,'value':True}}
  result=json.loads(subprocess.check_output([sys.executable,'-B','-c',code,str(self.path),json.dumps(intent)],cwd=V2_ROOT));self.assertEqual(result,before.to_dict())

 def test_existing_recovery_contract_preserves_equipment_and_policy(self):
  from src.application.recovery import RecoveryApplication
  from src.core.save.recovery import RecoveryRequest
  from src.core.validation import ConflictError
  i=self.forge();self.command('equipment_equip',{'instance_id':i});self.auto('mine','ore');q=self.q('equipment_lock',{'instance_id':i,'value':True});self.execute(q);before=self.state()
  with self.application() as app:
   app.checkpoint(self.save);life=RecoveryApplication(app.foundation,self.clock);observation=life.inspect(self.save);self.assertEqual(observation.status,'READY');r=life.recover(RecoveryRequest(self.save,observation.current_generation,observation.current_fingerprint,observation.source_fingerprint,str(uuid4()),'isolated Phase16 recovery'));self.assertEqual(r.status,'SUCCESS')
  self.assertEqual(self.state().domains,before.domains)
  with self.assertRaises(ConflictError):self.execute(q)

 def test_operator_upgrade_cli_uses_application_transaction(self):
  from tools.playable.economy_upgrade import run
  from contextlib import redirect_stdout
  from io import StringIO
  oldroot=self.root/'operator';oldroot.mkdir();path=oldroot/'danding.sqlite3';old=load_cultivation();s=initial_slice(old,last_settled_at_ms=1000)
  with SQLiteSave.initialize(path,allowed_root=oldroot) as store:WorldApplication(store,old,self.clock).create(s)
  (oldroot/'save-id').write_text(s.save_id)
  with redirect_stdout(StringIO()):run(oldroot)
  with SQLiteSave(path,allowed_root=oldroot) as store:
   app=EconomyApplication(store,self.registry,self.clock);new=app.query(s.save_id);self.assertEqual(new.time,s.time);self.assertEqual(new.identity,s.identity)
   for k,v in s.domains.items():self.assertEqual(new.domains[k],v)
   self.assertEqual(app.foundation.inspect(s.save_id).recovery,new)

 def test_old_settled_battle_never_displays_or_grants_new_equipment(self):
  path=self.root/'old-settled.sqlite3';old=load_cultivation();s=initial_slice(old,last_settled_at_ms=1000)
  with SQLiteSave.initialize(path,allowed_root=self.root) as store:
   a=WorldApplication(store,old,self.clock);a.create(s)
   def act(name,p):
    state=a.query(s.save_id);return a.execute(Command(s.save_id,state.generation,state.revision,str(uuid4()),name,p))
   bid=act('combat_start',{'encounter_id':'thorn_first'}).result['combat']['battle_id']
   for _ in range(4):act('combat_attack',{'battle_id':bid})
   act('combat_reward',{'battle_id':bid});before=a.query(s.save_id);upgrade(store,self.clock,Command(s.save_id,1,before.revision,str(uuid4()),'economy_content_upgrade',{}));new=EconomyApplication(store,self.registry,self.clock);state=new.query(s.save_id);v=new.view(s.save_id);self.assertEqual(len(v['combat']['reward']),2);self.assertFalse(v['equipment']['instances']);r=new.execute(Command(s.save_id,1,state.revision,str(uuid4()),'combat_reward',{'battle_id':bid}));self.assertIsNone(r.result['equipment_reward']);self.assertEqual(new.query(s.save_id),state)
 def test_new_claim_history_remains_truthful_after_item_sold(self):
  bid=self.win();self.command('combat_reward',{'battle_id':bid});i=next(iter(self.state().domains['equipment']['instances']));self.command('equipment_sell',{'instance_id':i});self.assertEqual(len(self.view()['combat']['reward']),3);self.assertFalse(self.view()['equipment']['instances']);self.assertEqual(self.state().domains['equipment']['latest_reward']['instance_id'],i)

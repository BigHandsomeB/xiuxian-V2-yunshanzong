"""Whole backpack, server-selected atomic commands: protection, CAS and replay."""
import json,tempfile,unittest
from pathlib import Path
from dataclasses import replace
from uuid import uuid4
from unittest.mock import patch
from src.application import equipment as equip
from src.application.sect_management import ManagementApplication
from src.application.memory import Command
from src.core.save.sqlite import SQLiteSave,V2_ROOT
from src.core.state.envelope import thaw_json
from src.core.validation import ConflictError,ValidationError
from tests.systems import test_settlement_batch as fixtures

class EquipmentBulkTests(unittest.TestCase):
 def setUp(self):
  fixture=fixtures.SettlementBatchTests();fixture.setUp();self.addCleanup(fixture.doCleanups);self.registry=fixture.registry;self.clock=fixture.clock;self.s=fixture.state;self.base=self.s
  self.temp=tempfile.TemporaryDirectory(dir=V2_ROOT/'.tmp');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.path=self.root/'bulk.sqlite3'
 def seed(self,count=7,definition='basic_left'):
  s,identity=equip.acquire(self.s,self.registry,definition,'bulk-fixture');e=thaw_json(s.domains['equipment']);row=e['instances'].pop(identity);counter=self.s.identity['instance_counter'];ids=[f'{s.save_id}:{s.generation}:i:{counter+n+1}' for n in range(count)]
  for i in ids:e['instances'][i]=dict(row)
  for i,key in zip(ids,('equipped','locked','favorite')):e['instances'][i][key]=True
  e['slots']['left']=ids[0];e['instances'][ids[3]]['enhancement']={'level':1,'bonus_bps':500,'version':'sect-enhance-v1'};e['instances'][ids[4]]['tradeable']=False
  e['instances'][ids[0]]['owner']='player'
  self.ids=ids;self.s=replace(s,identity={**s.identity,'instance_counter':counter+count},domains={**s.domains,'equipment':e})
  with SQLiteSave.initialize(self.path,allowed_root=self.root) as store:ManagementApplication(store,self.registry,self.clock).create(self.s)
 def command(self,s,mode,digest=None):return Command(s.save_id,s.generation,s.revision,str(uuid4()),'equipment_'+mode+'_all',{'selection_digest':digest or equip.bulk_preview(s,self.registry)['selection_digest']})
 def test_sell_and_salvage_exclude_protected_enhanced_unknown_atomic_replay(self):
  for mode in ('sell','salvage'):
   with self.subTest(mode=mode):
    if self.path.exists():self.path.unlink()
    self.s=self.base;self.seed();preview=equip.bulk_preview(self.s,self.registry);self.assertEqual(preview['count'],2)
    q=self.command(self.s,mode)
    with SQLiteSave(self.path,allowed_root=self.root) as store:
     app=ManagementApplication(store,self.registry,self.clock);r=app.execute(q);after=app.query(self.s.save_id);self.assertEqual(app.execute(q),r);self.assertEqual(app.query(self.s.save_id),after)
     self.assertEqual(set(after.domains['equipment']['instances']),set(self.ids[:5]));self.assertEqual(r.result['count'],2)
     for key,n in preview[mode].items():self.assertEqual(after.domains['inventory']['holdings'].get(key,0),self.s.domains['inventory']['holdings'].get(key,0)+n)
     self.assertEqual(after.domains['equipment']['slots'],self.s.domains['equipment']['slots']);self.assertEqual(after.revision,self.s.revision+1)
 def test_changed_selection_refuses_all_without_deletion(self):
  self.seed();preview=equip.bulk_preview(self.s,self.registry);e=thaw_json(self.s.domains['equipment']);e['instances'][self.ids[-1]]['locked']=True;s=replace(self.s,domains={**self.s.domains,'equipment':e})
  with self.assertRaises(ConflictError):equip.command(s,self.registry,'equipment_sell_all',{'selection_digest':preview['selection_digest']})
  self.assertEqual(len(s.domains['equipment']['instances']),7)
 def test_large_backpack_small_command_and_stale_cas(self):
  self.seed(350);q=self.command(self.s,'sell');self.assertLess(len(json.dumps(thaw_json(q.payload))),200)
  with SQLiteSave(self.path,allowed_root=self.root) as store:
   app=ManagementApplication(store,self.registry,self.clock);r=app.execute(q);self.assertEqual(r.result['count'],345)
   with self.assertRaises(ConflictError):app.execute(replace(q,request_id=str(uuid4())))
 def test_failed_commit_and_full_warehouse_preserve_all(self):
  self.seed();q=self.command(self.s,'salvage')
  with SQLiteSave(self.path,allowed_root=self.root) as store:
   app=ManagementApplication(store,self.registry,self.clock);before=app.query(self.s.save_id)
   with patch.object(store,'_insert_receipt',side_effect=RuntimeError('injected rollback')):
    with self.assertRaises(RuntimeError):app.execute(q)
   self.assertEqual(app.query(self.s.save_id),before);self.assertIsNone(store.receipt(q.save_id,q.generation,q.request_id))
  with patch.object(equip.sect,'capacity_source',return_value={'effective':0}):
   with self.assertRaises(ValidationError):equip.command(self.s,self.registry,q.name,q.payload)
  self.assertEqual(len(self.s.domains['equipment']['instances']),7)
 def test_empty_or_malformed_selection_cannot_mutate(self):
  with self.assertRaises(ValidationError):equip.command(self.s,self.registry,'equipment_sell_all',{})
  with self.assertRaises(ValidationError):equip.command(self.s,self.registry,'equipment_sell_all',{'selection_digest':equip.bulk_preview(self.s,self.registry)['selection_digest']})

 def test_unread_offline_report_preserved_after_bulk_and_replay(self):
  from src.application.settlement import SettlementRequest
  from src.core.time.model import Continuation
  automation=thaw_json(self.s.domains['automation']);automation['equipment']['mode']='OFF'
  self.s=replace(self.s,domains={**self.s.domains,'automation':automation})
  self.seed();self.clock.advance(120000)
  with SQLiteSave(self.path,allowed_root=self.root) as store:
   app=ManagementApplication(store,self.registry,self.clock)
   for _ in range(1000):
    state=app.query(self.s.save_id)
    app.settle(SettlementRequest(state.save_id,state.generation,state.revision,str(uuid4()),4096,Continuation.for_state(state) if state.time['pending'] else None))
    state=app.query(self.s.save_id)
    if not state.time['pending']:break
   self.assertIsNone(state.time['pending'])
   report=thaw_json(state.domains['offline_reports']);self.assertTrue(report['unread'])
   for mode in ('sell','salvage'):
    with self.subTest(mode=mode):
     # Restore eligible equipment only in an isolated in-memory candidate.
     candidate=replace(state,domains={**state.domains,'equipment':self.s.domains['equipment']})
     result=equip.command(candidate,self.registry,'equipment_'+mode+'_all',{'selection_digest':equip.bulk_preview(candidate,self.registry)['selection_digest']})
     self.assertEqual(thaw_json(result.domains['offline_reports']),report)
   q=self.command(state,'sell');receipt=app.execute(q)
   self.assertEqual(app.execute(q),receipt)
   self.assertEqual(thaw_json(app.query(state.save_id).domains['offline_reports']),report)

"""Differential timed baseline plus mid-batch failure, budgets and clock rollback."""
import unittest,tempfile
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
from src.application.sect_management import ManagementApplication
from src.application.economy_settlement import EconomySettlement
from src.application.settlement import SettlementRequest
from src.core.save.sqlite import SQLiteSave,V2_ROOT
from tests.systems import test_settlement_batch as fixtures
from tests.fixtures.settlement_legacy import timed_advance

class SettlementDraftTests(unittest.TestCase):
 def setUp(self):
  f=fixtures.SettlementBatchTests();f.setUp();self.addCleanup(f.doCleanups);self.f=f
 def test_timed_baseline_budget_boundary_and_clock_rollback_identical(self):
  f=self.f
  for target in (500,1000,81000):
   with self.subTest(target=target):
    with patch.object(EconomySettlement,'advance',timed_advance):old,old_events,_=f.drain(f.state,target)
    new,new_events,_=f.drain(f.state,target,batch=2)
    f.assert_same(old,new);self.assertEqual(old_events,new_events)
  with patch('src.application.economy_settlement.monotonic',side_effect=[0,.01,.02,4.1]):
   state,result=f.app.engine.advance(f.state,max_events=4096,now_ms=81000)
  self.assertEqual(len(result.processed_events),3);self.assertEqual(result.target_sim_ms,80000)
  end,events,_=f.drain(state,10**8);reference,all_events,_=f.drain(f.state,81000)
  f.assert_same(end,reference);self.assertEqual(list(result.processed_events)+events,all_events)
 def test_middle_event_failure_rolls_back_state_receipt_and_replay_recovers(self):
  f=self.f
  with tempfile.TemporaryDirectory(dir=V2_ROOT/'.tmp') as directory:
   root=Path(directory)
   with SQLiteSave.initialize(root/'draft.sqlite3',allowed_root=root) as store:
    app=ManagementApplication(store,f.registry,f.clock);app.create(f.state);f.clock.advance(80000);before=app.query(f.state.save_id)
    q=SettlementRequest(before.save_id,before.generation,before.revision,str(uuid4()),4096)
    step=app.engine.core._batch_step;calls=[]
    def fail(*args,**kwargs):
     calls.append(1)
     if len(calls)==4:raise RuntimeError('mid-batch fault')
     return step(*args,**kwargs)
    with patch.object(app.engine.core,'_batch_step',fail):
     with self.assertRaisesRegex(RuntimeError,'mid-batch fault'):app.settle(q)
    self.assertEqual(app.query(before.save_id),before);self.assertIsNone(store.receipt(q.save_id,q.generation,q.request_id))
    receipt=app.settle(q);after=app.query(before.save_id);self.assertEqual(app.settle(q),receipt);self.assertEqual(app.query(before.save_id),after)
    self.assertGreater(len(receipt.result.processed_events),3)

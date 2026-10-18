"""Technical invariants around bounded, zero-grant current gameplay observations."""
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from src.application.ecology import EcologyApplication
from src.core.save.sqlite import SQLiteSave, V2_ROOT
from src.core.validation import ValidationError
from src.data.content_loader import ContentLoader
from src.data.content_compatibility import package_evidence
from tests.fixtures import first_stage_flow as model
from tests.fixtures.time import ManualClock


class FirstStageFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry=ContentLoader().load()

    def temporary(self):
        temporary=tempfile.TemporaryDirectory(prefix='first-stage-flow-',dir=V2_ROOT/'tests')
        self.addCleanup(temporary.cleanup)
        return Path(temporary.name)

    def test_three_predeclared_zero_grant_flows_and_persistent_receipts(self):
        before=model.input_fingerprint();fingerprint=package_evidence(self.registry)
        reports=[];deadline=time.monotonic()+52
        for seed in model.SEEDS:
            root=self.temporary();path=root/'isolated.sqlite3'
            with SQLiteSave.initialize(path,allowed_root=root) as store:
                flow=model.Flow(store,self.registry,seed,deadline=min(deadline,time.monotonic()+16))
                initial=flow.initial
                self.assertEqual(dict(initial.domains['inventory']['holdings']),{'herb':30})
                self.assertEqual(sum(row['count'] for row in initial.domains['disciples']['groups'].values()),8)
                self.assertEqual(initial.domains['equipment']['instances'],{})
                self.assertFalse(any(row['definition_id']=='spring' for row in initial.domains['sect']['buildings'].values()))
                alchemy=flow.building('alchemy');policy=initial.domains['automation']['production'][alchemy]
                self.assertEqual(policy['recipe_id'],'ju_qi_pill')
                report=flow.run();final=flow.state()
                self.assertEqual(report['errors'],[],report['errors'])
                self.assertLessEqual(flow.requests,3000);self.assertLessEqual(flow.fights,300)
                self.assertLessEqual(report['clock_requested_ms'],6*3600000)
                self.assertLessEqual(max((row['steps'] for row in report['combats']),default=0),256)
                self.assertEqual(set(report['nodes']),set(model.STAGES))
                self.assertTrue(all(v['status'] in ('REACHED','UNTESTED','BLOCKED','STRATEGY_BLOCKED','TRUNCATED') for v in report['nodes'].values()))
                # No snapshot edit/grant capability: all changes recorded from actual authority calls.
                self.assertEqual(final.revision,initial.revision+sum(row['revision'][1]-row['revision'][0] for row in flow.ledger))
                if flow.receipts:
                    request,receipt=flow.receipts[0]
                    self.assertEqual(flow.app.execute(request),receipt)
                    self.assertEqual(flow.app.query(flow.sid),final)
                    report['receipt_replay']='PASSED'
                else:report['receipt_replay']='NOT_REACHED'
                flow.app.view(flow.sid)
                self.assertEqual(flow.app.query(flow.sid),final)
            with SQLiteSave(path,allowed_root=root) as store:
                app=EcologyApplication(store,self.registry,flow.clock)
                self.assertEqual(app.query(flow.sid),final)
                if flow.receipts:
                    self.assertEqual(app.execute(flow.receipts[0][0]),flow.receipts[0][1])
                    self.assertEqual(app.query(flow.sid),final)
                report['reopen']='PASSED'
            if seed==model.SEEDS[0]:
                code='''
import json,sys
from pathlib import Path
from src.application.ecology import EcologyApplication
from src.core.save.sqlite import SQLiteSave
from src.data.content_loader import ContentLoader
from tests.fixtures.time import ManualClock
root=Path(sys.argv[1])
with SQLiteSave(root/'isolated.sqlite3',allowed_root=root) as store:
 app=EcologyApplication(store,ContentLoader().load(),ManualClock(int(sys.argv[3])))
 state=app.query(sys.argv[2]);app.view(sys.argv[2]);assert app.query(sys.argv[2])==state
 print(json.dumps(state.to_dict(),sort_keys=True))
'''
                child=subprocess.run([sys.executable,'-B','-c',code,str(root),flow.sid,str(flow.clock.value)],
                                     cwd=V2_ROOT,capture_output=True,text=True,timeout=5)
                self.assertEqual(child.returncode,0,child.stderr)
                self.assertEqual(json.loads(child.stdout),final.to_dict())
                report['child_restart']='PASSED'
            reports.append(report)
        self.assertEqual(model.input_fingerprint(),before)
        self.assertEqual(package_evidence(ContentLoader().load()),fingerprint)
        self.assertEqual([row['seed'] for row in reports],list(model.SEEDS))
        print('FIRST_STAGE_INPUT='+before)
        print('FIRST_STAGE_REPORT='+json.dumps(reports,ensure_ascii=False,sort_keys=True))

    def test_request_limit_preserves_last_legal_state(self):
        root=self.temporary()
        with SQLiteSave.initialize(root/'isolated.sqlite3',allowed_root=root) as store:
            flow=model.Flow(store,self.registry,1,deadline=time.monotonic()+5,limits=model.Limits(requests=1))
            flow.advance(0);before=flow.state()
            with self.assertRaises(model.FlowStop) as caught:flow.command('material_reserve',{'resource_id':'wood','quantity':15})
            self.assertEqual(caught.exception.reason,'REQUEST_BUDGET')
            self.assertEqual(flow.app.query(flow.sid),before)
            self.assertEqual(flow.requests,1)

    def test_wall_sim_fight_and_turn_limits_do_not_create_fake_progress(self):
        for kind in ('wall','sim','fight','turn'):
            with self.subTest(limit=kind):
                root=self.temporary()
                with SQLiteSave.initialize(root/'isolated.sqlite3',allowed_root=root) as store:
                    flow=model.Flow(store,self.registry,1,deadline=time.monotonic()+5)
                    if kind=='wall':flow.deadline=time.monotonic()-1
                    elif kind=='sim':flow.limits=replace(flow.limits,sim_ms=0)
                    elif kind=='fight':flow.limits=replace(flow.limits,fights=0)
                    else:flow.limits=replace(flow.limits,turns=0)
                    before=flow.state()
                    with self.assertRaises(model.FlowStop) as caught:
                        if kind=='wall':flow.advance(0)
                        elif kind=='sim':flow.advance(1)
                        else:flow.fight(1)
                    self.assertEqual(caught.exception.category,'TRUNCATED')
                    after=flow.app.query(flow.sid)
                    self.assertEqual(after.domains['dungeon']['cleared_floor'],0)
                    if kind=='turn':
                        self.assertEqual(after.domains['combat']['battle']['status'],'ACTIVE')
                        self.assertEqual(after.domains['combat']['battle']['step'],0)
                    else:self.assertEqual(after,before)

    def test_seed_and_database_boundary_are_fixed(self):
        root=self.temporary()
        with SQLiteSave.initialize(root/'isolated.sqlite3',allowed_root=root) as store:
            with self.assertRaises(ValidationError):model.Flow(store,self.registry,4,deadline=time.monotonic()+5)
        from types import SimpleNamespace
        with self.assertRaises(ValidationError):model.check_test_store(SimpleNamespace(path=V2_ROOT/'.game/danding.sqlite3'))


if __name__=='__main__':
    unittest.main()

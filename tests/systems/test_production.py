"""Isolated real production rules; fixture workforce/extra building, no V1 execution."""
from dataclasses import replace, FrozenInstanceError
from pathlib import Path
from uuid import uuid4
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from src.application import production
from src.application.memory import Command
from src.application.settlement import SettlementRequest
from src.application.recovery import RecoveryApplication
from src.core.save.recovery import RecoveryRequest
from src.core.save.sqlite import SQLiteSave,V2_ROOT
from src.core.state.envelope import thaw_json
from src.core.time.model import Continuation
from src.core.time.config import OFFLINE_CAP_MS
from src.core.validation import ValidationError,ConflictError,NotFoundError,DuplicateError
from src.data.recipes.production import load_production
from src.data.registry import DefinitionKey
from src.systems.inventory import holdings
from src.systems.resources import jobs
from tests.fixtures.time import ManualClock


class ProductionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=V2_ROOT/'tests')
        self.root=Path(self.temp.name);self.path=self.root/'test.sqlite3'
        self.store=SQLiteSave.initialize(self.path,allowed_root=self.root)
        self.registry=load_production();self.clock=ManualClock(1000)
        self.app=production.ProductionApplication(self.store,self.registry,self.clock)
        self.state=production.new_state(self.registry,last_settled_at_ms=1000)
        rows=thaw_json(self.state.domains['sect'])
        self.field=next(k for k,v in rows['buildings'].items() if v['definition_id']=='field')
        self.smelter=f'{self.state.save_id}:1:i:13'
        rows['buildings'][self.smelter]={'definition_id':'smelter','level':1,'construction_target':None}
        self.state=replace(self.state,domains={**self.state.domains,'sect':rows},identity={**self.state.identity,'instance_counter':13})
        self.app.create(self.state)

    def tearDown(self):
        self.store.close();self.temp.cleanup();self.assertFalse(self.root.exists())

    def snapshot(self):return self.app.query(self.state.save_id)

    def command(self,name,payload,**overrides):
        s=self.snapshot();fields=dict(save_id=s.save_id,generation=s.generation,expected_revision=s.revision,
                                  request_id=str(uuid4()),name=name,payload=payload)
        fields.update(overrides);return Command(**fields)

    def intent(self,**overrides):
        p=dict(building_id=self.field,recipe_id='grain',workers=1,worker_power_milli=1000,
               work_rate_milli=1000,unlock_floor=0,unlock_realm=0)
        p.update(overrides);return p

    def start(self,**overrides):return self.app.execute(self.command('production_start',self.intent(**overrides)))
    def stock(self,name,amounts):return self.app.execute(self.command('inventory_'+name,{'amounts':amounts}))
    def request(self,budget=10,continuation=None,**overrides):
        s=self.snapshot();p=dict(save_id=s.save_id,generation=s.generation,expected_revision=s.revision,
                              request_id=str(uuid4()),max_events=budget,continuation=continuation)
        p.update(overrides);return SettlementRequest(**p)
    def advance(self,elapsed,budget=10):
        self.clock.advance(elapsed);return self.app.settle(self.request(budget))
    def quantity(self,key):return holdings.get_quantity(self.snapshot().domains['inventory'],self.registry,key)
    def restart(self):
        self.store.close();self.store=SQLiteSave(self.path,allowed_root=self.root)
        self.registry=load_production();self.app=production.ProductionApplication(self.store,self.registry,self.clock)

    def test_real_definitions_and_identity(self):
        d=jobs.definition(self.registry,'grain');self.assertEqual(d.outputs,(('grain',3),));self.assertEqual(d.duration_ms,30000)
        self.assertEqual(jobs.definition(self.registry,'ingot').inputs,(('ore',3),))
        self.assertEqual(d.machine_id,'grain')
        with self.assertRaises(FrozenInstanceError):d.display_name='changed'
        package=json.loads(Path('src/data/recipes/production.json').read_text());package['definitions'][0]['display_name']='改名'
        self.assertEqual(jobs.definition(load_production(json.dumps(package)),'grain').machine_id,d.machine_id)

    def test_definition_validation(self):
        original=json.loads(Path('src/data/recipes/production.json').read_text())
        for field,value in [('duration_ms',True),('duration_ms',0),('outputs',{}),('outputs',{'not_real':1}),('inputs',{'ore':-1}),('building_kind','unknown')]:
            p=json.loads(json.dumps(original));p['definitions'][0][field]=value
            with self.subTest(field=field,value=value),self.assertRaises((ValidationError,NotFoundError)):load_production(json.dumps(p))
        original['definitions'].append(original['definitions'][0])
        with self.assertRaises(DuplicateError):load_production(json.dumps(original))

    def test_job_start_allocates_once_and_no_definition_copy(self):
        before=self.snapshot();r=self.start();s=self.snapshot();j=s.domains['production']['jobs'][self.field]
        self.assertEqual(s.revision,before.revision+1);self.assertEqual(j['job_id'],r.result['job_id'])
        self.assertEqual(s.time,before.time);self.assertEqual(j['recipe_id'],'grain')
        self.assertFalse({'display_name','outputs','building_level_copy','sprite'}&set(j))
        self.assertEqual(s.identity['instance_counter'],14);self.assertEqual(s.identity['event_counter'],1)

    def test_unknown_building_recipe_and_mismatched_capability(self):
        for p in [self.intent(building_id='missing'),self.intent(recipe_id='missing'),self.intent(recipe_id='ingot')]:
            before=self.snapshot()
            with self.assertRaises((NotFoundError,ValidationError)):self.app.execute(self.command('production_start',p))
            self.assertEqual(before,self.snapshot())

    def test_bad_workforce_and_unlock_context(self):
        for key in ['workers','worker_power_milli','work_rate_milli']:
            for value in [True,0,-1,1.5]:
                with self.subTest(key=key,value=value),self.assertRaises(ValidationError):self.start(**{key:value})
        with self.assertRaises(ValidationError):self.start(building_id=self.smelter,recipe_id='ingot',unlock_floor=4)
        self.assertEqual(self.snapshot(),self.state)

    def test_zero_level_rejected(self):
        p=thaw_json(self.state.domains['sect']);p['buildings'][self.field].update(level=0,construction_target=1)
        s=replace(self.state,save_id=self.state.save_id)
        self.store.close();self.path=self.root/'zero.sqlite3';self.store=SQLiteSave.initialize(self.path,allowed_root=self.root)
        self.app=production.ProductionApplication(self.store,self.registry,self.clock)
        self.app.create(replace(s,domains={**s.domains,'sect':p}))
        with self.assertRaises(ValidationError):self.start()

    def test_inputs_consumed_once_outputs_not_early(self):
        self.stock('grant',{'ore':6});self.start(building_id=self.smelter,recipe_id='ingot',workers=2,worker_power_milli=2000,unlock_floor=5)
        self.assertEqual(self.quantity('ore'),0);self.assertEqual(self.quantity('ingot'),0)
        self.advance(29999);self.assertEqual(self.quantity('ingot'),0)
        self.advance(1);self.assertEqual(self.quantity('ingot'),2)
        self.advance(60000);self.assertEqual(self.quantity('ingot'),2)

    def test_insufficient_inputs_and_busy_are_atomic(self):
        before=self.snapshot()
        with self.assertRaises(ValidationError):self.start(building_id=self.smelter,recipe_id='ingot',unlock_floor=5)
        self.assertEqual(before,self.snapshot())
        self.start();before=self.snapshot()
        with self.assertRaises(ConflictError):self.start()
        self.assertEqual(before,self.snapshot())

    def test_work_progress_and_read_only_view(self):
        self.start();self.advance(15000)
        self.assertEqual(self.app.query_building(self.state.save_id,self.field)['progress_milli'],15000000)
        before=self.snapshot();reads=self.clock.reads
        self.assertEqual(self.app.query_building(self.state.save_id,self.field)['state'],'WORKING')
        self.assertEqual(self.app.query_building(self.state.save_id,self.smelter)['state'],'IDLE')
        with self.assertRaises(NotFoundError):self.app.query_building(self.state.save_id,'missing')
        self.assertEqual(before,self.snapshot());self.assertEqual(reads,self.clock.reads)
        self.advance(12000);self.assertEqual(self.app.query_building(self.state.save_id,self.field)['state'],'FINISHING')
        self.advance(3000);self.assertEqual(self.app.query_building(self.state.save_id,self.field)['state'],'COMPLETE')

    def test_fixed_work_rate(self):
        self.start(work_rate_milli=500);self.advance(30000);self.assertEqual(self.quantity('grain'),0)
        self.assertEqual(self.snapshot().domains['production']['jobs'][self.field]['progress_milli'],15000000)
        self.advance(30000);self.assertEqual(self.quantity('grain'),3)

    def test_building_level_yield_input_not_copied(self):
        p=thaw_json(self.state.domains['sect']);p['buildings'][self.field]['level']=10
        engine=self.app.engine
        changed=replace(self.state,domains={**self.state.domains,'sect':p})
        self.store.close();self.path=self.root/'level.sqlite3';self.store=SQLiteSave.initialize(self.path,allowed_root=self.root)
        self.app=production.ProductionApplication(self.store,self.registry,self.clock);self.app.create(changed)
        self.start(worker_power_milli=2000);j=self.snapshot().domains['production']['jobs'][self.field]
        self.assertEqual(j['yield_milli'],2900);self.assertNotIn('level',j)
        self.advance(30000);self.assertEqual(self.quantity('grain'),8)

    def test_capacity_preserves_whole_output_and_retry(self):
        self.stock('grant',{'grain':6998,'coins':100000});self.start();self.advance(30000)
        self.assertEqual(self.quantity('grain'),6998);self.assertEqual(self.app.query_building(self.state.save_id,self.field)['state'],'BLOCKED')
        self.restart();self.stock('consume',{'grain':1});before=self.snapshot()
        self.app.settle(self.request());self.assertEqual(self.quantity('grain'),7000)
        self.assertEqual(self.snapshot().revision,before.revision+1)
        self.assertEqual(self.snapshot().time,before.time)
        self.assertEqual(self.quantity('coins'),100000)

    def test_idempotent_start_conflict_revision_and_generation(self):
        cmd=self.command('production_start',self.intent());r=self.app.execute(cmd);s=self.snapshot()
        self.assertEqual(self.app.execute(cmd),r);self.assertEqual(self.snapshot(),s)
        with self.assertRaises(ConflictError):self.app.execute(replace(cmd,payload=self.intent(workers=2)))
        with self.assertRaises(ConflictError):self.app.execute(replace(cmd,request_id=str(uuid4())))
        with self.assertRaises(ConflictError):self.app.execute(replace(cmd,generation=2))

    def test_full_vs_segmented_vs_pending(self):
        self.stock('grant',{'ore':3});self.start();self.start(building_id=self.smelter,recipe_id='ingot',unlock_floor=5)
        initial=self.snapshot();engine=self.app.engine
        full,_=engine.advance(initial,max_events=100,now_ms=61000)
        part,_=engine.advance(initial,max_events=100,now_ms=16000)
        segmented,_=engine.advance(part,max_events=100,now_ms=61000)
        pending,r=engine.advance(initial,max_events=1,now_ms=61000)
        self.assertEqual(r.status,'PENDING');self.assertEqual(r.continuation,Continuation.for_state(pending))
        resumed,r=engine.advance(pending,max_events=1,continuation=r.continuation)
        self.assertEqual(r.status,'COMPLETE')
        for candidate in [segmented,resumed]:
            self.assertEqual(candidate.domains,full.domains);self.assertEqual(candidate.time,full.time)

    def test_pending_restart_and_receipt_replay(self):
        self.stock('grant',{'ore':3});self.start();self.start(building_id=self.smelter,recipe_id='ingot',unlock_floor=5)
        self.clock.advance(60000);request=self.request(budget=1);r=self.app.settle(request)
        self.assertEqual(r.result.status,'PENDING');s=self.snapshot();self.restart()
        self.assertEqual(self.app.settle(request),r);self.assertEqual(self.snapshot(),s)
        r=self.app.settle(self.request(budget=1,continuation=Continuation.for_state(self.snapshot())))
        self.assertEqual(r.result.status,'COMPLETE');self.assertEqual(self.quantity('grain'),3);self.assertEqual(self.quantity('ingot'),1)

    def test_restart_preserves_work_and_start_receipt(self):
        cmd=self.command('production_start',self.intent(work_rate_milli=500));r=self.app.execute(cmd)
        self.advance(15000);before=self.snapshot();self.restart()
        self.assertEqual(before,self.snapshot());self.assertEqual(self.app.execute(cmd),r)
        self.advance(45000);self.assertEqual(self.quantity('grain'),3)

    def test_real_fresh_process_restart(self):
        self.start();self.advance(12000);expected=self.snapshot().to_dict();self.store.close()
        code="import json,sys\nfrom pathlib import Path\nfrom src.application.production import ProductionApplication\nfrom src.data.recipes.production import load_production\nfrom src.core.save.sqlite import SQLiteSave\nfrom tests.fixtures.time import ManualClock\nwith SQLiteSave(Path(sys.argv[1]),allowed_root=Path(sys.argv[2])) as store:\n app=ProductionApplication(store,load_production(),ManualClock(13000))\n print(json.dumps(app.query(sys.argv[3]).to_dict()))\n"
        result=subprocess.run([sys.executable,'-B','-c',code,str(self.path),str(self.root),self.state.save_id],check=True,capture_output=True,text=True)
        self.assertEqual(json.loads(result.stdout),expected);self.restart();self.advance(18000);self.assertEqual(self.quantity('grain'),3)

    def test_offline_cap_freezes_excess_after_restart(self):
        self.start();r=self.advance(100*3600000)
        self.assertEqual(r.result.accepted_ms,OFFLINE_CAP_MS);self.assertEqual(r.result.discarded_ms,100*3600000-OFFLINE_CAP_MS)
        self.assertEqual(self.quantity('grain'),3);s=self.snapshot();self.restart();self.app.settle(self.request())
        self.assertEqual(self.snapshot().time,s.time);self.assertEqual(self.quantity('grain'),3)
        self.start();self.advance(30000);self.assertEqual(self.quantity('grain'),6)

    def test_start_and_settlement_rollback(self):
        self.stock('grant',{'ore':3});before=self.snapshot();cmd=self.command('production_start',self.intent(building_id=self.smelter,recipe_id='ingot',unlock_floor=5))
        real=self.store.commit
        def fail(*args):real(*args);raise RuntimeError('TEST failure after all writes')
        with patch.object(self.store,'commit',side_effect=fail),self.assertRaises(RuntimeError):self.app.execute(cmd)
        self.assertEqual(before,self.snapshot());self.assertIsNone(self.store.receipt(before.save_id,before.generation,cmd.request_id))
        self.app.execute(cmd);before=self.snapshot();self.clock.advance(30000);req=self.request()
        with patch.object(self.store,'commit',side_effect=fail),self.assertRaises(RuntimeError):self.app.settle(req)
        self.assertEqual(before,self.snapshot());self.assertIsNone(self.store.receipt(before.save_id,before.generation,req.request_id))
        self.app.settle(req);self.assertEqual(self.quantity('ingot'),1)

    def test_load_validation_and_unknown_reference(self):
        self.start();s=self.snapshot()
        for field,value in [('recipe_id','unknown'),('progress_milli',10),('job_id',f'{s.save_id}:1:i:999'),('due_ms',2)]:
            p=thaw_json(s.domains['production']);p['jobs'][self.field][field]=value
            with self.subTest(field=field),self.assertRaises((ValidationError,NotFoundError)):
                self.app.foundation.validate_state(replace(s,domains={**s.domains,'production':p}))

    def test_recovery_restores_jobs_inventory_and_old_requests_stale(self):
        self.stock('grant',{'ore':3});cmd=self.command('production_start',self.intent(building_id=self.smelter,recipe_id='ingot',unlock_floor=5));self.app.execute(cmd)
        self.advance(10000);source=self.snapshot();self.app.checkpoint(source.save_id);self.advance(20000)
        recovery=RecoveryApplication(self.app.foundation,self.clock);o=recovery.inspect(source.save_id)
        r=recovery.recover(RecoveryRequest(source.save_id,o.current_generation,o.current_fingerprint,o.source_fingerprint,str(uuid4()),'TEST explicit restore'))
        self.assertEqual(r.status,'SUCCESS');restored=self.snapshot();self.assertEqual(restored.domains,source.domains)
        self.assertEqual(restored.generation,2);self.assertEqual(restored.revision,0)
        with self.assertRaises(ConflictError):self.app.execute(cmd)
        self.restart();self.advance(20000);self.assertEqual(self.quantity('ingot'),1)
        self.start();self.assertEqual(self.snapshot().generation,2)
        self.app.checkpoint(source.save_id)

    def test_corrupt_job_does_not_auto_recover(self):
        self.app.checkpoint(self.state.save_id);self.start()
        self.store._connection.execute("UPDATE current SET body='broken' WHERE save_id=?",(self.state.save_id,))
        self.assertEqual(self.app.foundation.inspect(self.state.save_id).status,'CURRENT_INVALID_RECOVERY_AVAILABLE')

    def test_unsupported_command_version_and_noop_query_writes(self):
        with self.assertRaises(ValidationError):self.app.execute(self.command('production_start',self.intent(),version=2))
        changes=self.store._connection.total_changes;before=self.snapshot()
        self.app.query_building(before.save_id,self.field)
        self.assertEqual(self.store._connection.total_changes,changes)
        r=self.app.settle(self.request());self.assertEqual(self.snapshot(),before)
        self.assertEqual(r.committed_revision,before.revision)

    def test_capacity_convergence_with_pending(self):
        self.stock('grant',{'grain':6997,'ore':3});self.start();self.start(building_id=self.smelter,recipe_id='ingot',unlock_floor=5)
        initial=self.snapshot();engine=self.app.engine
        full,_=engine.advance(initial,max_events=10,now_ms=31000)
        partial,r=engine.advance(initial,max_events=1,now_ms=31000)
        resumed,_=engine.advance(partial,max_events=1,continuation=r.continuation)
        self.assertEqual(full.domains,resumed.domains)
        self.assertEqual(sum(j['status']=='OUTPUT_READY' for j in full.domains['production']['jobs'].values()),1)
        self.assertEqual(holdings.stock_size(full.domains['inventory'],self.registry),7000)

    def test_offline_pending_restart_cap_and_recovery_stale_continuation(self):
        self.stock('grant',{'ore':3});self.start();self.start(building_id=self.smelter,recipe_id='ingot',unlock_floor=5)
        self.app.checkpoint(self.state.save_id)
        r=self.advance(100*3600000,budget=1);old=r.result.continuation
        self.assertEqual(r.result.status,'PENDING');self.assertEqual(r.result.accepted_ms,OFFLINE_CAP_MS)
        self.restart();self.app.settle(self.request(budget=1,continuation=Continuation.for_state(self.snapshot())))
        self.assertEqual(self.snapshot().time['sim_time_ms'],OFFLINE_CAP_MS)
        recovery=RecoveryApplication(self.app.foundation,self.clock);o=recovery.inspect(self.state.save_id)
        r=recovery.recover(RecoveryRequest(self.state.save_id,o.current_generation,o.current_fingerprint,o.source_fingerprint,str(uuid4()),'TEST pending source'))
        self.assertEqual(r.status,'SUCCESS');before=self.snapshot()
        with self.assertRaises(ConflictError):self.app.settle(self.request(continuation=old))
        self.assertEqual(self.snapshot(),before)
        self.app.settle(self.request());self.assertEqual(self.quantity('grain'),0)
        self.advance(30000);self.assertEqual(self.quantity('grain'),3)

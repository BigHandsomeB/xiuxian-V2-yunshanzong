"""Real V1 startup cohorts, isolated SQLite; no full Disciple or management migration."""
from dataclasses import replace,FrozenInstanceError
from pathlib import Path
from uuid import uuid4
import json,subprocess,sys,tempfile,unittest
from unittest.mock import patch
from src.application import work as application
from src.application.production import ProductionApplication
from src.application.memory import Command
from src.application.settlement import SettlementRequest
from src.application.recovery import RecoveryApplication
from src.core.save.recovery import RecoveryRequest
from src.core.save.sqlite import SQLiteSave,V2_ROOT
from src.core.save.codec import CorruptSaveError,encode_state
from src.core.state.envelope import thaw_json
from src.core.time.model import Continuation
from src.core.time.config import OFFLINE_CAP_MS
from src.core.validation import ValidationError,ConflictError,NotFoundError,DuplicateError
from src.data.disciples.work import load_work
from src.data.registry import DefinitionKey
from src.systems.disciples import work
from src.systems.sect import buildings
from src.systems.inventory import holdings
from tests.fixtures.time import ManualClock


class WorkTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=V2_ROOT/'tests');self.root=Path(self.temp.name)
        self.path=self.root/'work.sqlite3';self.store=SQLiteSave.initialize(self.path,allowed_root=self.root)
        self.registry=load_work();self.clock=ManualClock(1000)
        self.app=application.WorkApplication(self.store,self.registry,self.clock)
        self.state=application.new_state(self.registry,last_settled_at_ms=1000)
        rows=thaw_json(self.state.domains['sect'])
        self.field=next(k for k,v in rows['buildings'].items() if v['definition_id']=='field')
        self.garden=next(k for k,v in rows['buildings'].items() if v['definition_id']=='garden')
        self.house=next(k for k,v in rows['buildings'].items() if v['definition_id']=='house')
        self.smelter=f'{self.state.save_id}:1:i:18'
        rows['buildings'][self.smelter]={'definition_id':'smelter','level':1,'construction_target':None}
        self.state=replace(self.state,domains={**self.state.domains,'sect':rows},identity={**self.state.identity,'instance_counter':18})
        self.groups={row['definition_id']:key for key,row in self.state.domains['disciples']['groups'].items()}
        self.farm=self.groups['ordinary_farm'];self.gather=self.groups['ordinary_gather'];self.cook=self.groups['ordinary_cook']
        self.app.create(self.state)

    def tearDown(self):
        self.store.close();self.temp.cleanup();self.assertFalse(self.root.exists())
    def snapshot(self):return self.app.query(self.state.save_id)
    def cmd(self,name,payload,**overrides):
        s=self.snapshot();fields=dict(save_id=s.save_id,generation=s.generation,expected_revision=s.revision,
                                    request_id=str(uuid4()),name=name,payload=payload)
        fields.update(overrides);return Command(**fields)
    def assign(self,worker=None,target=None,count=1):
        return self.app.execute(self.cmd('work_assign',{'worker_id':worker or self.farm,'building_id':target or self.field,'count':count}))
    def unassign(self,worker=None,target=None):
        return self.app.execute(self.cmd('work_unassign',{'worker_id':worker or self.farm,'building_id':target or self.field}))
    def reassign(self,worker=None,old=None,new=None):
        return self.app.execute(self.cmd('work_reassign',{'worker_id':worker or self.farm,'from_building_id':old or self.field,'to_building_id':new or self.garden}))
    def start(self,target=None,recipe='grain'):
        return self.app.execute(self.cmd('production_start',{'building_id':target or self.field,'recipe_id':recipe,'unlock_floor':5,'unlock_realm':0}))
    def req(self,budget=10,continuation=None,**overrides):
        s=self.snapshot();p=dict(save_id=s.save_id,generation=s.generation,expected_revision=s.revision,
                              request_id=str(uuid4()),max_events=budget,continuation=continuation)
        p.update(overrides);return SettlementRequest(**p)
    def advance(self,elapsed,budget=10):self.clock.advance(elapsed);return self.app.settle(self.req(budget))
    def stock(self,op,amounts):return self.app.execute(self.cmd('inventory_'+op,{'amounts':amounts}))
    def quantity(self,key):return holdings.get_quantity(self.snapshot().domains['inventory'],self.registry,key)
    def restart(self):
        self.store.close();self.store=SQLiteSave(self.path,allowed_root=self.root)
        self.registry=load_work();self.app=application.WorkApplication(self.store,self.registry,self.clock)
    def recreate(self,state):
        self.store.close();self.path=self.root/'changed.sqlite3';self.store=SQLiteSave.initialize(self.path,allowed_root=self.root)
        self.app=application.WorkApplication(self.store,self.registry,self.clock);self.app.create(state)

    def test_real_census_identity_and_source_definitions(self):
        p=self.snapshot().domains['disciples'];self.assertEqual(len(p['groups']),5)
        self.assertEqual(sum(row['count'] for row in p['groups'].values()),8)
        self.assertEqual(p['groups'][self.farm]['count'],2);self.assertEqual(p['groups'][self.gather]['count'],3)
        self.assertEqual(p['assignments'],{});self.assertEqual(p['commitments'],{})
        d=self.registry.lookup(DefinitionKey('work_groups','ordinary_farm'))
        with self.assertRaises(FrozenInstanceError):d.initial_count=999
        s=self.snapshot();self.restart();self.assertEqual(self.snapshot(),s)

    def test_work_definition_validation_and_stable_display_identity(self):
        p=json.loads(Path('src/data/disciples/work.json').read_text());p['groups'][0]['display_name']='改名'
        r=load_work(json.dumps(p));self.assertTrue(r.contains(DefinitionKey('work_groups','ordinary_farm')))
        for location,key,value in [('groups','initial_count',True),('groups','initial_count',0),('building_work','slots_per_level',1.5),('building_work','enabled',1),('building_work','machine_id','unknown')]:
            q=json.loads(json.dumps(p));q[location][0][key]=value
            with self.subTest(key=key),self.assertRaises(ValidationError):load_work(json.dumps(q))
        q=json.loads(json.dumps(p));q['schema_version']=2
        with self.assertRaises(ValidationError):load_work(json.dumps(q))
        p['groups'].append(p['groups'][0])
        with self.assertRaises(DuplicateError):load_work(json.dumps(p))

    def test_assignment_creation_removal_canonical_state(self):
        before=self.snapshot();self.assign(count=2);s=self.snapshot()
        self.assertEqual(s.revision,before.revision+1);self.assertEqual(s.time,before.time)
        self.assertEqual(s.domains['disciples']['assignments'][self.farm][self.field],2)
        self.unassign();self.assertEqual(self.snapshot().domains['disciples']['assignments'],{})

    def test_reassign_atomic_move(self):
        self.assign();before=self.snapshot();self.reassign();s=self.snapshot()
        self.assertEqual(s.revision,before.revision+1)
        self.assertEqual(s.domains['disciples']['assignments'][self.farm],{self.garden:1})

    def test_duplicate_assignment_and_cohort_conservation(self):
        self.assign(count=2);before=self.snapshot()
        with self.assertRaises(ConflictError):self.assign()
        with self.assertRaises(ConflictError):self.assign(target=self.garden)
        self.assertEqual(self.snapshot(),before)

    def test_cohort_split_is_real_group_not_fake_individual(self):
        self.assign(worker=self.gather,count=1);self.assign(worker=self.gather,target=self.smelter,count=2)
        self.assertEqual(work.allocations(self.snapshot().domains['disciples'],self.gather),{self.field:1,self.smelter:2})
        with self.assertRaises(ConflictError):self.assign(worker=self.gather,target=self.garden)

    def test_unknown_worker_building_and_invalid_inputs(self):
        for worker,target,count in [('missing',self.field,1),(self.farm,'missing',1),(self.farm,self.house,1),(self.farm,self.field,True),(self.farm,self.field,0),(self.farm,self.field,1.2)]:
            before=self.snapshot()
            with self.subTest(worker=worker,target=target,count=count),self.assertRaises((NotFoundError,ValidationError)):
                self.assign(worker,target,count)
            self.assertEqual(before,self.snapshot())

    def test_zero_and_upgrading_building_slots(self):
        rows=thaw_json(self.state.domains['sect']);rows['buildings'][self.field].update(level=0,construction_target=1)
        self.recreate(replace(self.state,domains={**self.state.domains,'sect':rows}))
        with self.assertRaises(ValidationError):self.assign()
        self.assertEqual(buildings.work_slots(self.snapshot().domains['sect'],self.registry,self.field),0)
        rows['buildings'][self.field].update(level=2,construction_target=3)
        self.assertEqual(buildings.work_slots(rows,self.registry,self.field),10)

    def test_slot_capacity_sum_and_level_projection(self):
        self.assign(count=2);self.assign(worker=self.cook);before=self.snapshot()
        with self.assertRaises(ValidationError):self.assign(worker=self.gather,count=3)
        self.assertEqual(self.snapshot(),before);self.assertEqual(self.app.query_work(self.state.save_id,self.field)['slot_capacity'],5)
        self.assertEqual(self.app.query_capability(self.state.save_id,self.field)['workers'],3)
        p=thaw_json(self.state.domains['sect']);p['buildings'][self.field]['level']=2
        self.assertEqual(buildings.work_slots(p,self.registry,self.field),10)
        self.assertNotIn('slot_count_copy',self.snapshot().domains['disciples'])

    def test_production_requires_grounded_capability(self):
        before=self.snapshot()
        with self.assertRaises(ValidationError):self.start()
        self.assertEqual(self.snapshot(),before)
        self.assign(count=2);self.assertEqual(self.app.query_capability(self.state.save_id,self.field),{'workers':2,'worker_power_milli':2000,'work_rate_milli':1000})
        self.start();s=self.snapshot();job=s.domains['production']['jobs'][self.field]
        self.assertEqual(job['workers'],2);self.assertEqual(job['yield_milli'],2000)
        self.assertEqual(s.domains['disciples']['commitments'][job['job_id']]['workers'],{self.farm:2})
        self.assertNotIn('worker_ids',job);self.advance(30000);self.assertEqual(self.quantity('grain'),6)
        self.assertEqual(self.snapshot().domains['disciples']['commitments'],{})

    def test_external_worker_inputs_cannot_bypass_formal_source(self):
        self.assign()
        p={'building_id':self.field,'recipe_id':'grain','unlock_floor':0,'unlock_realm':0,'workers':100,'worker_power_milli':100000,'work_rate_milli':1000}
        with self.assertRaises(ValidationError):self.app.execute(self.cmd('production_start',p))
        with self.assertRaises(ValidationError):ProductionApplication(self.store,self.registry,self.clock)

    def test_input_consume_and_job_reservation_atomic(self):
        self.assign(worker=self.gather,target=self.smelter,count=2);before=self.snapshot()
        with self.assertRaises(ValidationError):self.start(self.smelter,'ingot')
        self.assertEqual(self.snapshot(),before)
        self.stock('grant',{'ore':6});self.start(self.smelter,'ingot');self.assertEqual(self.quantity('ore'),0)
        self.assertEqual(self.app.query_work(self.state.save_id,self.smelter)['working_count'],2)
        self.advance(30000);self.assertEqual(self.quantity('ingot'),2)

    def test_mid_job_unassignment_retains_held_labor_and_progress(self):
        self.assign(count=2);self.start();self.advance(10000);before=self.snapshot();self.unassign();s=self.snapshot()
        self.assertEqual(s.time,before.time);self.assertEqual(s.domains['production'],before.domains['production'])
        view=self.app.query_work(s.save_id,self.field);self.assertEqual(view['assigned_count'],0);self.assertEqual(view['working_count'],2)
        with self.assertRaises(ConflictError):self.assign(target=self.garden)
        self.advance(20000);self.assertEqual(self.quantity('grain'),6)
        self.assertEqual(self.app.query_work(s.save_id,self.field)['working_count'],0)
        self.assign(target=self.garden,count=2)

    def test_mid_job_reassign_rejected_and_restoring_assignment_allowed(self):
        self.assign(count=2);self.start();before=self.snapshot()
        with self.assertRaises(ConflictError):self.reassign()
        self.assertEqual(self.snapshot(),before)
        self.unassign();self.assign(count=2)
        self.assertEqual(sum(work.allocations(self.snapshot().domains['disciples'],self.farm).values()),2)
        self.advance(30000);self.reassign();self.assertEqual(self.app.query_capability(self.state.save_id,self.garden)['workers'],2)

    def test_no_implicit_time_or_query_writes(self):
        self.clock.advance(999999);before=self.snapshot();reads=self.clock.reads
        self.assign();after=self.snapshot();self.assertEqual(before.time,after.time)
        changes=self.store._connection.total_changes
        self.app.query_work(after.save_id,self.field);self.app.query_capability(after.save_id,self.field)
        self.assertEqual(self.store._connection.total_changes,changes);self.assertEqual(self.clock.reads,reads)
        self.assertEqual(self.snapshot(),after)

    def test_full_chunked_pending_equivalence_with_work_release(self):
        self.assign();self.assign(worker=self.gather,target=self.smelter);self.stock('grant',{'ore':3});self.start();self.start(self.smelter,'ingot')
        s=self.snapshot();e=self.app.engine
        full,_=e.advance(s,max_events=10,now_ms=61000)
        first,_=e.advance(s,max_events=10,now_ms=16000);chunked,_=e.advance(first,max_events=10,now_ms=61000)
        pending,r=e.advance(s,max_events=1,now_ms=61000);self.assertEqual(r.status,'PENDING')
        self.assertEqual(len(pending.domains['disciples']['commitments']),1);self.assertEqual(r.continuation,Continuation.for_state(pending))
        done,_=e.advance(pending,max_events=1,continuation=r.continuation)
        for candidate in (done,chunked):self.assertEqual(candidate.domains,full.domains);self.assertEqual(candidate.time,full.time)

    def test_pending_blocks_assignment_and_restart_resume(self):
        self.assign();self.assign(worker=self.gather,target=self.smelter);self.stock('grant',{'ore':3});self.start();self.start(self.smelter,'ingot')
        r=self.advance(60000,budget=1);before=self.snapshot()
        with self.assertRaises(ConflictError):self.unassign()
        self.restart();self.assertEqual(self.snapshot(),before)
        self.app.settle(self.req(budget=1,continuation=Continuation.for_state(self.snapshot())))
        self.assertEqual(self.snapshot().domains['disciples']['commitments'],{});self.assertEqual(self.quantity('ingot'),1)

    def test_blocked_output_releases_labor_not_output(self):
        self.stock('grant',{'grain':7000});self.assign(count=2);self.start();self.unassign();self.advance(30000)
        self.assertEqual(self.snapshot().domains['production']['jobs'][self.field]['status'],'OUTPUT_READY')
        self.assertEqual(self.snapshot().domains['disciples']['commitments'],{});self.assertEqual(self.quantity('grain'),7000)
        self.assign(target=self.garden,count=2)
        self.stock('consume',{'grain':6});self.app.settle(self.req());self.assertEqual(self.quantity('grain'),7000)

    def test_idempotency_reassign_restart_and_conflict(self):
        cmd=self.cmd('work_assign',{'worker_id':self.farm,'building_id':self.field,'count':1});r=self.app.execute(cmd)
        before=self.snapshot();self.restart();self.assertEqual(self.app.execute(cmd),r);self.assertEqual(self.snapshot(),before)
        with self.assertRaises(ConflictError):self.app.execute(replace(cmd,payload={**cmd.payload,'count':2}))
        cmd=self.cmd('work_reassign',{'worker_id':self.farm,'from_building_id':self.field,'to_building_id':self.garden})
        r=self.app.execute(cmd);before=self.snapshot();self.assertEqual(self.app.execute(cmd),r);self.assertEqual(before,self.snapshot())

    def test_stale_revision_generation_version(self):
        cmd=self.cmd('work_assign',{'worker_id':self.farm,'building_id':self.field,'count':1})
        self.assign(worker=self.cook);before=self.snapshot()
        for request in [cmd,replace(cmd,generation=2),replace(cmd,expected_revision=before.revision,version=2)]:
            with self.assertRaises((ConflictError,ValidationError)):self.app.execute(request)
        self.assertEqual(before,self.snapshot())

    def test_assignment_reassign_and_start_rollback(self):
        real=self.store.commit
        def fail(*args):real(*args);raise RuntimeError('TEST commit failure')
        cmd=self.cmd('work_assign',{'worker_id':self.farm,'building_id':self.field,'count':1});before=self.snapshot()
        with patch.object(self.store,'commit',side_effect=fail),self.assertRaises(RuntimeError):self.app.execute(cmd)
        self.assertEqual(before,self.snapshot());self.assertIsNone(self.store.receipt(before.save_id,before.generation,cmd.request_id))
        self.app.execute(cmd);before=self.snapshot()
        with patch.object(self.store,'commit',side_effect=fail),self.assertRaises(RuntimeError):self.reassign()
        self.assertEqual(before,self.snapshot())
        with patch.object(self.store,'commit',side_effect=fail),self.assertRaises(RuntimeError):self.start()
        self.assertEqual(before,self.snapshot());self.assertEqual(before.domains['disciples']['commitments'],{})

    def test_settlement_output_and_work_release_rollback(self):
        self.assign();self.start();self.unassign();before=self.snapshot();self.clock.advance(30000)
        real=self.store.commit
        def fail(*args):real(*args);raise RuntimeError('TEST settlement failure')
        with patch.object(self.store,'commit',side_effect=fail),self.assertRaises(RuntimeError):self.app.settle(self.req())
        self.assertEqual(before,self.snapshot());self.assertEqual(self.quantity('grain'),0)
        self.app.settle(self.req());self.assertEqual(self.quantity('grain'),3);self.assertEqual(self.snapshot().domains['disciples']['commitments'],{})

    def test_reference_identity_and_commitment_validation(self):
        self.assign();self.start();s=self.snapshot();p=thaw_json(s.domains['disciples']);job=next(iter(p['commitments']))
        invalid=[]
        q=thaw_json(p);q['groups'][self.farm]['definition_id']='unknown';invalid.append(q)
        q=thaw_json(p);q['assignments']['unknown']={self.field:1};invalid.append(q)
        q=thaw_json(p);q['assignments'][self.farm]={'unknown':1};invalid.append(q)
        q=thaw_json(p);q['commitments'][job]['workers']={self.farm:2};invalid.append(q)
        q=thaw_json(p);q['commitments']={};invalid.append(q)
        q=thaw_json(p);q['groups'][self.farm]['count']=True;invalid.append(q)
        q=thaw_json(p);q['groups'][self.field]=q['groups'].pop(self.farm);invalid.append(q)
        for q in invalid:
            with self.assertRaises((ValidationError,ConflictError,NotFoundError)):
                self.app.foundation.validate_state(replace(s,domains={**s.domains,'disciples':q}))

    def test_corruption_detected_without_silent_cleanup(self):
        self.assign();self.app.checkpoint(self.state.save_id);self.start()
        self.store._connection.execute("UPDATE current SET body='broken' WHERE save_id=?",(self.state.save_id,))
        self.assertEqual(self.app.foundation.inspect(self.state.save_id).status,'CURRENT_INVALID_RECOVERY_AVAILABLE')
        with self.assertRaises(CorruptSaveError):self.snapshot()
        self.assertEqual(self.store._connection.execute('SELECT body FROM current').fetchone()[0],'broken')

    def test_offline_cap_and_held_labor_restart(self):
        self.assign(count=2);self.start();self.unassign();self.restart();r=self.advance(100*3600000)
        self.assertEqual(r.result.accepted_ms,OFFLINE_CAP_MS);self.assertEqual(r.result.discarded_ms,100*3600000-OFFLINE_CAP_MS)
        self.assertEqual(self.quantity('grain'),6);self.assertEqual(self.snapshot().domains['disciples']['commitments'],{})
        before=self.snapshot();self.restart();self.app.settle(self.req());self.assertEqual(before.time,self.snapshot().time)
        self.assign(target=self.garden,count=2)

    def test_recovery_restores_source_assignment_and_commitment(self):
        self.assign(count=2);self.start();self.advance(10000);self.unassign();source=self.snapshot();self.app.checkpoint(source.save_id)
        old=self.cmd('work_assign',{'worker_id':self.farm,'building_id':self.garden,'count':2})
        self.advance(20000);self.assign(target=self.garden,count=2)
        recovery=RecoveryApplication(self.app.foundation,self.clock);o=recovery.inspect(source.save_id)
        result=recovery.recover(RecoveryRequest(source.save_id,o.current_generation,o.current_fingerprint,o.source_fingerprint,str(uuid4()),'TEST coherent work restore'))
        self.assertEqual(result.status,'SUCCESS');s=self.snapshot();self.assertEqual(s.domains,source.domains)
        self.assertEqual(s.generation,2);self.assertEqual(s.revision,0)
        with self.assertRaises(ConflictError):self.app.execute(old)
        with self.assertRaises(ConflictError):self.assign(target=self.garden,count=2)
        self.restart();self.advance(20000);self.assertEqual(self.quantity('grain'),6)
        self.assign(target=self.garden,count=2);self.app.checkpoint(source.save_id)

    def test_true_fresh_process_with_held_unassigned_workers(self):
        self.assign(count=2);self.start();self.advance(10000);self.unassign();expected=self.snapshot().to_dict();self.store.close()
        code="import json,sys\nfrom pathlib import Path\nfrom src.application.work import WorkApplication\nfrom src.data.disciples.work import load_work\nfrom src.core.save.sqlite import SQLiteSave\nfrom tests.fixtures.time import ManualClock\nwith SQLiteSave(Path(sys.argv[1]),allowed_root=Path(sys.argv[2])) as store:\n app=WorkApplication(store,load_work(),ManualClock(11000))\n print(json.dumps(app.query(sys.argv[3]).to_dict()))\n"
        p=subprocess.run([sys.executable,'-B','-c',code,str(self.path),str(self.root),self.state.save_id],capture_output=True,text=True,check=True)
        self.assertEqual(json.loads(p.stdout),expected);self.restart();self.advance(20000);self.assertEqual(self.quantity('grain'),6)

    def test_formal_start_replay_after_assignment_change_and_restart(self):
        self.assign(count=2)
        cmd=self.cmd('production_start',{'building_id':self.field,'recipe_id':'grain','unlock_floor':0,'unlock_realm':0})
        receipt=self.app.execute(cmd);self.unassign();before=self.snapshot();self.restart()
        self.assertEqual(self.app.execute(cmd),receipt);self.assertEqual(self.snapshot(),before)
        self.advance(30000);self.assertEqual(self.quantity('grain'),6)

    def test_two_connection_assignment_race_preserves_single_population(self):
        other=SQLiteSave(self.path,allowed_root=self.root)
        try:
            app=application.WorkApplication(other,load_work(),self.clock)
            old=self.cmd('work_assign',{'worker_id':self.farm,'building_id':self.garden,'count':2})
            self.assign(count=2);before=self.snapshot()
            with self.assertRaises(ConflictError):app.execute(old)
            with self.assertRaises(ConflictError):app.execute(replace(old,expected_revision=before.revision))
            self.assertEqual(before,self.snapshot())
            self.assertIsNone(other.receipt(before.save_id,before.generation,old.request_id))
        finally:other.close()

    def test_structural_corruption_with_valid_checksum_is_reported(self):
        self.app.checkpoint(self.state.save_id)
        original=self.snapshot()
        for domain,field in [('disciples','groups'),('disciples','assignments'),('disciples','commitments'),('production','jobs')]:
            part=thaw_json(original.domains[domain]);part[field]=[]
            invalid=replace(original,domains={**original.domains,domain:part})
            row=encode_state(invalid)
            self.store._connection.execute('UPDATE current SET body=?,digest=? WHERE save_id=?',(row[6],row[7],original.save_id))
            result=self.app.foundation.inspect(original.save_id)
            self.assertEqual(result.status,'CURRENT_INVALID_RECOVERY_AVAILABLE')
            self.assertEqual(self.store._connection.execute('SELECT body FROM current').fetchone()[0],row[6])
        row=encode_state(original)
        self.store._connection.execute('UPDATE current SET body=?,digest=? WHERE save_id=?',(row[6],row[7],original.save_id))
        self.assertEqual(self.snapshot(),original)

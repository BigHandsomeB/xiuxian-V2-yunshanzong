"""One actual V1 pill through shared authorities; isolated V2 DBs, no Asset/V1 writes."""
from dataclasses import replace,FrozenInstanceError
from pathlib import Path
from uuid import uuid4
import json,subprocess,sys,tempfile,unittest
from unittest.mock import patch
from src.application.alchemy import AlchemyApplication,new_state
from src.application.work import WorkApplication
from src.application.memory import Command
from src.application.settlement import SettlementRequest
from src.application.recovery import RecoveryApplication
from src.core.save.recovery import RecoveryRequest
from src.core.save.sqlite import SQLiteSave,V2_ROOT
from src.core.save.codec import CorruptSaveError,encode_state,decode_state
from src.core.state.envelope import thaw_json
from src.core.time.config import OFFLINE_CAP_MS,DEFAULT_GAME_DAY_MS
from src.core.time.model import Continuation
from src.core.validation import ValidationError,ConflictError,NotFoundError,DuplicateError
from src.data.recipes.alchemy import load_alchemy
from src.data.recipes.production import ProductionDefinition
from src.data.registry import DefinitionKey
from src.systems.alchemy import recipes
from src.systems.inventory import holdings
from tests.fixtures.time import ManualClock


class AlchemyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=V2_ROOT/'tests');self.root=Path(self.temp.name)
        self.path=self.root/'alchemy.sqlite3';self.store=SQLiteSave.initialize(self.path,allowed_root=self.root)
        self.registry=load_alchemy();self.clock=ManualClock(1000)
        self.app=AlchemyApplication(self.store,self.registry,self.clock)
        self.state=new_state(self.registry,last_settled_at_ms=1000)
        self.targets={v['definition_id']:k for k,v in self.state.domains['sect']['buildings'].items()}
        self.alchemy=self.targets['alchemy'];self.field=self.targets['field'];self.garden=self.targets['garden']
        self.groups={v['definition_id']:k for k,v in self.state.domains['disciples']['groups'].items()}
        self.worker=self.groups['ordinary_alchemy'];self.farm=self.groups['ordinary_farm']
        self.app.create(self.state)
    def tearDown(self):
        self.store.close();self.temp.cleanup();self.assertFalse(self.root.exists())
    def snapshot(self):return self.app.query(self.state.save_id)
    def command(self,name,payload,**overrides):
        s=self.snapshot();fields=dict(save_id=s.save_id,generation=s.generation,expected_revision=s.revision,
                                    request_id=str(uuid4()),name=name,payload=payload)
        fields.update(overrides);return Command(**fields)
    def start_request(self,**payload):return self.command('alchemy_start',{'building_id':self.alchemy,'recipe_id':'pill',**payload})
    def assign(self,worker=None,target=None,count=1):
        return self.app.execute(self.command('work_assign',{'worker_id':worker or self.worker,'building_id':target or self.alchemy,'count':count}))
    def stock(self,op,amounts):return self.app.execute(self.command('inventory_'+op,{'amounts':amounts}))
    def quantity(self,key):return holdings.get_quantity(self.snapshot().domains['inventory'],self.registry,key)
    def ready(self):self.assign();self.stock('grant',{'herb':5})
    def request(self,budget=10,continuation=None):
        s=self.snapshot();return SettlementRequest(s.save_id,s.generation,s.revision,str(uuid4()),budget,continuation)
    def advance(self,elapsed,budget=10):self.clock.advance(elapsed);return self.app.settle(self.request(budget))
    def restart(self):
        self.store.close();self.store=SQLiteSave(self.path,allowed_root=self.root)
        self.registry=load_alchemy();self.app=AlchemyApplication(self.store,self.registry,self.clock)
    def recreate(self,state):
        self.store.close();self.path=self.root/'changed.sqlite3';self.store=SQLiteSave.initialize(self.path,allowed_root=self.root)
        self.app=AlchemyApplication(self.store,self.registry,self.clock);self.app.create(state)

    def test_real_one_recipe_and_shared_production_definition(self):
        self.assertEqual(recipes.recipe_ids(self.registry),('pill',))
        d=recipes.definition(self.registry,'pill');self.assertIsInstance(d,ProductionDefinition)
        self.assertEqual((d.building_kind,d.inputs,d.outputs,d.duration_ms,d.min_level),('alchemy',(('herb',5),),(('pill',1),),30000,1))
        self.assertEqual(self.registry.lookup(DefinitionKey('resources','pill')).display_name,'凝气丹')
        with self.assertRaises(FrozenInstanceError):d.duration_ms=24
        self.assertNotIn('alchemy',self.snapshot().domains)
        self.assertEqual(self.snapshot().time['day_length_ms'],DEFAULT_GAME_DAY_MS)
        self.assertEqual(self.snapshot().save_schema_version,1)
        with self.assertRaises(ValidationError):WorkApplication(self.store,self.registry,self.clock)

    def test_recipe_validation_types_bounds_schema_and_unknown_fields(self):
        base=json.loads(Path('src/data/recipes/alchemy.json').read_text())
        for key,value in [('duration_ms',True),('duration_ms',0),('duration_ms',1.5),('min_level',0),('inputs',{'herb':-1}),('inputs',{'herb':True}),('outputs',{}),('building_kind','field'),('random_success',1)]:
            p=json.loads(json.dumps(base));p['definitions'][0][key]=value
            with self.subTest(key=key),self.assertRaises(ValidationError):load_alchemy(json.dumps(p))
        base['schema_version']=2
        with self.assertRaises(ValidationError):load_alchemy(json.dumps(base))
        with self.assertRaises(ValidationError):load_alchemy('broken')

    def test_recipe_duplicate_and_missing_resource_references(self):
        p=json.loads(Path('src/data/recipes/alchemy.json').read_text());p['definitions'].append(p['definitions'][0])
        with self.assertRaises(DuplicateError):load_alchemy(json.dumps(p))
        for field in ('inputs','outputs'):
            p=json.loads(Path('src/data/recipes/alchemy.json').read_text());p['definitions'][0][field]={'unknown':1}
            with self.assertRaises(ValidationError):load_alchemy(json.dumps(p))
        with self.assertRaises(DuplicateError):load_alchemy('{"schema_version":1,"schema_version":1}')

    def test_display_name_not_identity_and_existing_definitions_unchanged(self):
        p=json.loads(Path('src/data/recipes/alchemy.json').read_text());p['definitions'][0]['display_name']='改名'
        r=load_alchemy(json.dumps(p));self.assertEqual(recipes.definition(r,'pill').machine_id,'pill')
        self.assertEqual(r.lookup(DefinitionKey('production','grain')).duration_ms,30000)
        self.assertEqual(r.lookup(DefinitionKey('production','ingot')).inputs,(('ore',3),))

    def test_start_consumes_exact_inputs_and_creates_single_shared_job(self):
        self.ready();before=self.snapshot();r=self.app.execute(self.start_request());s=self.snapshot()
        self.assertEqual(s.revision,before.revision+1);self.assertEqual(s.time,before.time)
        self.assertEqual(self.quantity('herb'),0);self.assertEqual(self.quantity('pill'),0)
        job=s.domains['production']['jobs'][self.alchemy]
        self.assertEqual((job['recipe_id'],job['workers'],job['due_ms'],job['status']),('pill',1,30000,'WORKING'))
        self.assertEqual(r.result['job_id'],job['job_id'])
        self.assertEqual(s.domains['disciples']['commitments'][job['job_id']]['workers'],{self.worker:1})
        self.assertEqual(before.domains['sect'],s.domains['sect'])

    def test_missing_ingredients_does_not_consume_create_hold_or_record(self):
        self.assign();self.stock('grant',{'herb':4});before=self.snapshot();cmd=self.start_request()
        with self.assertRaises(ValidationError):self.app.execute(cmd)
        self.assertEqual(before,self.snapshot());self.assertIsNone(self.store.receipt(before.save_id,before.generation,cmd.request_id))

    def test_missing_worker_does_not_consume_ingredients(self):
        self.stock('grant',{'herb':5});before=self.snapshot()
        with self.assertRaises(ValidationError):self.app.execute(self.start_request())
        self.assertEqual(before,self.snapshot())

    def test_wrong_missing_and_level_zero_building_rejected(self):
        self.ready();before=self.snapshot()
        for target in ('missing',self.field):
            with self.assertRaises((ValidationError,NotFoundError)):self.app.execute(self.start_request(building_id=target))
            self.assertEqual(before,self.snapshot())
        rows=thaw_json(self.state.domains['sect']);rows['buildings'][self.alchemy].update(level=0,construction_target=1)
        self.recreate(replace(self.state,domains={**self.state.domains,'sect':rows}));self.stock('grant',{'herb':5});before=self.snapshot()
        with self.assertRaises(ValidationError):self.app.execute(self.start_request())
        self.assertEqual(before,self.snapshot());view=self.app.query_alchemy(before.save_id,self.alchemy)
        self.assertIn('BUILDING_NOT_READY',view['recipes'][0]['blocking_reasons'])

    def test_invalid_recipe_and_external_power_payload_rejected(self):
        self.ready();before=self.snapshot()
        for key in ('unknown','grain','life_pill'):
            with self.assertRaises((ValidationError,NotFoundError)):self.app.execute(self.start_request(recipe_id=key))
        for extras in ({'workers':100},{'worker_power_milli':100000},{'danding_level':5}):
            with self.assertRaises(ValidationError):self.app.execute(self.start_request(**extras))
        self.assertEqual(before,self.snapshot())

    def test_unmigrated_progression_requirement_not_assumed_true(self):
        p=json.loads(Path('src/data/recipes/alchemy.json').read_text());p['definitions'][0]['unlock_realm']=1
        r=load_alchemy(json.dumps(p));app=AlchemyApplication(self.store,r,self.clock)
        s=new_state(r,last_settled_at_ms=1000);app.create(s)
        target=next(k for k,v in s.domains['sect']['buildings'].items() if v['definition_id']=='alchemy')
        cmd=Command(s.save_id,s.generation,s.revision,str(uuid4()),'alchemy_start',{'building_id':target,'recipe_id':'pill'})
        with self.assertRaises(ValidationError):app.execute(cmd)
        self.assertEqual(app.query(s.save_id),s)

    def test_work_progress_remaining_and_exact_once_delivery(self):
        self.ready();self.app.execute(self.start_request());self.advance(10000)
        view=self.app.query_alchemy(self.state.save_id,self.alchemy)['current']
        self.assertEqual((view['status'],view['remaining_ms'],view['job']['progress_milli']),('WORKING',20000,10000000))
        self.advance(20000);self.assertEqual(self.quantity('pill'),1)
        self.assertEqual(self.app.query_alchemy(self.state.save_id,self.alchemy)['current']['status'],'COMPLETE')
        before=self.snapshot();self.app.settle(self.request());self.assertEqual(self.snapshot(),before)
        self.advance(60000);self.assertEqual(self.quantity('pill'),1)

    def test_work_and_building_held_once_then_reusable(self):
        self.ready();self.stock('grant',{'herb':5});self.app.execute(self.start_request());before=self.snapshot()
        with self.assertRaises(ConflictError):self.app.execute(self.start_request())
        self.assertEqual(before,self.snapshot());self.advance(30000)
        self.assertEqual(self.snapshot().domains['disciples']['commitments'],{})
        self.app.execute(self.start_request());self.advance(30000);self.assertEqual(self.quantity('pill'),2)
        self.assertEqual(len(self.snapshot().domains['production']['jobs']),1)

    def test_mid_job_unassign_cannot_reuse_held_workers_then_releases(self):
        self.ready();self.app.execute(self.start_request());self.advance(10000)
        self.app.execute(self.command('work_unassign',{'worker_id':self.worker,'building_id':self.alchemy}))
        with self.assertRaises(ConflictError):self.assign(target=self.garden)
        self.advance(20000);self.assign(target=self.garden)
        self.assertEqual(self.quantity('pill'),1);self.assertEqual(self.snapshot().domains['disciples']['commitments'],{})

    def test_capacity_admission_personal_pills_and_coins_exempt(self):
        stock={'holdings':{'grain':7000,'herb':5,'coins':999999}}
        self.recreate(replace(self.state,domains={**self.state.domains,'inventory':stock}));self.assign()
        self.app.execute(self.start_request());self.advance(30000)
        self.assertEqual(self.quantity('pill'),1);self.assertEqual(self.quantity('coins'),999999)
        self.assertEqual(holdings.stock_size(self.snapshot().domains['inventory'],self.registry),7000)
        receipt=self.stock('grant',{'grain':1})
        self.assertEqual(self.quantity('grain'),7000)
        self.assertEqual(receipt.result['discarded'],{'grain':1})

    def test_start_preserves_other_pending_outputs_personal_pills_exempt(self):
        self.ready();self.assign(worker=self.farm,target=self.field,count=2);self.stock('grant',{'grain':6995})
        self.app.execute(self.command('production_start',{'building_id':self.field,'recipe_id':'grain','unlock_floor':0,'unlock_realm':0}))
        before=self.snapshot();field_job=before.domains['production']['jobs'][self.field]
        self.app.execute(self.start_request());after=self.snapshot()
        self.assertEqual(after.domains['production']['jobs'][self.field],field_job)
        self.assertNotIn('capacity_reserved',after.domains)
        self.assertEqual(after.domains['production']['jobs'][self.alchemy]['status'],'WORKING')

    def test_full_warehouse_personal_output_release_work_and_deliver_once(self):
        self.ready();self.app.execute(self.start_request());self.stock('grant',{'grain':7000});self.advance(30000)
        view=self.app.query_alchemy(self.state.save_id,self.alchemy)['current']
        self.assertEqual((view['status'],view['blocking_reason'],dict(view['expected_outputs'])),('COMPLETE',None,{'pill':1}))
        self.assertEqual(self.quantity('pill'),1);self.assertEqual(self.quantity('grain'),7000)
        self.assertEqual(self.snapshot().domains['disciples']['commitments'],{})
        before=self.snapshot();self.restart();self.app.settle(self.request());self.assertEqual(self.snapshot(),before)
        self.app.settle(self.request());self.assertEqual(self.quantity('pill'),1)

    def test_read_models_pure_no_clock_claim_or_receipt(self):
        self.ready();self.app.execute(self.start_request());before=self.snapshot();changes=self.store._connection.total_changes
        reads=self.clock.reads;self.clock.advance(100000)
        for _ in range(4):
            self.assertEqual(self.app.query_recipes(before.save_id)[0]['inputs_per_worker'],{'herb':5})
            v=self.app.query_alchemy(before.save_id,self.alchemy);self.assertEqual(v['current']['remaining_ms'],30000)
            self.assertIn('BUILDING_BUSY',v['recipes'][0]['blocking_reasons'])
        self.assertEqual(self.snapshot(),before);self.assertEqual(self.clock.reads,reads)
        self.assertEqual(self.store._connection.total_changes,changes)

    def test_full_chunked_pending_resume_same_gameplay_and_time(self):
        self.ready();self.assign(worker=self.farm,target=self.field);self.app.execute(self.start_request())
        self.app.execute(self.command('production_start',{'building_id':self.field,'recipe_id':'grain','unlock_floor':0,'unlock_realm':0}))
        s=self.snapshot();e=self.app.engine;full,_=e.advance(s,max_events=10,now_ms=61000)
        first,_=e.advance(s,max_events=10,now_ms=11000);chunked,_=e.advance(first,max_events=10,now_ms=61000)
        pending,r=e.advance(s,max_events=1,now_ms=61000);self.assertEqual(r.status,'PENDING')
        done,_=e.advance(pending,max_events=1,continuation=r.continuation)
        for candidate in (done,chunked):self.assertEqual(candidate.domains,full.domains);self.assertEqual(candidate.time,full.time)
        self.assertEqual(full.domains['inventory']['holdings']['pill'],1)

    def test_pending_restart_replay_and_resume(self):
        self.ready();self.assign(worker=self.farm,target=self.field);self.app.execute(self.start_request())
        self.app.execute(self.command('production_start',{'building_id':self.field,'recipe_id':'grain','unlock_floor':0,'unlock_realm':0}))
        self.clock.advance(60000);request=self.request(1);r=self.app.settle(request);self.assertEqual(r.result.status,'PENDING')
        before=self.snapshot();self.restart();self.assertEqual(self.app.settle(request),r);self.assertEqual(self.snapshot(),before)
        with self.assertRaises(ConflictError):self.app.execute(self.start_request())
        self.app.settle(self.request(1,Continuation.for_state(self.snapshot())))
        self.assertEqual(self.quantity('pill'),1);self.assertEqual(self.quantity('grain'),3)
        self.assertEqual(self.snapshot().domains['disciples']['commitments'],{})

    def test_offline_configured_cap_and_restart_no_repeat_or_autoproduction(self):
        self.ready();self.app.execute(self.start_request());self.restart();r=self.advance(100*3600000)
        self.assertEqual(r.result.accepted_ms,OFFLINE_CAP_MS);self.assertEqual(r.result.discarded_ms,100*3600000-OFFLINE_CAP_MS)
        self.assertEqual(self.quantity('pill'),1);self.assertEqual(self.snapshot().domains['disciples']['commitments'],{})
        before=self.snapshot();self.restart();self.app.settle(self.request());self.assertEqual(before,self.snapshot())

    def test_active_job_roundtrip_and_restart_receipt(self):
        self.ready();cmd=self.start_request();r=self.app.execute(cmd);self.advance(12000);s=self.snapshot()
        self.assertEqual(decode_state(encode_state(s)),s)
        self.restart();self.assertEqual(self.snapshot(),s);self.assertEqual(self.app.execute(cmd),r)
        self.advance(18000);self.assertEqual(self.quantity('pill'),1)

    def test_true_fresh_process_restart_preserves_active_pill(self):
        self.ready();self.app.execute(self.start_request());self.advance(12000);expected=self.snapshot().to_dict();self.store.close()
        code="import json,sys\nfrom pathlib import Path\nfrom src.application.alchemy import AlchemyApplication\nfrom src.data.recipes.alchemy import load_alchemy\nfrom src.core.save.sqlite import SQLiteSave\nfrom tests.fixtures.time import ManualClock\nwith SQLiteSave(Path(sys.argv[1]),allowed_root=Path(sys.argv[2])) as store:\n app=AlchemyApplication(store,load_alchemy(),ManualClock(13000))\n print(json.dumps(app.query(sys.argv[3]).to_dict()))\n"
        result=subprocess.run([sys.executable,'-B','-c',code,str(self.path),str(self.root),self.state.save_id],capture_output=True,text=True,check=True)
        self.assertEqual(json.loads(result.stdout),expected);self.restart();self.advance(18000);self.assertEqual(self.quantity('pill'),1)

    def test_start_replay_and_request_name_intent_conflict(self):
        self.ready();cmd=self.start_request();r=self.app.execute(cmd);s=self.snapshot();self.restart()
        self.assertEqual(self.app.execute(cmd),r);self.assertEqual(s,self.snapshot())
        for changed in (replace(cmd,payload={**cmd.payload,'recipe_id':'grain'}),replace(cmd,name='production_start',payload={**cmd.payload,'unlock_floor':0,'unlock_realm':0})):
            with self.assertRaises(ConflictError):self.app.execute(changed)
        self.assertEqual(s,self.snapshot())

    def test_stale_revision_generation_version_rejected(self):
        self.ready();cmd=self.start_request();self.stock('grant',{'coins':1});s=self.snapshot()
        for changed in (cmd,replace(cmd,expected_revision=s.revision,generation=2),replace(cmd,expected_revision=s.revision,version=2)):
            with self.assertRaises((ConflictError,ValidationError)):self.app.execute(changed)
        self.assertEqual(self.snapshot(),s)

    def test_start_transaction_failure_rolls_back_all_domains_counters_receipt(self):
        self.ready();before=self.snapshot();cmd=self.start_request();real=self.store.commit
        def fail(*args):real(*args);raise RuntimeError('TEST after write')
        with patch.object(self.store,'commit',side_effect=fail),self.assertRaises(RuntimeError):self.app.execute(cmd)
        self.assertEqual(before,self.snapshot());self.assertIsNone(self.store.receipt(before.save_id,before.generation,cmd.request_id))
        self.app.execute(cmd);self.assertEqual(self.quantity('herb'),0)

    def test_completion_transaction_failure_rolls_back_grant_release_receipt(self):
        self.ready();self.app.execute(self.start_request());before=self.snapshot();self.clock.advance(30000)
        cmd=self.request();real=self.store.commit
        def fail(*args):real(*args);raise RuntimeError('TEST after grant')
        with patch.object(self.store,'commit',side_effect=fail),self.assertRaises(RuntimeError):self.app.settle(cmd)
        self.assertEqual(self.snapshot(),before);self.assertEqual(self.quantity('pill'),0)
        self.assertIsNone(self.store.receipt(before.save_id,before.generation,cmd.request_id))
        self.app.settle(cmd);self.assertEqual(self.quantity('pill'),1)
        self.assertEqual(self.snapshot().domains['disciples']['commitments'],{})

    def test_definition_and_building_reference_corruption_rejected_on_load(self):
        self.ready();self.app.execute(self.start_request());s=self.snapshot()
        for field,value in [('recipe_id','unknown'),('due_ms',1),('workers',True)]:
            p=thaw_json(s.domains['production']);p['jobs'][self.alchemy][field]=value
            with self.assertRaises((ValidationError,NotFoundError)):self.app.foundation.validate_state(replace(s,domains={**s.domains,'production':p}))
        p=thaw_json(s.domains['sect']);del p['buildings'][self.alchemy]
        with self.assertRaises((ValidationError,NotFoundError)):self.app.foundation.validate_state(replace(s,domains={**s.domains,'sect':p}))
        p=thaw_json(s.domains['production']);p['jobs'][self.alchemy]['recipe_id']='unknown'
        corrupt=replace(s,domains={**s.domains,'production':p});row=encode_state(corrupt)
        self.store._connection.execute('UPDATE current SET body=?,digest=? WHERE save_id=?',(row[6],row[7],s.save_id))
        with self.assertRaises(CorruptSaveError):self.snapshot()

    def test_recovery_restores_coherent_active_batch_and_rejects_old_requests(self):
        self.ready();cmd=self.start_request();self.app.execute(cmd);self.advance(10000);source=self.snapshot();self.app.checkpoint(source.save_id)
        self.advance(20000);self.assertEqual(self.quantity('pill'),1)
        recovery=RecoveryApplication(self.app.foundation,self.clock);o=recovery.inspect(source.save_id)
        request=RecoveryRequest(source.save_id,o.current_generation,o.current_fingerprint,o.source_fingerprint,str(uuid4()),'TEST alchemy restore')
        result=recovery.recover(request);self.assertEqual(result.status,'SUCCESS')
        restored=self.snapshot();self.assertEqual(restored.domains,source.domains);self.assertEqual(restored.generation,2);self.assertEqual(restored.revision,0)
        with self.assertRaises(ConflictError):self.app.execute(cmd)
        self.restart();self.app.settle(self.request());self.assertEqual(self.quantity('pill'),0)
        self.advance(20000);self.assertEqual(self.quantity('pill'),1)
        self.stock('grant',{'herb':5});new=self.app.execute(self.start_request());self.assertIn(':2:i:',new.result['job_id'])
        self.advance(30000);self.assertEqual(self.quantity('pill'),2)

    def test_recovery_of_personal_output_delivers_exact_once(self):
        self.ready();self.app.execute(self.start_request());self.stock('grant',{'grain':7000});self.advance(30000)
        source=self.snapshot();self.app.checkpoint(source.save_id);self.stock('consume',{'grain':1});self.app.settle(self.request())
        recovery=RecoveryApplication(self.app.foundation,self.clock);o=recovery.inspect(source.save_id)
        recovery.recover(RecoveryRequest(source.save_id,o.current_generation,o.current_fingerprint,o.source_fingerprint,str(uuid4()),'TEST blocked output'))
        self.assertEqual(self.snapshot().domains,source.domains);self.assertEqual(self.quantity('pill'),1)
        self.stock('consume',{'grain':1});self.app.settle(self.request());self.app.settle(self.request());self.assertEqual(self.quantity('pill'),1)

    def test_non_specialist_capability_valid_and_level_yield_from_building_authority(self):
        rows=thaw_json(self.state.domains['sect']);rows['buildings'][self.alchemy]['level']=10
        self.recreate(replace(self.state,domains={**self.state.domains,'sect':rows}));self.assign(worker=self.farm,count=2);self.stock('grant',{'herb':10})
        view=self.app.query_alchemy(self.state.save_id,self.alchemy);self.assertEqual(view['recipes'][0]['batch_outputs'],{'pill':2})
        self.app.execute(self.start_request());job=self.snapshot().domains['production']['jobs'][self.alchemy]
        self.assertEqual(job['yield_milli'],2900);self.assertNotIn('building_level_copy',job)
        self.advance(30000);self.assertEqual(self.quantity('pill'),2)

    def test_second_connection_cannot_start_same_revision_or_double_charge(self):
        self.ready();first=self.start_request();second=self.start_request()
        with SQLiteSave(self.path,allowed_root=self.root) as store:
            other=AlchemyApplication(store,load_alchemy(),self.clock)
            result=self.app.execute(first)
            with self.assertRaises(ConflictError):other.execute(second)
            self.assertEqual(other.execute(first),result)
        self.assertEqual(self.quantity('herb'),0);self.assertEqual(len(self.snapshot().domains['disciples']['commitments']),1)

    def test_completion_receipt_replays_after_restart_without_revision_or_reward(self):
        self.ready();self.app.execute(self.start_request());self.clock.advance(30000)
        request=self.request();receipt=self.app.settle(request);before=self.snapshot();self.restart()
        self.assertEqual(self.app.settle(request),receipt);self.assertEqual(self.snapshot(),before)
        self.assertEqual(self.quantity('pill'),1)

"""Real migrated resource rules; TEST callers/SQLite only, no V1 runtime/import."""
from dataclasses import replace, FrozenInstanceError
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest
from uuid import uuid4
from unittest.mock import patch

from src.application import inventory
from src.application.memory import Command
from src.application.recovery import RecoveryApplication
from src.core.save.codec import CorruptSaveError
from src.core.save.recovery import RecoveryRequest
from src.core.save.sqlite import SQLiteSave, V2_ROOT
from src.core.validation import ConflictError, DuplicateError, NotFoundError, ValidationError
from src.data.items.resources import load_resources, warehouse_capacity
from src.data.registry import DefinitionKey, DefinitionRegistry
from src.systems.inventory import holdings, operations
from tests.fixtures.time import ManualClock


class InventoryRules(unittest.TestCase):
    def setUp(self):
        self.registry = load_resources()
        self.state = inventory.new_state(self.registry, last_settled_at_ms=10)
        self.app = inventory.memory(self.state, self.registry, capacity=7000)

    def command(self, amounts, name='inventory_grant', **changes):
        s=self.app.query()
        args=dict(save_id=s.save_id,generation=s.generation,expected_revision=s.revision,
                  request_id=str(uuid4()),name=name,payload={'amounts':amounts})
        args.update(changes)
        return Command(**args)

    def qty(self,key):
        return inventory.query_quantity(self.app,self.registry,key)

    def test_real_definitions_and_all_mapping_ids(self):
        root=Path(__file__).resolve().parents[2]
        rows=json.loads((root/'docs/migration/INVENTORY_ID_MAPPING.json').read_text())
        self.assertEqual(len(rows),71)
        for row in rows:
            definition=self.registry.lookup(DefinitionKey('resources',row['v2_machine_id']))
            self.assertEqual(definition.display_name,{'ore':'凡铁矿','ingot':'铁锭','stone':'石材'}.get(row['v2_machine_id'],row['display_name']))
            self.assertEqual(row['v1_identifier'],definition.machine_id)
        self.assertEqual(self.registry.lookup(DefinitionKey('resources','ore')).display_name,'凡铁矿')

    def test_duplicate_definition_rejected(self):
        r=DefinitionRegistry(schema_version=1,content_version='test')
        d=self.registry.lookup(DefinitionKey('resources','herb'));r.register(d)
        with self.assertRaises(DuplicateError):r.register(d)

    def test_loader_rejects_bad_id_duplicate_and_invalid_metadata(self):
        p=json.loads(Path('src/data/items/resources.json').read_text())
        for field,value in [('machine_id','灵草'),('capacity_counted',1),('grade',False)]:
            bad=json.loads(json.dumps(p));bad['definitions'][0][field]=value
            with self.assertRaises(ValidationError):load_resources(json.dumps(bad))
        p['definitions'].append(p['definitions'][0])
        with self.assertRaises(DuplicateError):load_resources(json.dumps(p))
        with self.assertRaises(DuplicateError):load_resources('{"schema_version":1,"schema_version":1}')

    def test_display_name_not_identity(self):
        d=self.registry.lookup(DefinitionKey('resources','herb'));renamed=replace(d,display_name='灵草新展示名')
        self.assertEqual(d.key,renamed.key)
        r=DefinitionRegistry(schema_version=1,content_version=self.registry.content_version);r.register(renamed);r.seal()
        p,_=operations.grant(holdings.initial(),r,{'herb':3},capacity=3)
        self.assertEqual(holdings.get_quantity(p,r,'herb'),3)

    def test_empty_and_defined_unheld(self):
        holdings.validate(holdings.initial(),self.registry)
        self.assertEqual(self.qty('herb'),0)
        self.assertFalse(holdings.has(holdings.initial(),self.registry,'herb'))

    def test_unknown_query(self):
        with self.assertRaises(NotFoundError):self.qty('no_such_resource')

    def test_grant_and_revision(self):
        receipt=self.app.execute(self.command({'herb':73}))
        self.assertEqual(self.qty('herb'),73);self.assertEqual(receipt.committed_revision,1)

    def test_consume_exact_removes_zero(self):
        self.app.execute(self.command({'herb':3}));self.app.execute(self.command({'herb':3},'inventory_consume'))
        self.assertEqual(self.qty('herb'),0)
        self.assertNotIn('herb',self.app.query().domains['inventory']['holdings'])
        self.assertEqual(self.app.query().revision,2)

    def test_consume_partial(self):
        self.app.execute(self.command({'ore':18}));self.app.execute(self.command({'ore':7},'inventory_consume'))
        self.assertEqual(self.qty('ore'),11)

    def test_insufficient_batch_is_atomic(self):
        self.app.execute(self.command({'herb':5,'ore':1}));before=self.app.query();receipts=self.app.receipts()
        with self.assertRaises(operations.InsufficientResources):self.app.execute(self.command({'herb':3,'ore':2},'inventory_consume'))
        self.assertIs(self.app.query(),before);self.assertEqual(self.app.receipts(),receipts)

    def test_multi_resource_grant_consume(self):
        self.app.execute(self.command({'herb':5,'ore':3,'coins':100}))
        self.app.execute(self.command({'herb':2,'ore':3,'coins':10},'inventory_consume'))
        self.assertEqual(dict(holdings.project(self.app.query().domains['inventory'],self.registry)),{'coins':90,'herb':3})

    def test_invalid_quantities_never_mutate(self):
        for amount in [-1,1.5,True,'2',None]:
            before=self.app.query()
            for name in ['inventory_grant','inventory_consume']:
                with self.assertRaises(ValidationError):self.app.execute(self.command({'herb':amount},name))
                self.assertIs(self.app.query(),before)

    def test_invalid_state_and_zero_entries_rejected(self):
        for p in [{'holdings':{'herb':0}},{'holdings':{'herb':-1}},{'holdings':{'herb':True}},{'holdings':[]},{'holdings':{},'target_stock':200}]:
            with self.assertRaises(ValidationError):holdings.validate(p,self.registry)

    def test_invalid_reference_rejects_entire_grant(self):
        before=self.app.query()
        with self.assertRaises(NotFoundError):self.app.execute(self.command({'herb':5,'no_such_resource':1}))
        self.assertIs(self.app.query(),before)

    def test_invalid_reference_even_zero(self):
        with self.assertRaises(NotFoundError):self.app.execute(self.command({'no_such_resource':0}))

    def test_zero_and_empty_intents_no_revision(self):
        for intent in [{},{'herb':0}]:
            self.app.execute(self.command(intent))
            self.assertEqual(self.app.query().revision,0)
            self.assertEqual(dict(self.app.query().domains['inventory']['holdings']),{})

    def test_capacity_formula(self):
        self.assertEqual(warehouse_capacity(0),5000);self.assertEqual(warehouse_capacity(2),9000)
        with self.assertRaises(ValidationError):warehouse_capacity(-1)

    def test_overflow_reports_accepted_discarded(self):
        result=self.app.execute(self.command({'herb':8000})).result
        self.assertEqual(result['accepted']['herb'],7000);self.assertEqual(result['discarded']['herb'],1000)
        self.assertEqual(self.qty('herb'),7000)

    def test_currency_exempt_no_artificial_cap(self):
        self.app.execute(self.command({'herb':7000,'coins':10**50}))
        self.assertEqual(self.qty('coins'),10**50)
        self.assertEqual(holdings.stock_size(self.app.query().domains['inventory'],self.registry),7000)

    def test_all_capacity_metadata_and_pill_grade(self):
        package=json.loads(Path('src/data/items/resources.json').read_text())
        self.assertEqual([d['machine_id'] for d in package['definitions'] if not d['capacity_counted']],['coins'])
        self.assertEqual(self.registry.lookup(DefinitionKey('resources','pill')).grade,9)
        self.assertEqual(self.registry.lookup(DefinitionKey('resources','pill')).display_name,'凝气丹')

    def test_overcapacity_keeps_existing_and_allows_consume(self):
        p,_=operations.grant(holdings.initial(),self.registry,{'herb':10},capacity=10)
        after,result=operations.grant(p,self.registry,{'herb':2,'coins':3},capacity=5)
        self.assertEqual(after['holdings']['herb'],10);self.assertEqual(result['discarded']['herb'],2)
        after,_=operations.consume(after,self.registry,{'herb':6});self.assertEqual(after['holdings']['herb'],4)

    def test_capacity_batch_order_deterministic(self):
        p=holdings.initial()
        a,_=operations.grant(p,self.registry,{'ore':4,'herb':4},capacity=5)
        b,_=operations.grant(p,self.registry,{'herb':4,'ore':4},capacity=5)
        self.assertEqual(a,b);self.assertEqual(a['holdings']['herb'],4)

    def test_grant_replay_and_different_intent(self):
        cmd=self.command({'herb':2});first=self.app.execute(cmd)
        self.assertEqual(self.app.execute(cmd),first);self.assertEqual(self.qty('herb'),2)
        with self.assertRaises(ConflictError):self.app.execute(replace(cmd,payload={'amounts':{'herb':3}}))

    def test_consume_replay(self):
        self.app.execute(self.command({'herb':5}));cmd=self.command({'herb':2},'inventory_consume')
        self.app.execute(cmd);rev=self.app.query().revision;self.app.execute(cmd)
        self.assertEqual(self.qty('herb'),3);self.assertEqual(self.app.query().revision,rev)

    def test_stale_revision_and_generation(self):
        for changes in [{'expected_revision':9},{'generation':2}]:
            with self.assertRaises(ConflictError):self.app.execute(self.command({'herb':2},**changes))
        self.assertEqual(self.qty('herb'),0)

    def test_query_and_mutation_never_advance_time(self):
        before=self.app.query();self.qty('herb');holdings.project(before.domains['inventory'],self.registry)
        self.assertIs(self.app.query(),before);self.assertEqual(self.app.receipts(),())
        self.app.execute(self.command({'herb':2}));self.assertEqual(self.app.query().time,before.time)
        self.assertEqual(self.app.query().generation,before.generation)

    def test_authority_and_definitions_immutable(self):
        self.app.execute(self.command({'herb':2}));s=self.app.query()
        with self.assertRaises(TypeError):s.domains['inventory']['holdings']['herb']=99
        with self.assertRaises(TypeError):holdings.project(s.domains['inventory'],self.registry)['herb']=99
        d=self.registry.lookup(DefinitionKey('resources','herb'))
        with self.assertRaises(FrozenInstanceError):d.display_name='changed'
        self.assertEqual(self.qty('herb'),2)

    def test_payload_only_amounts_no_policy_or_visual(self):
        for field in ['target_stock','reserve_stock','production_priority','scene_position']:
            cmd=self.command({'herb':1});cmd=replace(cmd,payload={'amounts':{'herb':1},field:5})
            with self.assertRaises(ValidationError):self.app.execute(cmd)


class InventoryPersistence(unittest.TestCase):
    def setUp(self):
        root=V2_ROOT/'.tmp';root.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(prefix='phase8-',dir=root)
        self.root=Path(self.temp.name);self.path=self.root/'test.sqlite3'
        self.store=SQLiteSave.initialize(self.path,allowed_root=self.root)
        self.registry=load_resources();self.app=inventory.persistent(self.store,self.registry,capacity=7000)
        self.state=inventory.new_state(self.registry,last_settled_at_ms=10);self.save_id=self.state.save_id
        self.app.create(self.state)

    def tearDown(self):
        self.store.close();self.temp.cleanup();self.assertFalse(self.root.exists())

    def snapshot(self):return self.app.query(self.save_id)

    def command(self,amounts,name='inventory_grant',**changes):
        s=self.snapshot();args=dict(save_id=s.save_id,generation=s.generation,expected_revision=s.revision,
          request_id=str(uuid4()),name=name,payload={'amounts':amounts});args.update(changes);return Command(**args)

    def restart(self):
        self.store.close();self.store=SQLiteSave(self.path,allowed_root=self.root)
        self.registry=load_resources();self.app=inventory.persistent(self.store,self.registry,capacity=7000)

    def test_round_trip_no_embedded_definition(self):
        self.app.execute(self.command({'herb':73,'ore':18,'coins':1250}));before=self.snapshot();self.restart()
        self.assertEqual(self.snapshot(),before)
        self.assertEqual(self.snapshot().domains['inventory']['holdings'],{'herb':73,'ore':18,'coins':1250})
        self.assertNotIn('display_name',json.dumps(self.snapshot().to_dict()))
        self.assertEqual(self.snapshot().save_schema_version,1)

    def test_restart_grant_and_consume_idempotency(self):
        grant=self.command({'herb':10});self.app.execute(grant)
        consume=self.command({'herb':3},'inventory_consume');self.app.execute(consume);before=self.snapshot()
        self.restart();self.app.execute(grant);self.app.execute(consume)
        self.assertEqual(self.snapshot(),before)
        with self.assertRaises(ConflictError):self.app.execute(replace(grant,payload={'amounts':{'herb':11}}))

    def test_failed_batch_keeps_persisted_state_revision_receipts(self):
        self.app.execute(self.command({'herb':5,'ore':1}));before=self.snapshot();cmd=self.command({'herb':3,'ore':2},'inventory_consume')
        with self.assertRaises(operations.InsufficientResources):self.app.execute(cmd)
        self.assertIsNone(self.store.receipt(self.save_id,1,cmd.request_id));self.restart();self.assertEqual(self.snapshot(),before)

    def test_sqlite_failure_rolls_back_state_and_receipt(self):
        before=self.snapshot();cmd=self.command({'herb':2});commit=self.store.commit
        def fail(*args):commit(*args);raise RuntimeError('TEST failure after writes before commit')
        with patch.object(self.store,'commit',side_effect=fail):
            with self.assertRaises(RuntimeError):self.app.execute(cmd)
        self.assertEqual(self.snapshot(),before);self.assertIsNone(self.store.receipt(self.save_id,1,cmd.request_id))

    def test_query_has_no_writes_receipts_or_claim(self):
        before=self.snapshot();count=self.store._connection.total_changes
        for _ in range(3):self.assertEqual(inventory.query_quantity(self.app,self.registry,'herb',save_id=self.save_id),0)
        self.assertEqual(self.snapshot(),before);self.assertEqual(self.store._connection.total_changes,count)

    def test_zero_canonical_after_restart(self):
        self.app.execute(self.command({'herb':3}));self.app.execute(self.command({'herb':3},'inventory_consume'));self.restart()
        self.assertNotIn('herb',self.snapshot().domains['inventory']['holdings'])
        self.assertEqual(inventory.query_quantity(self.app,self.registry,'herb',save_id=self.save_id),0)

    def test_unknown_definition_load_detected_not_repaired(self):
        bad=replace(self.state,save_id=str(uuid4()),domains={'inventory':{'holdings':{'no_such_resource':1}}})
        with self.store.transaction():self.store.create(bad)
        self.save_id=bad.save_id
        self.assertEqual(self.app.inspect(self.save_id).status,'CURRENT_INVALID_NO_RECOVERY')
        with self.assertRaises(CorruptSaveError):self.snapshot()

    def test_recovery_restores_inventory_and_invalidates_old_requests(self):
        self.app.execute(self.command({'herb':5,'coins':7}));self.app.checkpoint(self.save_id)
        old=self.command({'herb':3});self.app.execute(old)
        clock=ManualClock(100);recovery=RecoveryApplication(self.app,clock);obs=recovery.inspect(self.save_id)
        result=recovery.recover(RecoveryRequest(self.save_id,obs.current_generation,obs.current_fingerprint,
          obs.source_fingerprint,str(uuid4()),'TEST Inventory recovery'))
        self.assertEqual(result.status,'SUCCESS');self.restart();s=self.snapshot()
        self.assertEqual(s.domains['inventory']['holdings'],{'herb':5,'coins':7})
        self.assertEqual((s.generation,s.revision),(2,0));self.assertEqual(s.time['sim_time_ms'],0)
        self.assertEqual(s.time['last_settled_at_ms'],100)
        with self.assertRaises(ConflictError):self.app.execute(old)
        self.app.execute(self.command({'herb':1}));self.assertEqual(self.snapshot().revision,1)
        self.app.checkpoint(self.save_id)
        self.assertEqual(RecoveryApplication(self.app,clock).inspect(self.save_id).status,'READY')

    def test_definition_rename_round_trip(self):
        self.app.execute(self.command({'herb':1}));r=DefinitionRegistry(schema_version=1,content_version=self.registry.content_version)
        for row in json.loads(Path('src/data/items/resources.json').read_text())['definitions']:
            d=self.registry.lookup(DefinitionKey('resources',row['machine_id']))
            r.register(replace(d,display_name='修改展示名') if d.machine_id=='herb' else d)
        r.seal();app=inventory.persistent(self.store,r,capacity=7000)
        self.assertEqual(app.query(self.save_id).domains['inventory']['holdings']['herb'],1)

    def test_malformed_inventory_load_is_detected(self):
        for partition in [{'holdings':{'herb':0}},{'bad':{}},{'holdings':[]}, {'holdings':{'herb':-1}}]:
            bad=replace(self.state,revision=1,domains={'inventory':partition})
            # Fresh isolated Save identity for each deliberately corrupt semantic payload.
            bad=replace(bad,save_id=str(uuid4()),revision=0)
            with self.store.transaction():self.store.create(bad)
            self.assertEqual(self.app.inspect(bad.save_id).status,'CURRENT_INVALID_NO_RECOVERY')

    def test_invalid_batch_never_leaks_to_persistence(self):
        before=self.snapshot()
        for amounts in [{'herb':5,'ore':-1},{'herb':5,'ore':True}]:
            with self.assertRaises(ValidationError):self.app.execute(self.command(amounts))
            self.assertEqual(self.snapshot(),before)

    def test_real_subprocess_restart_reads_and_replays(self):
        cmd=self.command({'herb':73});self.app.execute(cmd);self.store.close()
        script='import json,sys\nfrom pathlib import Path\nfrom src.application import inventory\nfrom src.application.memory import Command\nfrom src.core.save.sqlite import SQLiteSave\nfrom src.data.items.resources import load_resources\nfrom src.core.state.envelope import thaw_json\nwith SQLiteSave(Path(sys.argv[1]),allowed_root=Path(sys.argv[2])) as store:\n app=inventory.persistent(store,load_resources(),capacity=7000)\n app.execute(Command(**json.loads(sys.argv[3])))\n state=app.query(sys.argv[4]);print(json.dumps(state.to_dict()))\n'
        args={'save_id':cmd.save_id,'generation':cmd.generation,'expected_revision':cmd.expected_revision,
              'request_id':cmd.request_id,'name':cmd.name,'payload':{'amounts':{'herb':73}}}
        run=subprocess.run([sys.executable,'-B','-c',script,str(self.path),str(self.root),json.dumps(args),self.save_id],capture_output=True,text=True,check=True)
        state=json.loads(run.stdout);self.assertEqual(state['revision'],1)
        self.assertEqual(state['domains']['inventory']['holdings'],{'herb':73})

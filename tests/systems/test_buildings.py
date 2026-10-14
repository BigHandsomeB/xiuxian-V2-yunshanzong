"""TEST ONLY building facts/quotes; no pretend gameplay upgrade or construction engine."""
from dataclasses import replace,FrozenInstanceError
from pathlib import Path
from uuid import uuid4
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from src.application import sect
from src.application.memory import Command,CommandSpec
from src.application.persistent import PersistentApplication
from src.application.recovery import RecoveryApplication
from src.core.save.recovery import RecoveryRequest
from src.core.save.sqlite import SQLiteSave,V2_ROOT
from src.core.state.envelope import thaw_json
from src.core.validation import ValidationError,ConflictError,DuplicateError,NotFoundError
from src.data.buildings.definitions import load_content,BuildingDefinition
from src.data.registry import DefinitionKey,DefinitionRegistry
from src.systems.sect import buildings,rules
from tests.fixtures.time import ManualClock


def fixture_complete_level(partition,payload):
    """TEST isolated changed authoritative facts, NOT a gameplay Upgrade Command."""
    key=payload['instance_id'];partition['buildings'][key]['level']=payload['level']
    partition['buildings'][key]['construction_target']=None
    return {'test_fact_change':True}


class BuildingRules(unittest.TestCase):
    def setUp(self):
        self.registry=load_content();self.state=sect.new_state(self.registry,last_settled_at_ms=10)
        self.partition=self.state.domains['sect']
        self.warehouse=next(k for k,v in self.partition['buildings'].items() if v['definition_id']=='warehouse')

    def fact(self,level=1,target=None):
        p=thaw_json(self.partition)
        p['buildings'][self.warehouse].update(level=level,construction_target=target)
        return p

    def test_real_definitions_mapping_and_ids(self):
        rows=json.loads(Path('docs/migration/BUILDING_ID_MAPPING.json').read_text())
        current=[row for row in rows if row['migration_status']=='MIGRATE']
        self.assertEqual(len(current),21)
        for row in current:
            d=self.registry.lookup(DefinitionKey('buildings',row['v2_machine_id']))
            self.assertEqual(d.display_name,row['display_name']);self.assertEqual(d.max_level,10)
        self.assertEqual(self.registry.lookup(DefinitionKey('buildings','warehouse')).display_name,'万宝库')

    def test_duplicate_and_invalid_ids_rejected(self):
        p=json.loads(Path('src/data/buildings/buildings.json').read_text());p['definitions'].append(p['definitions'][0])
        with self.assertRaises(DuplicateError):load_content(json.dumps(p))
        p['definitions'].pop();p['definitions'][0]['machine_id']='仓库'
        with self.assertRaises(ValidationError):load_content(json.dumps(p))

    def test_schema_and_instance_counter_validation(self):
        package=json.loads(Path('src/data/buildings/buildings.json').read_text())
        package['schema_version']=True
        with self.assertRaises(ValidationError):load_content(json.dumps(package))
        bad=replace(self.state,identity={**self.state.identity,'instance_counter':0})
        with self.assertRaises(ValidationError):buildings.references(bad)

    def test_cost_references_sealed(self):
        p=json.loads(Path('src/data/buildings/buildings.json').read_text());p['definitions'][0]['cost']['unknown_resource']=1
        with self.assertRaises(ValidationError):load_content(json.dumps(p))

    def test_default_twelve_instances_and_two_houses(self):
        buildings.validate(self.partition,self.registry,save_id=self.state.save_id)
        rows=self.partition['buildings'];self.assertEqual(len(rows),12)
        self.assertEqual(sum(v['definition_id']=='house' for v in rows.values()),2)
        self.assertTrue(all(v['level']==1 and v['construction_target'] is None for v in rows.values()))
        self.assertEqual(self.state.identity['instance_counter'],12)

    def test_level_validation(self):
        for level in [-1,1.5,True,'1',11]:
            with self.subTest(level=level),self.assertRaises(ValidationError):buildings.validate(self.fact(level),self.registry)
        for level in [1,2,10]:buildings.validate(self.fact(level),self.registry)

    def test_zero_only_initial_construction(self):
        with self.assertRaises(ValidationError):buildings.validate(self.fact(0),self.registry)
        p=self.fact(0,1);buildings.validate(p,self.registry)
        self.assertEqual(buildings.capability(p,self.registry)['warehouse_levels'],0)
        self.assertNotIn(self.warehouse,buildings.capability(p,self.registry)['effective_levels'])

    def test_absent_building_not_level_zero_instance(self):
        p=self.fact();del p['buildings'][self.warehouse]
        self.assertEqual(buildings.capability(p,self.registry)['warehouse_levels'],0)
        with self.assertRaises(NotFoundError):buildings.get_level(p,self.registry,self.warehouse)

    def test_pending_upgrade_retains_old_effective_level(self):
        p=self.fact(2,3);buildings.validate(p,self.registry)
        self.assertEqual(buildings.capability(p,self.registry)['warehouse_levels'],2)
        with self.assertRaises(ValidationError):rules.quote_upgrade(p,self.registry,self.warehouse)

    def test_invalid_construction_target(self):
        for level,target in [(1,1),(1,3),(0,None),(10,11),(1,True)]:
            with self.assertRaises(ValidationError):buildings.validate(self.fact(level,target),self.registry)

    def test_unknown_reference(self):
        p=self.fact();p['buildings'][self.warehouse]['definition_id']='unknown'
        with self.assertRaises(NotFoundError):buildings.validate(p,self.registry)
        with self.assertRaises(NotFoundError):buildings.definition(self.registry,'unknown')

    def test_instance_owner_and_identity(self):
        with self.assertRaises(ValidationError):buildings.validate(self.partition,self.registry,save_id=str(uuid4()))
        for key in ['bad',self.state.save_id+':0:i:1',self.state.save_id+':1:i:0']:
            with self.assertRaises(ValidationError):buildings.instance_id(key)

    def test_state_policy_and_visual_fields_rejected(self):
        for field in ['target_stock','reserve_stock','production_priority','scene_position','workers','queue']:
            p=self.fact();p['buildings'][self.warehouse][field]=1
            with self.assertRaises(ValidationError):buildings.validate(p,self.registry)

    def test_definition_immutable_and_display_rename_identity(self):
        d=buildings.definition(self.registry,'warehouse')
        with self.assertRaises(FrozenInstanceError):d.display_name='changed'
        self.assertEqual(replace(d,display_name='新名称').key,d.key)
        with self.assertRaises(TypeError):self.partition['buildings'][self.warehouse]['level']=2
        self.assertEqual(d.max_level,10)

    def test_query_and_capability_no_side_effects(self):
        before=self.state.to_dict()
        self.assertEqual(buildings.get_level(self.partition,self.registry,self.warehouse),1)
        row=buildings.get_building(self.partition,self.registry,self.warehouse)
        with self.assertRaises(TypeError):row['level']=2
        buildings.capability(self.partition,self.registry)
        self.assertEqual(self.state.to_dict(),before)

    def test_capacity_level_zero_one_two_and_multiple_instances(self):
        for level,target,expected in [(0,1,5000),(1,None,7000),(2,None,9000),(10,None,25000)]:
            s=replace(self.state,domains={**self.state.domains,'sect':self.fact(level,target)})
            source=sect.capacity_source(s,self.registry)
            self.assertEqual(source['effective'],expected)
            self.assertEqual(source['warehouse_contribution'],level*2000)
        p=self.fact(2);p['buildings'][f'{self.state.save_id}:1:i:13']={'definition_id':'warehouse','level':3,'construction_target':None}
        source=sect.capacity_source(replace(self.state,domains={**self.state.domains,'sect':p}),self.registry)
        self.assertEqual(source['warehouse_levels'],5);self.assertEqual(source['effective'],15000)

    def test_capacity_not_persisted(self):
        self.assertNotIn('capacity',json.dumps(self.state.to_dict()))
        self.assertEqual(sect.capacity_source(self.state,self.registry),sect.capacity_source(self.state,self.registry))

    def test_unlock_requirements_explicit_progress_inputs(self):
        self.assertFalse(rules.can_build(self.registry,'cave',cleared_floor=20,realm=0))
        self.assertFalse(rules.can_build(self.registry,'cave',cleared_floor=19,realm=1))
        self.assertTrue(rules.can_build(self.registry,'cave',cleared_floor=20,realm=1))
        self.assertTrue(rules.can_build(self.registry,'warehouse',cleared_floor=0,realm=0))
        with self.assertRaises(ValidationError):rules.can_build(self.registry,'warehouse',cleared_floor=True,realm=0)

    def test_real_upgrade_quote_not_instant_upgrade(self):
        quote=rules.quote_upgrade(self.partition,self.registry,self.warehouse)
        self.assertEqual(quote['target_level'],2)
        self.assertEqual(dict(quote['cost']),{'coins':80,'wood':16,'stone':8})
        self.assertEqual(quote['construction_work_seconds'],120)
        self.assertEqual(self.partition['buildings'][self.warehouse]['level'],1)
        with self.assertRaises(ValidationError):rules.quote_upgrade(self.fact(10),self.registry,self.warehouse)

    def test_inventory_has_no_building_import(self):
        import ast
        for path in Path('src/systems/inventory').glob('*.py'):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node,ast.ImportFrom):
                    self.assertFalse('sect' in (node.module or ''));self.assertFalse('buildings' in (node.module or ''))


class BuildingPersistence(unittest.TestCase):
    def setUp(self):
        root=V2_ROOT/'.tmp';root.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(prefix='phase9-',dir=root);self.root=Path(self.temp.name)
        self.path=self.root/'test.sqlite3';self.store=SQLiteSave.initialize(self.path,allowed_root=self.root)
        self.registry=load_content();self.app=sect.SectApplication(self.store,self.registry)
        self.state=sect.new_state(self.registry,last_settled_at_ms=10);self.save_id=self.state.save_id
        self.warehouse=next(k for k,v in self.state.domains['sect']['buildings'].items() if v['definition_id']=='warehouse')
        self.app.create(self.state)

    def tearDown(self):self.store.close();self.temp.cleanup();self.assertFalse(self.root.exists())
    def snapshot(self):return self.app.query(self.save_id)

    def command(self,amounts,**changes):
        s=self.snapshot();args=dict(save_id=s.save_id,generation=s.generation,expected_revision=s.revision,
           request_id=str(uuid4()),name='inventory_grant',payload={'amounts':amounts});args.update(changes)
        return Command(**args)

    def fixture_command(self,level):
        cmd=self.command({})
        return replace(cmd,name='test_completed_building',payload={'instance_id':self.warehouse,'level':level})

    def fixture_app(self):
        return PersistentApplication(self.store,self.registry,{'test_completed_building':CommandSpec('sect',fixture_complete_level)},
                        references=sect.references,validators=sect.validators(self.registry))

    def set_fixture_level(self,level):return self.fixture_app().execute(self.fixture_command(level))

    def restart(self):
        self.store.close();self.store=SQLiteSave(self.path,allowed_root=self.root)
        self.registry=load_content();self.app=sect.SectApplication(self.store,self.registry)

    def test_application_derives_capacity_for_grant(self):
        self.set_fixture_level(2)
        result=self.app.execute(self.command({'herb':9500,'coins':50000}))
        self.assertEqual(result.result['accepted']['herb'],9000)
        self.assertEqual(self.snapshot().domains['inventory']['holdings']['coins'],50000)
        source=self.app.query_capacity(self.save_id)
        self.assertEqual((source['base'],source['warehouse_contribution'],source['effective']),(5000,4000,9000))

    def test_recomputed_capacity_after_restart(self):
        self.set_fixture_level(2);before=self.snapshot();self.restart()
        self.assertEqual(self.snapshot(),before);self.assertEqual(self.app.query_capacity(self.save_id)['effective'],9000)

    def test_query_does_not_write_or_advance_time(self):
        before=self.snapshot();writes=self.store._connection.total_changes
        for _ in range(3):self.app.query_capacity(self.save_id);buildings.get_level(before.domains['sect'],self.registry,self.warehouse)
        self.assertEqual(self.snapshot(),before);self.assertEqual(self.store._connection.total_changes,writes)
        self.assertEqual(before.time['last_settled_at_ms'],10)

    def test_overcapacity_preserved_and_diagnosed(self):
        self.set_fixture_level(2);self.app.execute(self.command({'herb':8500}))
        self.set_fixture_level(1)  # TEST fixture: normal gameplay offers no downgrade.
        before=self.snapshot();self.restart()
        self.assertEqual(self.app.query_capacity(self.save_id)['over_capacity'],1500)
        result=self.app.execute(self.command({'herb':1,'coins':2}))
        self.assertEqual(result.result['accepted']['herb'],0)
        self.assertEqual(self.snapshot().domains['inventory']['holdings']['herb'],8500)
        self.assertEqual(self.snapshot().time,before.time)
        cmd=self.command({'herb':2000},name='inventory_consume');self.app.execute(cmd)
        self.assertEqual(self.app.query_capacity(self.save_id)['over_capacity'],0)

    def test_capacity_projection_race_rejected(self):
        cmd=self.command({'herb':7500});original=sect.commands
        def racing(*args,**kwargs):
            self.set_fixture_level(2)
            return original(*args,**kwargs)
        with patch('src.application.sect.commands',side_effect=racing):
            with self.assertRaises(ConflictError):self.app.execute(cmd)
        self.assertEqual(dict(self.snapshot().domains['inventory']['holdings']),{})

    def test_restart_idempotency_and_global_revision(self):
        cmd=self.command({'herb':7});self.app.execute(cmd);before=self.snapshot();self.restart()
        self.app.execute(cmd);self.assertEqual(self.snapshot(),before)
        with self.assertRaises(ConflictError):self.app.execute(replace(cmd,payload={'amounts':{'herb':8}}))
        fact=self.fixture_command(2);self.fixture_app().execute(fact);before=self.snapshot();self.restart()
        self.fixture_app().execute(fact);self.assertEqual(self.snapshot(),before)

    def test_stale_revision_and_generation(self):
        for changes in [{'expected_revision':999},{'generation':2}]:
            with self.assertRaises(ConflictError):self.app.execute(self.command({'herb':1},**changes))
        self.assertEqual(self.snapshot().revision,0)

    def test_recovery_restores_both_and_invalidates_building_requests(self):
        self.app.execute(self.command({'herb':5}));self.app.checkpoint(self.save_id)
        old=self.fixture_command(2);self.fixture_app().execute(old)
        self.app.execute(self.command({'herb':7}));clock=ManualClock(100)
        recovery=RecoveryApplication(self.app.foundation,clock);obs=recovery.inspect(self.save_id)
        result=recovery.recover(RecoveryRequest(self.save_id,obs.current_generation,obs.current_fingerprint,
                      obs.source_fingerprint,str(uuid4()),'TEST coherent building inventory recovery'))
        self.assertEqual(result.status,'SUCCESS');self.restart();s=self.snapshot()
        self.assertEqual((s.generation,s.revision),(2,0))
        self.assertEqual(buildings.get_level(s.domains['sect'],self.registry,self.warehouse),1)
        self.assertEqual(s.domains['inventory']['holdings']['herb'],5)
        self.assertEqual(s.time['last_settled_at_ms'],100)
        with self.assertRaises(ConflictError):self.fixture_app().execute(old)
        self.set_fixture_level(2);self.assertEqual(self.snapshot().revision,1)
        self.app.execute(self.command({'herb':1}));self.assertEqual(self.snapshot().revision,2)

    def test_references_revalidated_and_foreign_instances_rejected(self):
        for row in [{'definition_id':'unknown','level':1,'construction_target':None},
                    {'definition_id':'warehouse','level':False,'construction_target':None}]:
            bad=replace(self.state,save_id=str(uuid4()),domains={**self.state.domains,'sect':{'buildings':{self.warehouse:row}}})
            with self.assertRaises(ValidationError):self.app.create(bad)
        p=thaw_json(self.state.domains['sect']);p['buildings'][self.warehouse]['definition_id']='unknown'
        bad=replace(self.state,domains={**self.state.domains,'sect':p})
        with self.assertRaises(NotFoundError):self.app.foundation.validate_state(bad)

    def test_no_definition_or_capacity_copies_in_save(self):
        raw=json.dumps(self.snapshot().to_dict())
        for field in ['display_name','max_level','capacity','workers','sprite','cost']:
            self.assertNotIn(field,raw)

    def test_no_fake_upgrade_command(self):
        with self.assertRaises(NotFoundError):self.app.execute(self.command({},name='building_upgrade'))
        self.assertEqual(self.snapshot().revision,0)

    def test_pending_fact_restart_keeps_old_capability(self):
        raw=self.state.to_dict();raw['domains']['sect']['buildings'][self.warehouse]['construction_target']=2
        pending=replace(self.state,save_id=str(uuid4()),domains=raw['domains'])
        # Entity IDs are tied to their Save; create a separate owned pending instance.
        pending=replace(pending,domains={'inventory':{'holdings':{}},'sect':{'buildings':{
            f'{pending.save_id}:1:i:1':{'definition_id':'warehouse','level':1,'construction_target':2}}}},
            identity={**pending.identity,'instance_counter':1})
        self.app.create(pending);self.restart()
        loaded=self.app.query(pending.save_id)
        self.assertEqual(loaded.domains['sect']['buildings'][f'{pending.save_id}:1:i:1']['construction_target'],2)
        self.assertEqual(self.app.query_capacity(pending.save_id)['effective'],7000)

    def test_real_subprocess_restart(self):
        self.set_fixture_level(2);self.app.execute(self.command({'herb':7}));self.store.close()
        script="import json,sys\nfrom pathlib import Path\nfrom src.application.sect import SectApplication\nfrom src.core.save.sqlite import SQLiteSave\nfrom src.data.buildings.definitions import load_content\nwith SQLiteSave(Path(sys.argv[1]),allowed_root=Path(sys.argv[2])) as store:\n app=SectApplication(store,load_content());s=app.query(sys.argv[3])\n print(json.dumps({'state':s.to_dict(),'capacity':app.query_capacity(s.save_id)}))\n"
        run=subprocess.run([sys.executable,'-B','-c',script,str(self.path),str(self.root),self.save_id],capture_output=True,text=True,check=True)
        result=json.loads(run.stdout);self.assertEqual(result['capacity']['effective'],9000)
        self.assertEqual(result['state']['domains']['inventory']['holdings']['herb'],7)
        self.assertEqual(result['state']['revision'],2)

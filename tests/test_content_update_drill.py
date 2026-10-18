"""A full content update rehearsal: original JSON loaders and real SQLite commands."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from src.application.ecology import EcologyApplication
from src.application import content_compatibility as preflight
from src.application.settlement import SettlementRequest
from src.core.save.sqlite import SQLiteSave, V2_ROOT
from src.core.state.envelope import thaw_json
from src.core.validation import ConflictError, ValidationError
from src.data import content_loader
from src.data.content_compatibility import package_evidence
from src.data.dungeons import catalog, expeditions, durability
from src.data.dungeons.definitions import load_dungeons
from src.data.item_effects import bindings_for, validate_bindings
from src.data.registry import DefinitionKey, DefinitionRegistry
from src.systems.dungeons import progress
from tests.fixtures.time import ManualClock
from tests.fixtures import content_update as drill
from tools.playable import game


class ContentUpdateDrillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = load_dungeons(management=True,cold_jade=True,ecology=True)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='content-update-drill-', dir=V2_ROOT/'tests')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root/'drill.sqlite3'
        self.clock = ManualClock()
        drill.prepare_package(self.root)

    def target(self):
        return self.enterContext(drill.package(self.root)).load()

    def create(self, store, *, active=True):
        app = EcologyApplication(store,self.source,self.clock)
        app.create(drill.synthetic_state(self.source,self.clock))
        state = app.query(drill.SAVE_ID)
        building = next(key for key,row in state.domains['sect']['buildings'].items() if row['definition_id']=='alchemy')
        drill.execute(app,'work_assign',{'building_id':building,'count':1})
        paid, receipt = drill.execute(app,'production_start',{'building_id':building,'recipe_id':'ju_qi_pill'})
        if active:
            drill.execute(app,'combat_start',{'encounter_id':'thorn_path_v2_030'})
        return app, building, paid, receipt

    def replay_unchanged(self, app, request, receipt):
        before = app.query(drill.SAVE_ID)
        self.assertEqual(app.execute(request), receipt)
        self.assertEqual(app.query(drill.SAVE_ID), before)

    def test_full_chain_migration_old_work_drops_craft_brew_effect_and_restart(self):
        # Source is created/paid before activating any temporary readers.
        with SQLiteSave.initialize(self.path,allowed_root=self.root) as store:
            old, building, paid, paid_receipt = self.create(store)
            before = old.query(drill.SAVE_ID)
            self.assertEqual(before.domains['combat']['battle']['status'],'ACTIVE')
            self.assertNotEqual(before.domains['equipment']['instances'],{})
            target = self.target()
            self.assertFalse(progress.unlocked(before.domains['dungeon'],target,drill.DUNGEON))
            with self.assertRaises(ConflictError):
                progress.choose(before.domains['dungeon'],target,drill.DUNGEON)
            migration = drill.command(old,'drill_upgrade')
            migrated = drill.migrate(store,self.clock,migration,self.source,target)
            app = EcologyApplication(store,target,self.clock)
            after = app.query(drill.SAVE_ID)
            self.assertEqual(after,replace(before,content_version=drill.VERSION,revision=before.revision+1))
            self.assertEqual(drill.migrate(store,self.clock,migration,self.source,target),migrated)
            self.replay_unchanged(app,paid,paid_receipt)
            # Finish the old battle under its saved player/growth/equipment snapshot.
            reward, reward_receipt = drill.win_and_claim(app)
            self.replay_unchanged(app,reward,reward_receipt)
            state = app.query(drill.SAVE_ID)
            self.assertEqual(state.domains['dungeon']['cleared_floor'],30)
            self.assertTrue(progress.unlocked(state.domains['dungeon'],target,drill.DUNGEON))
            old_job = before.domains['production']['jobs'][building]
            old_output = state.domains['inventory']['holdings'].get('ju_qi_pill',0)
            drill.drain(app,self.clock,old_job['due_ms']-state.time['sim_time_ms'])
            state = app.query(drill.SAVE_ID)
            self.assertEqual(state.domains['production']['jobs'][building]['status'],'COMPLETE')
            self.assertGreater(state.domains['inventory']['holdings'].get('ju_qi_pill',0),old_output)
            self.replay_unchanged(app,paid,paid_receipt)
            drill.execute(app,'dungeon_select',{'dungeon_id':drill.DUNGEON})
            state = app.query(drill.SAVE_ID)
            self.assertEqual(progress.selected(state.domains['dungeon']),drill.DUNGEON)
            drill.execute(app,'combat_start',{'encounter_id':drill.DUNGEON+'_v1_001'})
            reward, reward_receipt = drill.win_and_claim(app)
            self.replay_unchanged(app,reward,reward_receipt)
            state = app.query(drill.SAVE_ID)
            self.assertEqual(progress.cleared(state.domains['dungeon'],drill.DUNGEON),1)
            earned = durability.amount(4,state.domains['combat']['battle'],drill.MATERIAL)
            self.assertEqual(earned,11)  # Fixed battle identity and existing durability compensation.
            self.assertEqual(state.domains['inventory']['holdings'].get(drill.MATERIAL),earned)
            self.assertIn(state.domains['equipment']['latest_reward']['definition_id'],
                          {drill.DUNGEON+f'_equipment_{i:02d}' for i in range(1,13)})
            # Real equipment craft consumes the newly dropped material and a coin.
            coins = state.domains['inventory']['holdings']['coins']
            craft, crafted = drill.execute(app,'equipment_craft',{'equipment_id':drill.GEAR})
            state = app.query(drill.SAVE_ID)
            self.assertEqual(state.domains['inventory']['holdings'][drill.MATERIAL],earned-1)
            self.assertEqual(state.domains['inventory']['holdings']['coins'],coins-1)
            new_gear = state.domains['equipment']['instances'][crafted.result['instance_id']]
            self.assertEqual(new_gear['definition_id'],drill.GEAR)
            self.assertEqual(new_gear['roll_version'],drill.DUNGEON+'-roll-v1')
            self.replay_unchanged(app,craft,crafted)
            brew, brewed = drill.execute(app,'production_start',{'building_id':building,'recipe_id':drill.RECIPE})
            state = app.query(drill.SAVE_ID)
            self.assertEqual(state.domains['inventory']['holdings'][drill.MATERIAL],earned-2)
            self.assertEqual(state.domains['inventory']['holdings'].get(drill.TONIC,0),0)
            self.replay_unchanged(app,brew,brewed)
            due = state.domains['production']['jobs'][building]['due_ms']
            drill.drain(app,self.clock,due-state.time['sim_time_ms'])
            state = app.query(drill.SAVE_ID)
            self.assertEqual(state.domains['inventory']['holdings'][drill.TONIC],1)
            self.assertEqual(bindings_for(target)[('cultivation_use_pill',drill.TONIC)].effect_type,'cultivation_pill')
            self.assertNotIn('pill',drill.TONIC)
            xp = state.domains['cultivation']['total_xp']
            use, used = drill.execute(app,'cultivation_use_pill',{'item_id':drill.TONIC,'count':1})
            final = app.query(drill.SAVE_ID)
            self.assertEqual(final.domains['inventory']['holdings'].get(drill.TONIC,0),0)
            self.assertGreater(final.domains['cultivation']['total_xp'],xp)
            self.replay_unchanged(app,use,used)
            for identity, row in before.domains['equipment']['instances'].items():
                self.assertEqual(final.domains['equipment']['instances'][identity],row)
            self.assertGreater(final.identity['instance_counter'],before.identity['instance_counter'])
        with game.game_factory(self.path,self.root,registry=target,clock=self.clock,
                               application_class=EcologyApplication)() as app:
            self.assertEqual(app.query(drill.SAVE_ID),final)
            for request,receipt in ((paid,paid_receipt),(craft,crafted),(brew,brewed),(use,used),(reward,reward_receipt)):
                self.replay_unchanged(app,request,receipt)
        # New interpreter recreates the same isolated package and checks old/new receipts.
        requests = [paid,craft,brew,use,reward]
        serialized = [{'save_id':q.save_id,'generation':q.generation,'expected_revision':q.expected_revision,
                       'request_id':q.request_id,'name':q.name,'payload':thaw_json(q.payload),'version':q.version} for q in requests]
        (self.root/'requests.json').write_text(json.dumps(serialized))
        code = '''
import json,sys
from pathlib import Path
from src.application.ecology import EcologyApplication
from src.application.memory import Command
from src.core.save.sqlite import SQLiteSave
from tests.fixtures import content_update as d
from tests.fixtures.time import ManualClock
root=Path(sys.argv[1])
with d.package(root) as loader:
 registry=loader.load()
 with SQLiteSave(root/'drill.sqlite3',allowed_root=root) as store:
  app=EcologyApplication(store,registry,ManualClock(int(sys.argv[2])))
  before=app.query(d.SAVE_ID)
  for values in json.loads((root/'requests.json').read_text()):
   q=Command(**values);saved=store.receipt(d.SAVE_ID,q.generation,q.request_id)
   receipt=app.execute(q)
   assert receipt.committed_revision==saved.committed_revision
   assert receipt.result==saved.payload
  assert app.query(d.SAVE_ID)==before
  print(json.dumps(before.to_dict(),sort_keys=True))
'''
        child = subprocess.run([sys.executable,'-B','-c',code,str(self.root),str(self.clock.value)],
                               cwd=V2_ROOT,capture_output=True,text=True,timeout=30)
        self.assertEqual(child.returncode,0,child.stderr)
        self.assertEqual(json.loads(child.stdout),final.to_dict())

    def test_package_is_additive_and_formal_sources_caches_and_loader_are_restored(self):
        files = {p:hashlib.sha256(p.read_bytes()).hexdigest() for p in (V2_ROOT/'src/data').rglob('*.json')}
        official = package_evidence(self.source)
        pinned = content_loader.load_current()
        self.assertEqual(package_evidence(pinned),official)
        with drill.package(self.root) as loader:
            target = loader.load()
            delta = drill.assert_additive(self.source,target)
            self.assertEqual(len(delta['definitions']['added']),230)
            self.assertEqual(delta['effects'],{'added':['cultivation_use_pill:'+drill.TONIC], 'removed':[], 'modified':[]})
            self.assertEqual(len(catalog.registered_ids(target)),5)
            self.assertEqual(len(expeditions.content(drill.DUNGEON)['materials']),12)
            self.assertEqual(len(expeditions.content(drill.DUNGEON)['equipment']),12)
            self.assertIs(loader.load(),target)
        self.assertEqual(len(catalog.all_ids()),4)
        with self.assertRaises(ValidationError):expeditions.content(drill.DUNGEON)
        rebuilt = content_loader.ContentLoader().load()
        self.assertEqual(package_evidence(rebuilt),official)
        self.assertEqual(package_evidence(content_loader.load_current()),official)
        self.assertEqual(len(rebuilt._definitions),1529)
        self.assertEqual({p:hashlib.sha256(p.read_bytes()).hexdigest() for p in files},files)

    def test_pending_refused_then_settled_with_source_before_migration(self):
        with SQLiteSave.initialize(self.path,allowed_root=self.root) as store:
            old, _, _, _ = self.create(store)
            current = old.query(drill.SAVE_ID)
            mine = next(key for key,row in current.domains['sect']['buildings'].items() if row['definition_id']=='mine')
            drill.execute(old,'work_assign',{'building_id':mine,'count':1})
            drill.execute(old,'production_start',{'building_id':mine,'recipe_id':'ore'})
            self.clock.advance(600000)
            state = old.query(drill.SAVE_ID)
            old.settle(SettlementRequest(drill.SAVE_ID,state.generation,state.revision,str(uuid4()),1,None))
            before = old.query(drill.SAVE_ID)
            self.assertIsNotNone(before.time['pending'])
            target = self.target()
            request = drill.command(old,'drill_upgrade')
            with self.assertRaises(ConflictError):drill.migrate(store,self.clock,request,self.source,target)
            self.assertEqual(old.query(drill.SAVE_ID),before)
            self.assertIsNone(store.receipt(drill.SAVE_ID,before.generation,request.request_id))
            # Pending continuation is completed with the original registry and rules.
            drill.drain(old,self.clock)
            settled = old.query(drill.SAVE_ID)
            self.assertIsNone(settled.time['pending'])
            self.assertEqual(settled.content_version,drill.SOURCE_VERSION)
            request = drill.command(old,'drill_upgrade')
            drill.migrate(store,self.clock,request,self.source,target)
            self.assertEqual(EcologyApplication(store,target,self.clock).query(drill.SAVE_ID),
                             replace(settled,content_version=drill.VERSION,revision=settled.revision+1))

    def test_sql_commit_and_checkpoint_failures_roll_back_current_previous_and_receipt(self):
        target = self.target()
        with SQLiteSave.initialize(self.path,allowed_root=self.root) as store:
            old, _, _, _ = self.create(store)
            before = old.query(drill.SAVE_ID)
            with store.transaction():store.checkpoint(drill.SAVE_ID)
            recovery = store.inspect(drill.SAVE_ID).recovery
            rows = store.recovery_rows(drill.SAVE_ID)
            request = drill.command(old,'drill_upgrade')
            for stage in ('commit','checkpoint'):
                with self.subTest(stage=stage):
                    actual = getattr(store,stage)
                    calls = []
                    def failure(*args,**kwargs):
                        result = actual(*args,**kwargs);calls.append(True)
                        if stage=='commit' or len(calls)==2:
                            raise ValidationError('injected after SQL')
                        return result
                    with patch.object(store,stage,side_effect=failure):
                        with self.assertRaisesRegex(ValidationError,'injected after SQL'):
                            drill.migrate(store,self.clock,request,self.source,target)
                    self.assertEqual(old.query(drill.SAVE_ID),before)
                    self.assertEqual(store.inspect(drill.SAVE_ID).recovery,recovery)
                    self.assertEqual(store.recovery_rows(drill.SAVE_ID),rows)
                    self.assertIsNone(store.receipt(drill.SAVE_ID,before.generation,request.request_id))
            drill.migrate(store,self.clock,request,self.source,target)
            self.assertEqual(EcologyApplication(store,target,self.clock).query(drill.SAVE_ID).content_version,drill.VERSION)

    def test_migration_invalid_target_stale_generation_and_replay_intent_are_atomic(self):
        target = self.target()
        with SQLiteSave.initialize(self.path,allowed_root=self.root) as store:
            old, _, _, _ = self.create(store)
            before = old.query(drill.SAVE_ID)
            request = drill.command(old,'drill_upgrade')
            for bad in (replace(request,generation=before.generation+1),
                        replace(request,expected_revision=before.revision-1),
                        replace(request,payload={'unexpected':True})):
                with self.subTest(request=bad),self.assertRaises((ConflictError,ValidationError)):
                    drill.migrate(store,self.clock,bad,self.source,target)
                self.assertEqual(old.query(drill.SAVE_ID),before)
                self.assertIsNone(store.receipt(drill.SAVE_ID,before.generation,request.request_id))
            rows = store.recovery_rows(drill.SAVE_ID)
            actual = drill.EcologyApplication
            def invalid_target(store,registry,clock):
                app = actual(store,registry,clock)
                if registry is target:
                    def reject(_):
                        raise ValidationError('injected invalid target state')
                    app.foundation.validate_state = reject
                return app
            with patch.object(drill,'EcologyApplication',side_effect=invalid_target):
                with self.assertRaisesRegex(ValidationError,'injected invalid target'):
                    drill.migrate(store,self.clock,request,self.source,target)
            self.assertEqual(old.query(drill.SAVE_ID),before)
            self.assertEqual(store.recovery_rows(drill.SAVE_ID),rows)
            self.assertIsNone(store.receipt(drill.SAVE_ID,before.generation,request.request_id))
            result = drill.migrate(store,self.clock,request,self.source,target)
            app = EcologyApplication(store,target,self.clock)
            migrated = app.query(drill.SAVE_ID)
            self.assertEqual(drill.migrate(store,self.clock,request,self.source,target),result)
            with self.assertRaises(ValidationError):
                drill.migrate(store,self.clock,replace(request,payload={'changed':True}),self.source,target)
            self.assertEqual(app.query(drill.SAVE_ID),migrated)

    def test_invalid_packages_fail_before_application_or_save_creation(self):
        mutations = ('missing_manifest','missing_reference','unlock_cycle','unknown_effect_resource','unknown_field')
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                root = self.root/mutation;root.mkdir();drill.prepare_package(root)
                if mutation=='missing_manifest':
                    value=drill.read(root,'content_manifest.json')
                    next(row for row in value['packages'] if row['id']=='expeditions')['sources'].remove('src/data/dungeons/'+drill.ENTRY.source)
                    drill.write(root,'content_manifest.json',value)
                elif mutation in ('missing_reference','unlock_cycle','unknown_field'):
                    value=drill.read(root,'dungeons/'+drill.ENTRY.source)
                    if mutation=='missing_reference':value['loot']['normal_materials'][0]='missing_drill_material'
                    elif mutation=='unlock_cycle':value['unlock']['dungeon_id']=drill.DUNGEON
                    else:value['effect_type']='execute_arbitrary_python'
                    drill.write(root,'dungeons/'+drill.ENTRY.source,value)
                else:
                    value=drill.read(root,'cultivation/leveling.json')
                    value['pills']['missing_drill_tonic']=value['pills'].pop(drill.TONIC)
                    drill.write(root,'cultivation/leveling.json',value)
                with drill.package(root) as loader:
                    with self.assertRaises((ValidationError,content_loader.ContentInputError)):loader.load()
                    self.assertIsNone(loader._registry)
                self.assertFalse((root/'drill.sqlite3').exists())
        target = self.target()
        with self.assertRaisesRegex(ValidationError,'unsupported item effect type'):
            validate_bindings(target,[{'command':'cultivation_use_pill','item_id':drill.TONIC,
                                      'effect_type':'arbitrary_effect','parameters':{}}])

    def test_semantic_edits_and_deletions_refuse_migration_without_database_change(self):
        target = self.target()
        with SQLiteSave.initialize(self.path,allowed_root=self.root) as store:
            app, _, _, _ = self.create(store)
            before = app.query(drill.SAVE_ID)
            request = drill.command(app,'drill_upgrade')
            for mutation in ('rename','delete','old_cost'):
                with self.subTest(mutation=mutation):
                    changed = DefinitionRegistry(schema_version=target.schema_version,content_version=target.content_version)
                    for row in target._definitions.values():
                        if row.key==DefinitionKey('resources','wood'):
                            if mutation=='delete':continue
                            if mutation=='rename':row=replace(row,display_name='changed old wood')
                        if mutation=='old_cost' and row.key==DefinitionKey('sect_rules','shipping'):
                            values=thaw_json(row.values);values['craft']['common']['coins']+=1
                            from src.core.state.envelope import freeze_json
                            row=replace(row,values=freeze_json(values))
                        changed.register(row)
                    # A missing referenced resource is rejected even before policy.
                    if mutation=='delete':
                        with self.assertRaises(ValidationError):changed.seal()
                        continue
                    changed.seal()
                    with self.assertRaises(ValidationError):drill.migrate(store,self.clock,request,self.source,changed)
                    self.assertEqual(app.query(drill.SAVE_ID),before)
                    self.assertIsNone(store.receipt(drill.SAVE_ID,before.generation,request.request_id))

    def test_formal_runtime_and_preflight_reject_test_version_and_reverse_edge_is_readonly(self):
        target = self.target()
        with SQLiteSave.initialize(self.path,allowed_root=self.root) as store:
            old, _, _, _ = self.create(store)
            before = old.query(drill.SAVE_ID)
            report = preflight.inspect_compatibility(before,drill.VERSION,source_registry=self.source,target_registry=target)
            self.assertEqual(report['transition'],'BLOCKED')
            self.assertEqual(old.query(drill.SAVE_ID),before)
            drill.migrate(store,self.clock,drill.command(old,'drill_upgrade'),self.source,target)
            app = EcologyApplication(store,target,self.clock)
            upgraded = app.query(drill.SAVE_ID)
            reverse = drill.command(app,'drill_upgrade')
            with self.assertRaises(ValidationError):drill.migrate(store,self.clock,reverse,target,self.source)
            self.assertEqual(app.query(drill.SAVE_ID),upgraded)
            self.assertIsNone(store.receipt(drill.SAVE_ID,upgraded.generation,reverse.request_id))
        # configured_game is pointed only at this synthetic project's .game.
        private = self.root/'.game';private.mkdir()
        path = private/'danding.sqlite3'
        with SQLiteSave.initialize(path,allowed_root=private) as store:
            with store.transaction():store.create(upgraded)
        (private/'save-id').write_text(drill.SAVE_ID)
        raw = path.read_bytes()
        with patch.object(game,'PROJECT',self.root),patch.object(content_loader,'load_current',side_effect=AssertionError('unknown package assembled')):
            with self.assertRaisesRegex(ValidationError,'unsupported'):
                game.configured_game()
        self.assertEqual(path.read_bytes(),raw)


if __name__ == '__main__':
    unittest.main()

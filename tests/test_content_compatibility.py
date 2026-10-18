"""Offline reports and real dedicated migrations, only disposable V2 snapshots."""
from contextlib import contextmanager
from dataclasses import replace
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from src.application import content_compatibility as analysis
from src.application import equipment as equip
from src.application.cold_jade_upgrade import upgrade as cold_upgrade
from src.application.danding import initial_slice
from src.application.dungeons import DungeonApplication
from src.application.ecology import EcologyApplication
from src.application.ecology_upgrade import upgrade
from src.application.memory import Command
from src.application.sect_management import ManagementApplication
from src.application.settlement import SettlementRequest
from src.core.save.backup import MAX_SAVE_BYTES
from src.core.save.codec import StoredReceipt
from src.core.save.sqlite import SQLiteSave, V2_ROOT
from src.core.state.envelope import StateEnvelope, freeze_json, thaw_json
from src.core.time.model import Continuation
from src.core.validation import ConflictError, ValidationError
from src.data import content_compatibility as content
from src.data.dungeons.definitions import load_dungeons
from src.data.economy.sect_rules import settings
from src.data.items.resources import ResourceDefinition
from src.data.registry import DefinitionKey, DefinitionRegistry
from tests.fixtures.time import ManualClock
from tools.economy import check_save_compatibility as cli


OLD, CURRENT = content.COLD_JADE_MANAGEMENT_VERSION, content.ECOLOGY_VERSION


def clone(registry, replacements=None, additions=(), reverse=False):
    replacements = replacements or {}
    result = DefinitionRegistry(schema_version=registry.schema_version, content_version=registry.content_version)
    rows = list(registry._definitions.values())
    for row in reversed(rows) if reverse else rows:
        result.register(replacements.get(row.key, row))
    for row in additions:result.register(row)
    result.seal()
    return result


class Fixtures:
    @classmethod
    def setUpClass(cls):
        cls.old = load_dungeons(management=True,cold_jade=True)
        cls.current = load_dungeons(management=True,cold_jade=True,ecology=True)

    def fixture(self, registry=None, application=None):
        registry = self.old if registry is None else registry
        application = ManagementApplication if application is None else application
        tmp = tempfile.TemporaryDirectory(prefix='compatibility-',dir=V2_ROOT/'tests')
        self.addCleanup(tmp.cleanup)
        root, clock = Path(tmp.name), ManualClock()
        path = root/'isolated.sqlite3'
        state = initial_slice(registry,last_settled_at_ms=clock.now_ms())
        domains = thaw_json(state.domains)
        domains['inventory']['holdings'].update(food=40,grain=100,spring_water=100,coins=1000,herb=100)
        domains['disciples']['assignments'] = {}
        state = replace(state,domains=domains)
        for definition, version in (('thorn_fang_blade','thorn-forge-v1'),('mist_marsh_equipment_01','mist_marsh-roll-v1')):
            state, identity = equip.acquire(state,registry,definition,'saved:'+version,roll_version=version)
        domains = thaw_json(state.domains)
        row = domains['equipment']['instances'][identity]
        row.update(locked=True,favorite=True,enhancement={'level':1,'bonus_bps':500,'version':'sect-enhance-v1'})
        state = replace(state,domains=domains)
        with SQLiteSave.initialize(path,allowed_root=root) as store:
            app = application(store,registry,clock)
            app.create(state)
            state = app.query(state.save_id)
        return root,path,clock,state

    def request(self, app, sid, name, payload=None):
        state = app.query(sid)
        return Command(sid,state.generation,state.revision,str(uuid4()),name,payload or {})

    def execute(self, app, sid, name, payload=None):
        q = self.request(app,sid,name,payload)
        return q,app.execute(q)


class ContentPolicyTests(Fixtures,unittest.TestCase):
    def test_three_explicit_profiles_and_directional_policies(self):
        table = content.validate_profiles()
        from src.data.combat.mechanics import CONTENT_VERSION as EFFECTS
        self.assertEqual(set(table),{OLD,CURRENT,EFFECTS})
        self.assertEqual(content.transition(CURRENT,EFFECTS),'REQUIRES_EXPLICIT_MIGRATION')
        self.assertEqual(content.transition(EFFECTS,CURRENT),'BLOCKED')
        self.assertEqual(content.transition(OLD,CURRENT),'REQUIRES_EXPLICIT_MIGRATION')
        self.assertEqual(content.transition(CURRENT,OLD),'BLOCKED')
        self.assertEqual(content.transition(OLD,OLD),'NOT_NEEDED')
        with self.assertRaises(TypeError):table['new'] = table[OLD]
        for version in ('future',load_dungeons().content_version,None,[]):
            with self.subTest(version=version),self.assertRaises(ValidationError):content.profile(version)

    def test_duplicate_missing_and_unsafe_profile_declarations_rejected(self):
        row = content.PROFILES[0]
        variants = [(),(*content.PROFILES,row),
                    (replace(row,application='os.system'),content.PROFILES[1]),
                    (replace(row,loader='plugin'),content.PROFILES[1]),
                    (replace(row,flags=(('management',1),('cold_jade',True))),content.PROFILES[1]),
                    (replace(row,domains=set(row.domains)),content.PROFILES[1])]
        for entries in variants:
            with self.subTest(entries=entries),self.assertRaises(ValidationError):content.validate_profiles(entries)

    def test_fingerprint_ignores_insertion_order_and_observes_all_definition_fields(self):
        evidence = content.package_evidence(self.old)
        self.assertEqual(evidence,content.package_evidence(clone(self.old,reverse=True)))
        row = self.old.lookup(DefinitionKey('resources','wood'))
        changed = clone(self.old,{row.key:replace(row,display_name=row.display_name+'测试')})
        other = content.package_evidence(changed)
        self.assertNotEqual(evidence['fingerprint'],other['fingerprint'])
        self.assertEqual(content.differences(evidence,other)['definitions']['modified'],['resources:wood'])

    def test_effect_binding_changes_and_added_ids_are_reported(self):
        rules = self.current.lookup(DefinitionKey('sect_rules','shipping'))
        values = thaw_json(rules.values)
        values['leveling']['pills'].pop('ju_qi_pill')
        changed = clone(self.current,{rules.key:replace(rules,values=freeze_json(values))},
                        [ResourceDefinition('resources','trial_material','临时材料')])
        delta = content.differences(content.package_evidence(self.current),content.package_evidence(changed))
        self.assertEqual(delta['effects']['removed'],['cultivation_use_pill:ju_qi_pill'])
        self.assertIn('resources:trial_material',delta['definitions']['added'])
        self.assertFalse(self.current.contains(DefinitionKey('resources','trial_material')))


class CompatibilityReportTests(Fixtures,unittest.TestCase):
    def report(self,state,target,**kwargs):
        return analysis.inspect_compatibility(state,target,
            source_registry=kwargs.pop('source_registry', self.old if state.content_version==OLD else self.current),
            target_registry=kwargs.pop('target_registry',self.old if target==OLD else self.current),**kwargs)

    def test_same_package_valid_without_side_effect_or_reading_clock_database(self):
        root,path,clock,state = self.fixture()
        before = state.to_dict()
        raw = path.read_bytes()
        with patch('sqlite3.connect',side_effect=AssertionError('report opened DB')):
            report = self.report(state,OLD)
        self.assertEqual(report['transition'],'NOT_NEEDED')
        self.assertEqual(report['source']['validation'],'VALID')
        self.assertEqual(report['target']['validation'],'VALID')
        self.assertEqual(state.to_dict(),before)
        self.assertEqual(path.read_bytes(),raw)
        self.assertEqual(report['provenance'],'CURRENT_TREE_ONLY')
        for key in ('SQLITE_RECEIPTS','WALL_CLAIM','PREVIOUS','HISTORICAL_RELEASE_CODE_AND_PACKAGE'):
            self.assertIn(key,report['not_checked'])
        self.assertNotIn('save_id',json.dumps(report))
        self.assertEqual(report,self.report(state,OLD))

    def test_forward_requires_dedicated_transform_and_reverse_is_never_authorized(self):
        root,path,clock,old = self.fixture()
        report = self.report(old,CURRENT)
        self.assertEqual(report['transition'],'REQUIRES_EXPLICIT_MIGRATION')
        self.assertEqual(report['target']['validation'],'INVALID')
        self.assertIn('DEDICATED_MIGRATION_REQUIRED',{issue['code'] for issue in report['issues']})
        root,path,clock,current = self.fixture(self.current,EcologyApplication)
        with patch.object(analysis,'validate_snapshot',return_value=current):
            report = self.report(current,OLD)
        self.assertEqual(report['target']['validation'],'VALID')
        self.assertEqual(report['transition'],'BLOCKED')
        self.assertIn('DOWNGRADE_NOT_SUPPORTED',{issue['code'] for issue in report['issues']})

    def test_unknown_versions_and_partitions_fail_closed(self):
        root,path,clock,state = self.fixture()
        for source,target in ((replace(state,content_version='future'),OLD),(state,'future')):
            report = self.report(source,target)
            self.assertEqual(report['transition'],'BLOCKED')
            self.assertIn('UNSUPPORTED',[report[side]['validation'] for side in ('source','target')])
        bad = replace(state,domains={**state.domains,'unknown_domain':{}})
        report = self.report(bad,OLD)
        self.assertEqual(report['source']['validation'],'INVALID')
        self.assertEqual(report['target']['validation'],'NOT_CHECKED')

    def test_unsupported_roll_battle_snapshot_and_job_definition_are_rejected(self):
        root,path,clock,state = self.fixture()
        with SQLiteSave(path,allowed_root=root) as store:
            app = ManagementApplication(store,self.old,clock)
            bid = next(key for key,row in state.domains['sect']['buildings'].items() if row['definition_id']=='canteen')
            self.execute(app,state.save_id,'work_assign',{'building_id':bid,'count':1})
            self.execute(app,state.save_id,'production_start',{'building_id':bid,'recipe_id':'sect_food'})
            self.execute(app,state.save_id,'combat_start',{'encounter_id':'thorn_path_v2_001'})
            state = app.query(state.save_id)
        for part in ('equipment','production','combat','loot'):
            domains = thaw_json(state.domains)
            if part == 'equipment':next(iter(domains[part]['instances'].values()))['roll_version'] = 'future-roll'
            elif part == 'production':next(iter(domains[part]['jobs'].values()))['recipe_id'] = 'future_recipe'
            elif part == 'combat':domains[part]['battle']['player_snapshot']['attack_milli'] = 10**15
            else:domains['combat']['battle']['loot_version'] = 'future-loot'
            report = self.report(replace(state,domains=domains),OLD)
            with self.subTest(part=part):
                self.assertEqual(report['source']['validation'],'INVALID')
                self.assertEqual(report['transition'],'BLOCKED')

    def test_source_invalid_stops_before_loading_target(self):
        root,path,clock,state = self.fixture()
        inv = thaw_json(state.domains['inventory']);inv['holdings']['missing_resource'] = 1
        bad = replace(state,domains={**state.domains,'inventory':inv})
        with patch.object(analysis,'load_registry',side_effect=AssertionError('loaded target after bad source')):
            report = analysis.inspect_compatibility(bad,CURRENT,source_registry=self.old)
        self.assertEqual(report['source']['validation'],'INVALID')

    def test_same_version_semantic_changes_do_not_pass_even_with_valid_target(self):
        root,path,clock,state = self.fixture()
        row = self.old.lookup(DefinitionKey('resources','wood'))
        target = clone(self.old,{row.key:replace(row,display_name='测试更名')})
        report = self.report(state,OLD,target_registry=target)
        self.assertEqual(report['target']['validation'],'VALID')
        self.assertEqual(report['transition'],'BLOCKED')
        self.assertIn('SAME_VERSION_DIFFERENT_PACKAGE',{issue['code'] for issue in report['issues']})

    def test_used_removed_item_blocks_target_and_keeps_input_unchanged(self):
        added = ResourceDefinition('resources','saved_trial_material','仅旧档材料')
        source = clone(self.old,additions=[added])
        root,path,clock,state = self.fixture(source)
        inventory = thaw_json(state.domains['inventory'])
        inventory['holdings']['saved_trial_material'] = 3
        state = replace(state,domains={**state.domains,'inventory':inventory})
        before = state.to_dict()
        report = self.report(state,OLD,source_registry=source)
        self.assertEqual(report['source']['validation'],'VALID')
        self.assertEqual(report['target']['validation'],'INVALID')
        self.assertEqual(report['transition'],'BLOCKED')
        self.assertIn('resources:saved_trial_material',report['differences']['definitions']['removed'])
        self.assertEqual(before,state.to_dict())


class OfflineCompatibilityCLITests(Fixtures,unittest.TestCase):
    def setUp(self):
        self.root,self.path,self.clock,self.state = self.fixture()
        self.snapshot = self.root/'snapshot.json'
        self.snapshot.write_text(json.dumps(self.state.to_dict(),ensure_ascii=False))

    def test_read_snapshot_and_command_are_readonly_and_do_not_connect_sqlite(self):
        raw = self.snapshot.read_bytes();mtime = self.snapshot.stat().st_mtime_ns
        with patch('sqlite3.connect',side_effect=AssertionError('CLI connected DB')):
            report = cli.run(self.snapshot,OLD)
        self.assertEqual(report['transition'],'NOT_NEEDED')
        self.assertEqual(report['snapshot_file_sha256'],hashlib.sha256(raw).hexdigest())
        self.assertEqual(self.snapshot.read_bytes(),raw)
        self.assertEqual(self.snapshot.stat().st_mtime_ns,mtime)
        self.assertEqual(sorted(row.name for row in self.root.iterdir()),['isolated.sqlite3','snapshot.json'])

    def test_bad_json_duplicate_keys_nonfinite_and_future_schema_rejected(self):
        for raw in ('{','{"x":1,"x":2}','{"x":NaN}',json.dumps({**self.state.to_dict(),'save_schema_version':2})):
            with self.subTest(raw=raw[:30]):
                self.snapshot.write_text(raw)
                with self.assertRaises((ValidationError,ValueError)):cli.read_snapshot(self.snapshot)
        self.snapshot.write_text(json.dumps({**self.state.to_dict(),'extra':{}}))
        with self.assertRaises(ValidationError):cli.read_snapshot(self.snapshot)

    def test_production_v1_outside_traversal_and_symlinks_rejected_before_read(self):
        for path in (V2_ROOT/'.game/snapshot.json',V2_ROOT.parent/'legacy-reference/test.json',
                     Path('/tmp/external.json'),self.root/'../escape.json'):
            with self.subTest(path=path),self.assertRaises(ValidationError):cli.checked_input(path)
        link = self.root/'link.json';link.symlink_to(self.snapshot)
        with self.assertRaises(ValidationError):cli.read_snapshot(link)
        directory = self.root/'linked';directory.symlink_to(self.root,target_is_directory=True)
        with self.assertRaises(ValidationError):cli.read_snapshot(directory/'snapshot.json')

    def test_input_mutation_during_read_is_rejected(self):
        original = cli.os.fstat
        calls = []
        def mutate(descriptor):
            result = original(descriptor)
            calls.append(True)
            if len(calls)==1:
                self.snapshot.write_text(self.snapshot.read_text()+' ')
            return result
        with patch.object(cli.os,'fstat',side_effect=mutate):
            with self.assertRaisesRegex(ValidationError,'changed during read'):
                cli.read_snapshot(self.snapshot)

    def test_size_limit_and_nonregular_input_rejected(self):
        self.snapshot.write_bytes(b' '*(MAX_SAVE_BYTES+1))
        with self.assertRaises(ValidationError):cli.read_snapshot(self.snapshot)
        directory = self.root/'directory.json';directory.mkdir()
        with self.assertRaises((ValidationError,OSError)):cli.read_snapshot(directory)

    def test_cli_exit_codes_and_no_apply_option(self):
        script = V2_ROOT/'tools/economy/check_save_compatibility.py'
        base = [sys.executable,'-B',str(script),'--snapshot',str(self.snapshot)]
        for target,expected in ((OLD,0),(CURRENT,1),('future',1)):
            child = subprocess.run([*base,'--target',target,'--json'],cwd='/tmp',capture_output=True,text=True,timeout=30)
            self.assertEqual(child.returncode,expected,child.stderr)
            report = json.loads(child.stdout)
            self.assertNotIn('SAFE_TO_APPLY',child.stdout)
            self.assertIn('transition',report)
        child = subprocess.run([*base,'--target',OLD,'--apply'],capture_output=True,text=True,timeout=30)
        self.assertEqual(child.returncode,2)
        self.snapshot.write_text('{')
        with patch('sys.stdout',new_callable=io.StringIO) as output:
            self.assertEqual(cli.main(['--snapshot',str(self.snapshot),'--target',OLD,'--json']),1)
        self.assertEqual(json.loads(output.getvalue())['issues'][0]['code'],'INVALID_INPUT')


class DedicatedMigrationTests(Fixtures,unittest.TestCase):
    def test_ecology_upgrade_preserves_gear_paid_job_battle_cursor_clock_and_receipts_after_restart(self):
        root,path,clock,state = self.fixture()
        sid = state.save_id
        with SQLiteSave(path,allowed_root=root) as store:
            old = ManagementApplication(store,self.old,clock)
            supply,rs = self.execute(old,sid,'sect_supply',{'enabled':True,'reserve':0})
            building = next(key for key,row in state.domains['sect']['buildings'].items() if row['definition_id']=='canteen')
            self.execute(old,sid,'work_assign',{'building_id':building,'count':1})
            job,rj = self.execute(old,sid,'production_start',{'building_id':building,'recipe_id':'sect_food'})
            self.execute(old,sid,'dungeon_auto',{'enabled':True,'mode':'farm','floor':1})
            self.execute(old,sid,'dungeon_auto',{'enabled':False,'mode':'farm','floor':1})
            self.execute(old,sid,'combat_start',{'encounter_id':'thorn_path_v2_001'})
            before = old.query(sid)
            self.assertEqual(before.domains['combat']['battle']['status'],'ACTIVE')
            self.assertTrue(before.domains['production']['jobs'])
            q = self.request(old,sid,'ecology_content_upgrade')
            result = upgrade(store,clock,q)
            app = EcologyApplication(store,self.current,clock)
            after = app.query(sid)
            for domain in before.domains:
                if domain not in ('inventory','sect_management','automation'):
                    self.assertEqual(after.domains[domain],before.domains[domain],domain)
            self.assertEqual(after.time,before.time)
            expected_identity = {**before.identity,'event_counter':before.identity['event_counter']+2}
            self.assertEqual(dict(after.identity),expected_identity)
            wake = after.domains['ecology']['wake']
            self.assertEqual(wake['event_id'],f"{sid}:{before.generation}:e:{before.identity['event_counter']+1}")
            self.assertEqual(wake['next_event_id'],f"{sid}:{before.generation}:e:{before.identity['event_counter']+2}")
            self.assertEqual(wake['due_ms'],after.domains['ecology']['supply']['next_day_ms'])
            self.assertEqual((after.save_id,after.generation),(before.save_id,before.generation))
            inventory = thaw_json(before.domains['inventory'])
            quantity = inventory['holdings'].pop('food')
            inventory['holdings']['meal_qingling_rice'] = inventory['holdings'].get('meal_qingling_rice',0)+quantity
            self.assertEqual(thaw_json(after.domains['inventory']),inventory)
            self.assertNotIn('food',after.domains['inventory']['holdings'])
            self.assertEqual(after.domains['production'],before.domains['production'])
            self.assertEqual(after.domains['combat'],before.domains['combat'])
            self.assertEqual(after.domains['dungeon'],before.domains['dungeon'])
            for request,receipt in ((supply,rs),(job,rj)):
                self.assertEqual(app.execute(request),receipt)
            self.assertEqual(upgrade(store,clock,q),result)
            with self.assertRaises(ConflictError):
                app.execute(replace(supply,payload={'enabled':False,'reserve':0}))
            with self.assertRaises((ValidationError,ConflictError)):upgrade(store,clock,replace(q,payload={'changed':True}))
            self.assertEqual(app.query(sid),after)
        with SQLiteSave(path,allowed_root=root) as store:
            app = EcologyApplication(store,self.current,clock)
            self.assertEqual(app.query(sid),after)
            self.assertEqual(app.execute(job),rj)
            self.assertEqual(upgrade(store,clock,q),result)
            self.assertEqual(app.query(sid),after)

    def test_enabled_auto_cursor_and_wake_survive_ecology_migration(self):
        root,path,clock,state = self.fixture()
        with SQLiteSave(path,allowed_root=root) as store:
            app = ManagementApplication(store,self.old,clock)
            self.execute(app,state.save_id,'dungeon_auto',{'enabled':True,'mode':'farm','floor':1})
            before = app.query(state.save_id)
            self.assertTrue(before.domains['dungeon']['auto']['enabled'])
            self.assertIsNotNone(before.domains['dungeon']['auto']['wake'])
            upgrade(store,clock,self.request(app,state.save_id,'ecology_content_upgrade'))
            after = EcologyApplication(store,self.current,clock).query(state.save_id)
            self.assertEqual(after.domains['dungeon'],before.domains['dungeon'])
            self.assertEqual(after.time,before.time)

    def test_real_commit_and_checkpoint_failures_leave_no_partial_migration(self):
        for stage in ('commit_after_sql','checkpoint_after_sql','target_validation'):
            with self.subTest(stage=stage):
                root,path,clock,state = self.fixture()
                with SQLiteSave(path,allowed_root=root) as store:
                    old = ManagementApplication(store,self.old,clock)
                    before = old.query(state.save_id)
                    with store.transaction():store.checkpoint(state.save_id)
                    previous = store.inspect(state.save_id).recovery
                    raw_rows = store.recovery_rows(state.save_id)
                    q = self.request(old,state.save_id,'ecology_content_upgrade')
                    if stage == 'target_validation':
                        # Upgrade uses the pure target validator, not create.
                        from src.application import ecology_upgrade
                        actual_class = ecology_upgrade.EcologyApplication
                        def fail_app(*args,**kwargs):
                            app = actual_class(*args,**kwargs)
                            app.foundation.validate_state = lambda _: (_ for _ in ()).throw(ValidationError('injected'))
                            return app
                        context = patch.object(ecology_upgrade,'EcologyApplication',side_effect=fail_app)
                    else:
                        target,attr = store, 'commit' if stage=='commit_after_sql' else 'checkpoint'
                        actual = getattr(target,attr)
                        calls = []
                        def fail(*args,**kwargs):
                            result = actual(*args,**kwargs)
                            calls.append(True)
                            if stage == 'commit_after_sql' or len(calls) == 2:
                                raise ValidationError('injected')
                            return result
                        context = patch.object(target,attr,side_effect=fail)
                    with context:
                        with self.assertRaisesRegex(ValidationError,'injected'):upgrade(store,clock,q)
                    self.assertEqual(old.query(state.save_id),before)
                    self.assertEqual(store.inspect(state.save_id).recovery,previous)
                    self.assertEqual(store.recovery_rows(state.save_id),raw_rows)
                    self.assertIsNone(store.receipt(state.save_id,state.generation,q.request_id))
                    upgrade(store,clock,q)
                    self.assertEqual(EcologyApplication(store,self.current,clock).query(state.save_id).content_version,CURRENT)

    def test_pending_ecology_migration_and_readonly_report_both_preserve_window(self):
        root,path,clock,state = self.fixture()
        with SQLiteSave(path,allowed_root=root) as store:
            app = ManagementApplication(store,self.old,clock)
            self.execute(app,state.save_id,'sect_supply',{'enabled':True,'reserve':0})
            building = next(key for key,row in state.domains['sect']['buildings'].items() if row['definition_id']=='canteen')
            self.execute(app,state.save_id,'work_assign',{'building_id':building,'count':1})
            self.execute(app,state.save_id,'production_start',{'building_id':building,'recipe_id':'sect_food'})
            clock.advance(600000)
            current = app.query(state.save_id)
            app.settle(SettlementRequest(current.save_id,current.generation,current.revision,str(uuid4()),1,None))
            pending = app.query(state.save_id)
            self.assertIsNotNone(pending.time['pending'])
            report = analysis.inspect_compatibility(pending,CURRENT,source_registry=self.old,target_registry=self.current)
            self.assertEqual(report['transition'],'BLOCKED')
            self.assertIn('PENDING_WINDOW',{issue['code'] for issue in report['issues']})
            q = self.request(app,state.save_id,'ecology_content_upgrade')
            with self.assertRaises(ConflictError):upgrade(store,clock,q)
            self.assertEqual(app.query(state.save_id),pending)
            self.assertIsNone(store.receipt(state.save_id,state.generation,q.request_id))
        with SQLiteSave(path,allowed_root=root) as store:
            self.assertEqual(ManagementApplication(store,self.old,clock).query(state.save_id),pending)

    def test_additive_cold_upgrade_rebinds_pending_and_continues_without_losing_paid_jobs(self):
        registry = load_dungeons(management=True)
        root,path,clock,state = self.fixture(registry)
        with SQLiteSave(path,allowed_root=root) as store:
            app = ManagementApplication(store,registry,clock)
            self.execute(app,state.save_id,'sect_supply',{'enabled':True,'reserve':0})
            building = next(key for key,row in state.domains['sect']['buildings'].items() if row['definition_id']=='canteen')
            self.execute(app,state.save_id,'work_assign',{'building_id':building,'count':1})
            job,receipt = self.execute(app,state.save_id,'production_start',{'building_id':building,'recipe_id':'sect_food'})
            clock.advance(600000)
            current = app.query(state.save_id)
            app.settle(SettlementRequest(current.save_id,current.generation,current.revision,str(uuid4()),1,None))
            before = app.query(state.save_id)
            self.assertIsNotNone(before.time['pending'])
            q = self.request(app,state.save_id,'cold_jade_content_upgrade')
            result = cold_upgrade(store,clock,q)
            after = ManagementApplication(store,self.old,clock).query(state.save_id)
            self.assertEqual(after.domains,before.domains)
            self.assertEqual(after.identity,before.identity)
            expected = thaw_json(before.time);expected['pending']['revision'] = after.revision
            self.assertEqual(thaw_json(after.time),expected)
            self.assertEqual(cold_upgrade(store,clock,q),result)
        with SQLiteSave(path,allowed_root=root) as store:
            app = ManagementApplication(store,self.old,clock)
            self.assertEqual(app.query(state.save_id),after)
            for _ in range(50):
                current = app.query(state.save_id)
                if current.time['pending'] is None:break
                app.settle(SettlementRequest(current.save_id,current.generation,current.revision,str(uuid4()),128,Continuation.for_state(current)))
            resumed = app.query(state.save_id)
            self.assertIsNone(resumed.time['pending'])
            self.assertEqual(resumed.domains['equipment'],before.domains['equipment'])
            self.assertEqual(app.execute(job),receipt)


if __name__=='__main__':unittest.main()

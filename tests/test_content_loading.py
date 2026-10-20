"""Startup snapshots, factory equivalence and disposable save restart compatibility."""
import json
from dataclasses import replace
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from src.data import content_loader as content
from src.data.dungeons.definitions import load_dungeons
from src.data.economy.sect_rules import settings


class ContentLoadingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='content-loading-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root/'src/data/sample.json'
        self.source.parent.mkdir(parents=True)
        self.source.write_text('{"schema_version":1}')
        self.manifest = self.root/'src/data/content_manifest.json'
        self.data = {'schema_version':1, 'profile':'ecology_current', 'content_version':'fixture-v1',
                     'packages':[{'id':'sample','sources':['src/data/sample.json']}]}
        self.write_manifest()
        self.calls = []
        self.registry = SimpleNamespace(is_sealed=True, content_version='fixture-v1')
        self.loader = content.ContentLoader(root=self.root, assembler=self.assemble)

    def write_manifest(self):
        self.manifest.write_text(json.dumps(self.data))

    def assemble(self, profile):
        self.calls.append(profile)
        return self.registry

    def test_assembly_is_pinned_and_manifest_is_not_a_content_source(self):
        self.assertIs(self.loader.load(), self.registry)
        self.assertIs(self.loader.load(), self.registry)
        self.assertEqual(self.calls, ['ecology_current'])
        self.assertEqual(content.discover_sources(self.root, self.manifest), {'src/data/sample.json'})

    def test_changed_inputs_require_restart_without_reassembly(self):
        for target in (self.source, self.manifest):
            with self.subTest(target=target):
                self.source.write_text('{"schema_version":1}');self.write_manifest()
                loader = content.ContentLoader(root=self.root, assembler=self.assemble)
                loader.load();count = len(self.calls)
                target.write_text(target.read_text()+' ')
                with self.assertRaisesRegex(content.ContentInputError, 'restart required'):
                    loader.load()
                self.assertEqual(count, len(self.calls))

    def test_invalid_manifest_rejected_before_assembly(self):
        original = json.dumps(self.data)
        mutations = [lambda d:d.update(schema_version=True), lambda d:d.update(schema_version=2),
                     lambda d:d.update(profile='os.system'),lambda d:d.update(extra='import'),
                     lambda d:d['packages'].append(d['packages'][0]),
                     lambda d:d['packages'].append({'id':'other','sources':['src/data/sample.json']})]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                self.data = json.loads(original);mutate(self.data);self.write_manifest()
                with self.assertRaises(content.ContentInputError):self.loader.load()
        for raw in ('{"schema_version":1,"schema_version":1}', '{"schema_version":NaN}'):
            self.manifest.write_text(raw)
            with self.assertRaises(content.ContentInputError):self.loader.load()
        self.assertEqual(self.calls, [])

    def test_invalid_sources_rejected_before_assembly(self):
        for raw in ('{"x":1,"x":2}', '{"x":Infinity}', '[]', '{"schema_version":true}', '{"schema_version":2}'):
            with self.subTest(raw=raw):
                self.source.write_text(raw)
                with self.assertRaises(content.ContentInputError):self.loader.load()
        self.assertEqual(self.calls, [])

    def test_undeclared_and_missing_sources_block_current_loading(self):
        extra = self.source.parent/'unlisted.json';extra.write_text('{}')
        with self.assertRaisesRegex(content.ContentInputError, 'coverage mismatch'):self.loader.load()
        extra.unlink();self.source.unlink()
        with self.assertRaises(content.ContentInputError):self.loader.load()
        self.assertEqual(self.calls, [])

    def test_traversal_symlinks_and_duplicate_resolved_sources_rejected(self):
        for name in ('../outside.json', '/etc/passwd', 'src/ui/data.json'):
            self.data['packages'][0]['sources']=[name];self.write_manifest()
            with self.assertRaises(content.ContentInputError):self.loader.load()
        self.data['packages'][0]['sources']=['src/data/sample.json','src/data/alias.json']
        alias = self.source.parent/'alias.json';alias.symlink_to(self.source);self.write_manifest()
        with self.assertRaisesRegex(content.ContentInputError, 'duplicate resolved'):self.loader.load()
        alias.unlink();outside=self.root/'outside.json';outside.write_text('{}')
        self.source.unlink();self.source.symlink_to(outside)
        self.data['packages'][0]['sources']=['src/data/sample.json'];self.write_manifest()
        with self.assertRaises(content.ContentInputError):self.loader.load()
        self.assertEqual(self.calls, [])

    def test_unsealed_wrong_version_and_factory_failures_never_pin(self):
        for registry in (SimpleNamespace(is_sealed=False,content_version='fixture-v1'),
                         SimpleNamespace(is_sealed=True,content_version='wrong')):
            self.registry=registry
            with self.assertRaises(content.ContentInputError):self.loader.load()
            self.assertIsNone(self.loader._registry)
        def fail(_):raise RuntimeError('factory failure')
        with self.assertRaisesRegex(RuntimeError,'factory failure'):
            content.ContentLoader(root=self.root,assembler=fail).load()

    def test_source_changes_and_new_files_during_assembly_fail_closed(self):
        def change(_):
            self.source.write_text('{"schema_version":1,"changed":true}')
            return self.registry
        with self.assertRaisesRegex(content.ContentInputError,'changed during assembly'):
            content.ContentLoader(root=self.root,assembler=change).load()
        def add(_):
            (self.source.parent/'added.json').write_text('{}')
            return self.registry
        with self.assertRaisesRegex(content.ContentInputError,'coverage mismatch'):
            content.ContentLoader(root=self.root,assembler=add).load()

    def test_builtin_factory_cannot_read_an_unrelated_root(self):
        with self.assertRaises(content.ContentInputError):content.ContentLoader(root=self.root)

    def test_current_registry_retains_historical_definitions_and_whitelist(self):
        original = load_dungeons(management=True,cold_jade=True,ecology=True)
        loaded = content.load_current()
        self.assertEqual(original.schema_version,loaded.schema_version)
        self.assertNotEqual(original.content_version,loaded.content_version)
        self.assertEqual(1772,len(loaded._definitions))
        self.assertLess(set(original._definitions),set(loaded._definitions))
        for key, definition in original._definitions.items():
            with self.subTest(key=key):
                self.assertIs(type(definition),type(loaded.lookup(key)))
                self.assertEqual(definition,loaded.lookup(key))
        self.assertEqual(settings(original),settings(loaded))

    def test_first_current_assembly_refreshes_known_source_caches(self):
        from src.data.dungeons import loot,expeditions,durability
        from src.data.economy import activities
        from contextlib import ExitStack
        with ExitStack() as stack:
            checks=[stack.enter_context(patch.object(reader,'cache_clear',wraps=reader.cache_clear))
                    for reader in (loot.content,expeditions.content,durability.settings,activities.content)]
            loader=content.ContentLoader();loader.load();loader.load()
            for check in checks:check.assert_called_once_with()

    def test_historical_factories_do_not_require_current_manifest(self):
        profiles=({}, {'legacy':True}, {'balance_legacy':True}, {'expansion_legacy':True},
                  {'management':True}, {'cold_jade':True}, {'management':True,'cold_jade':True})
        expected=[load_dungeons(**flags) for flags in profiles]
        with patch.object(content,'content_snapshot',side_effect=content.ContentInputError('bad current manifest')):
            for flags, before in zip(profiles,expected):
                after=load_dungeons(**flags)
                self.assertEqual(before.content_version,after.content_version)
                self.assertEqual(before._definitions,after._definitions)

    def test_default_game_factory_loads_once_and_explicit_old_registry_bypasses_manifest(self):
        from tools.playable.game import game_factory
        with patch.object(content,'load_current',return_value=content.load_current()) as load:
            factory=game_factory(self.root/'unused.sqlite3',self.root)
            self.assertTrue(callable(factory));load.assert_called_once_with()
        with patch.object(content,'load_current',side_effect=AssertionError('old version consulted current manifest')):
            self.assertTrue(callable(game_factory(self.root/'unused.sqlite3',self.root,
                                     registry=load_dungeons(management=True,cold_jade=True))))
        self.assertFalse((self.root/'unused.sqlite3').exists())

    def test_builtin_current_loading_checks_catalog_sources_before_assembly(self):
        from src.data.dungeons import catalog
        from src.core.validation import ValidationError
        with patch.object(catalog,'validate_sources',side_effect=ValidationError('catalog source missing')) as check, \
             patch('src.data.dungeons.definitions.load_dungeons',side_effect=AssertionError('assembly should not run')):
            with self.assertRaisesRegex(ValidationError,'catalog source missing'):
                content.ContentLoader().load()
            check.assert_called_once()

    def test_builtin_current_loading_checks_catalog_registry_before_pinning(self):
        from src.data.dungeons import catalog
        from src.core.validation import ValidationError
        loader=content.ContentLoader()
        with patch.object(catalog,'validate_registry',side_effect=ValidationError('catalog graph invalid')) as check:
            with self.assertRaisesRegex(ValidationError,'catalog graph invalid'):loader.load()
            check.assert_called_once()
        self.assertIsNone(loader._registry)

    def test_fresh_process_definition_equivalence(self):
        code = """
from src.data.content_loader import load_current
from src.data.dungeons.definitions import load_dungeons
from src.data.economy.sect_rules import settings
old=load_dungeons(management=True,cold_jade=True,ecology=True)
new=load_current()
assert old.content_version!=new.content_version
assert all(new.lookup(k)==v for k,v in old._definitions.items())
assert settings(old)==settings(new)
print(len(new._definitions))
"""
        result=subprocess.run([sys.executable,'-B','-c',code],cwd=content.ROOT,
                              capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.strip(),'1772')


class ContentSaveRestartTests(unittest.TestCase):
    def test_paid_jobs_rolls_and_active_battle_survive_both_startup_routes(self):
        from src.application.danding import initial_slice
        from src.application.ecology import EcologyApplication
        from src.application.sect_management import ManagementApplication
        from src.application.memory import Command
        from src.core.save.sqlite import SQLiteSave,V2_ROOT
        from src.core.state.envelope import thaw_json
        from src.systems.equipment import items
        from src.systems.economy import policy
        from tests.fixtures.time import ManualClock
        from tools.playable import game as playable
        for ecology in (False,True):
            with self.subTest(ecology=ecology), tempfile.TemporaryDirectory(dir=V2_ROOT/'tests') as temporary:
                project=Path(temporary);root=project/'.game';root.mkdir()
                path=root/'danding.sqlite3';clock=ManualClock()
                registry=load_dungeons(management=True,cold_jade=True,ecology=ecology)
                cls=EcologyApplication if ecology else ManagementApplication
                state=initial_slice(registry,last_settled_at_ms=clock.now_ms())
                domains=thaw_json(state.domains);domains['disciples']['assignments']={}
                domains['inventory']['holdings'].update(herb=100,spring_water=100,grain=100,coins=1000)
                domains['automation']=thaw_json(policy.initial())
                gear=items.initial();counter=state.identity['instance_counter']
                for version in ('thorn-roll-v2','thorn-forge-v1'):
                    counter+=1
                    gear=items.add(gear,registry,f'{state.save_id}:1:i:{counter}','thorn_fang_blade',
                                   'saved:'+version,0,False,roll_version=version)
                domains['equipment']=gear
                state=replace(state,identity={**state.identity,'instance_counter':counter},domains=domains)
                sid=state.save_id
                with SQLiteSave.initialize(path,allowed_root=root) as store:
                    app=cls(store,registry,clock);app.create(state)
                    def command(name,payload):
                        current=app.query(sid)
                        req=Command(sid,current.generation,current.revision,str(uuid4()),name,payload)
                        return req,app.execute(req)
                    kind='alchemy' if ecology else 'canteen'
                    building=next(k for k,v in app.query(sid).domains['sect']['buildings'].items() if v['definition_id']==kind)
                    command('work_assign',{'building_id':building,'count':1})
                    paid,receipt=command('production_start',{'building_id':building,
                                                'recipe_id':'ju_qi_pill' if ecology else 'sect_food'})
                    command('combat_start',{'encounter_id':'thorn_path_v2_001'})
                    before=app.query(sid)
                    self.assertTrue(before.domains['production']['jobs'])
                    self.assertEqual(before.domains['combat']['battle']['status'],'ACTIVE')
                    self.assertNotEqual(state.domains['inventory'],before.domains['inventory'])
                (root/'save-id').write_text(sid+'\n')
                with patch.object(playable,'PROJECT',project):
                    if ecology:
                        factory,opened=playable.configured_game()
                    else:
                        with patch.object(content,'load_current',side_effect=AssertionError('old route accessed current manifest')):
                            factory,opened=playable.configured_game()
                self.assertEqual(opened,sid)
                # Both configured_game and repeated views are pure even with active jobs.
                with factory() as app:
                    after=app.query(sid)
                    self.assertEqual(before,after)
                    for domain in ('equipment','production','combat'):
                        self.assertEqual(before.domains[domain],after.domains[domain])
                    app.view(sid);app.view(sid)
                    self.assertEqual(before,app.query(sid))
                    self.assertEqual(receipt,app.execute(paid))
                    self.assertEqual(before,app.query(sid))
                # Restart in a fresh interpreter, not just with a new SQLite connection.
                code="""
import json,sys
from pathlib import Path
from unittest.mock import patch
from tools.playable import game
from src.core.state.envelope import thaw_json
with patch.object(game,'PROJECT',Path(sys.argv[1])):
    factory,sid=game.configured_game()
with factory() as app:
    state=app.query(sid)
    print(json.dumps({'revision':state.revision,'domains':thaw_json(state.domains)},sort_keys=True))
"""
                child=subprocess.run([sys.executable,'-B','-c',code,str(project)],cwd=content.ROOT,
                                     capture_output=True,text=True,timeout=30)
                self.assertEqual(child.returncode,0,child.stderr)
                reopened=json.loads(child.stdout)
                self.assertEqual(before.revision,reopened['revision'])
                self.assertEqual(thaw_json(before.domains),reopened['domains'])


class ExplicitRuntimeRouteTests(unittest.TestCase):
    def test_unknown_and_earlier_versions_rejected_before_package_loading(self):
        from src.application.danding import initial_slice
        from src.core.save.sqlite import SQLiteSave,V2_ROOT
        from src.core.validation import ValidationError
        from tools.playable import game
        registry = load_dungeons(management=True,cold_jade=True)
        for version in ('future-content-version',load_dungeons().content_version):
            with self.subTest(version=version),tempfile.TemporaryDirectory(dir=V2_ROOT/'tests') as folder:
                project = Path(folder);root = project/'.game';root.mkdir()
                state = replace(initial_slice(registry,last_settled_at_ms=1000),content_version=version)
                path = root/'danding.sqlite3'
                with SQLiteSave.initialize(path,allowed_root=root) as store:
                    with store.transaction():store.create(state)
                (root/'save-id').write_text(state.save_id)
                with patch.object(game,'PROJECT',project), \
                     patch.object(game,'load_dungeons',side_effect=AssertionError('fallback attempted')), \
                     patch.object(content,'load_current',side_effect=AssertionError('current content attempted')):
                    with self.assertRaisesRegex(ValidationError,'unsupported runtime content version'):
                        game.configured_game()
                with SQLiteSave(path,allowed_root=root) as store:
                    self.assertEqual(store.inspect(state.save_id,include_recovery=False).current,state)


if __name__=='__main__':unittest.main()

"""Central declaration defects and full factory loading with a disposable new dungeon."""
from contextlib import contextmanager
from dataclasses import replace
import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from src.core.state.envelope import freeze_json, thaw_json
from src.core.validation import ValidationError, ConflictError
from src.data import content_loader
from src.data.dungeons import catalog, expeditions, loot
from src.data.dungeons.definitions import load_dungeons
from src.data.registry import DefinitionKey
from src.systems.dungeons import progress


TRIAL = 'catalog_trial'
DECLARATION = catalog.DungeonEntry(TRIAL,'expedition',TRIAL+'.json')


@contextmanager
def trial_content():
    """Real JSON and original assembly; never add definitions by hand."""
    with tempfile.TemporaryDirectory(prefix='dungeon-catalog-') as folder:
        root=Path(folder)
        for source in (content_loader.ROOT/'src/data').rglob('*.json'):
            target=root/source.relative_to(content_loader.ROOT)
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(source,target)
        original=(root/'src/data/dungeons/red_copper_mine.json').read_text()
        data=json.loads(original.replace('red_copper_mine',TRIAL))
        data['unlock']={'dungeon_id':'thorn_path','cleared_floor':100}
        source=root/'src/data/dungeons'/DECLARATION.source
        source.write_text(json.dumps(data))
        manifest=root/content_loader.DEFAULT_MANIFEST
        config=json.loads(manifest.read_text())
        next(row for row in config['packages'] if row['id']=='expeditions')['sources'].append(
            'src/data/dungeons/'+DECLARATION.source)
        manifest.write_text(json.dumps(config))
        from src.data.economy import market
        with patch.object(catalog,'ENTRIES',(*catalog.ENTRIES,DECLARATION)), \
             patch.object(catalog,'__file__',str(root/'src/data/dungeons/catalog.py')), \
             patch.object(market,'__file__',str(root/'src/data/economy/market.py')):
            def assemble(profile):
                # Same checks as production, with a trusted temporary-root seam.
                selected,_=content_loader.content_snapshot(root,content_loader.DEFAULT_MANIFEST)
                catalog.validate_sources(content_loader.validate_manifest(selected))
                return content_loader._assemble_profile(profile)
            loader=content_loader.ContentLoader(root=root,assembler=assemble)
            try:
                yield SimpleNamespace(root=root,source=source,data=data,loader=loader,manifest=manifest)
            finally:
                expeditions.content.cache_clear()


class DungeonCatalogTests(unittest.TestCase):
    def test_current_order_and_frozen_historical_aliases(self):
        catalog.validate_entries()
        self.assertEqual(catalog.all_ids(),('thorn_path','red_copper_mine','mist_marsh','cold_jade_cave','fire_elixir_ruins'))
        self.assertEqual(expeditions.IDS,catalog.HISTORICAL_IDS)
        self.assertEqual(expeditions.ALL_IDS,catalog.HISTORICAL_COLD_JADE_IDS)
        with patch.object(catalog,'ENTRIES',(*catalog.ENTRIES,DECLARATION)):
            self.assertIn(TRIAL,catalog.expedition_ids(current=True))
            self.assertNotIn(TRIAL,catalog.expedition_ids(cold_jade=True))
            self.assertEqual(catalog.expedition_ids(),expeditions.IDS)

    def test_invalid_declarations_are_rejected(self):
        variants=(replace(DECLARATION,machine_id='../bad'),replace(DECLARATION,kind='python.import'),
                  replace(DECLARATION,profile='arbitrary'),replace(DECLARATION,profile='historical'),
                  replace(DECLARATION,source='../outside.json'),replace(DECLARATION,source='/tmp/out.json'),
                  replace(DECLARATION,source='../../outside.json'),replace(DECLARATION,source=123),
                  replace(DECLARATION,source='bad\\name.json'),replace(DECLARATION,kind='thorn'))
        for declaration in variants:
            with self.subTest(declaration=declaration),patch.object(catalog,'ENTRIES',(*catalog.ENTRIES,declaration)):
                with self.assertRaises(ValidationError):catalog.validate_entries()

    def test_duplicate_ids_sources_and_encounter_prefixes_are_rejected(self):
        variants=(catalog.ENTRIES[-1],replace(DECLARATION,source=catalog.ENTRIES[-1].source),
                  replace(DECLARATION,machine_id='thorn_path_extra'))
        for declaration in variants:
            with self.subTest(declaration=declaration),patch.object(catalog,'ENTRIES',(*catalog.ENTRIES,declaration)):
                with self.assertRaises(ValidationError):catalog.validate_entries()

    def test_historical_entries_cannot_be_removed_or_reclassified(self):
        historical=tuple(row for row in catalog.ENTRIES if row.profile=='historical')
        last=historical[-1]
        for entries in (tuple(r for r in catalog.ENTRIES if r!=last),tuple(replace(r,profile='ecology_current') if r==last else r for r in catalog.ENTRIES)):
            with patch.object(catalog,'ENTRIES',entries):
                with self.assertRaises(ValidationError):catalog.validate_entries()

    def test_source_escape_by_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);base=root/'data';base.mkdir();outside=root/'outside.json';outside.write_text('{}')
            (base/'escaped.json').symlink_to(outside)
            with patch.object(catalog,'__file__',str(base/'catalog.py')):
                with self.assertRaises(ValidationError):catalog.source_path(replace(DECLARATION,source='escaped.json'))

    def test_manifest_must_declare_every_dungeon_source(self):
        sources=['src/data/dungeons/'+row.source for row in catalog.ENTRIES]
        catalog.validate_sources(sources)
        with patch.object(catalog,'ENTRIES',(*catalog.ENTRIES,DECLARATION)):
            with self.assertRaisesRegex(ValidationError,'missing from content manifest'):catalog.validate_sources(sources)

    def test_declared_dungeon_json_without_catalog_entry_is_rejected(self):
        with trial_content() as fixture:
            orphan=fixture.source.with_name('orphan_dungeon.json')
            orphan.write_text(fixture.source.read_text())
            data=json.loads(fixture.manifest.read_text())
            next(row for row in data['packages'] if row['id']=='expeditions')['sources'].append(
                'src/data/dungeons/orphan_dungeon.json')
            fixture.manifest.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValidationError,'no catalog entry'):fixture.loader.load()

    def test_historical_roll_checks_do_not_load_future_configurations(self):
        with patch.object(catalog,'ENTRIES',(*catalog.ENTRIES,DECLARATION)), \
             patch.object(expeditions,'content',side_effect=AssertionError('unrelated content read')):
            self.assertIsNone(loot.equipment_roll_version({'loot_version':'thorn-loot-v1'}))
            self.assertIsNone(loot.equipment_roll_version({'loot_version':'unknown-loot-v1'}))

    def test_registry_directory_excludes_unregistered_and_future_entries(self):
        old=load_dungeons(legacy=True)
        with patch.object(catalog,'ENTRIES',(*catalog.ENTRIES,DECLARATION)):
            self.assertEqual(catalog.registered_ids(old),('thorn_path',))
            self.assertEqual([row['id'] for row in progress.directory(progress.initial(),old)],['thorn_path'])

    def test_legacy_loot_resolution_works_before_dungeon_registration(self):
        r=load_dungeons(expansion_legacy=True)
        loot_key=DefinitionKey('loot','thorn_path')
        partial=SimpleNamespace(contains=lambda key:key==loot_key,lookup=lambda key:r.lookup(key))
        self.assertEqual(expeditions.loot_version(partial,'thorn_path_v2_001'),'thorn-loot-v2')
        self.assertIsNone(expeditions.owner(partial,'thorn_path_v2_001'))
        for version in ('thorn-loot-v1','thorn-loot-v2'):
            self.assertTrue(expeditions.valid_loot_version(r,'thorn_path_v2_001',version))

    def test_full_current_factory_registers_trial_and_historical_profiles_do_not(self):
        with trial_content() as fixture:
            registry=fixture.loader.load()
            self.assertEqual(catalog.registered_ids(registry)[-1],TRIAL)
            definition=progress.definition(registry,TRIAL)
            self.assertEqual(len(definition.encounters),100)
            self.assertEqual(expeditions.owner(registry,definition.encounters[0]),TRIAL)
            for flags in ({},{'cold_jade':True},{'management':True,'cold_jade':True},{'legacy':True}):
                historical=load_dungeons(**flags)
                self.assertFalse(historical.contains(DefinitionKey('dungeons',TRIAL)),flags)
                self.assertNotIn(TRIAL,catalog.registered_ids(historical))

    def test_trial_gate_selection_progress_drops_and_roll_version_are_connected(self):
        with trial_content() as fixture:
            registry=fixture.loader.load();part=progress.initial()
            self.assertFalse(progress.unlocked(part,registry,TRIAL))
            with self.assertRaises(ConflictError):progress.choose(part,registry,TRIAL)
            part={**part,'cleared_floor':100}
            selected=progress.choose(part,registry,TRIAL)
            directory=progress.directory(selected,registry)
            self.assertEqual([row['id'] for row in directory][-1],TRIAL)
            self.assertEqual(directory[-1]['unlock_condition'],{'dungeon_id':'thorn_path','cleared_floor':100})
            encounter=progress.definition(registry,TRIAL).encounters[0]
            self.assertEqual(progress.require_unlocked(selected,registry,encounter),encounter)
            claimed=progress.claimed(selected,registry,{'encounter_id':encounter,'status':'SETTLED'})
            self.assertEqual(progress.cleared(claimed,TRIAL),1)
            self.assertEqual(progress.next_encounter(claimed,registry),progress.definition(registry,TRIAL).encounters[1])
            boss=progress.definition(registry,TRIAL).encounters[-1]
            version=expeditions.loot_version(registry,boss)
            battle={'encounter_id':boss,'battle_id':'fixed-trial-boss','loot_version':version}
            result=loot.plan(registry,battle)
            self.assertEqual(result,loot.plan(registry,battle))
            self.assertTrue(result['amounts']);self.assertIsNotNone(result['equipment'])
            self.assertTrue(registry.contains(DefinitionKey('equipment',result['equipment'])))
            for resource in result['amounts']:self.assertTrue(registry.contains(DefinitionKey('resources',resource)))
            self.assertEqual(loot.equipment_roll_version(battle),TRIAL+'-roll-v1')
            self.assertTrue(expeditions.valid_loot_version(registry,boss,version))
            self.assertFalse(expeditions.valid_loot_version(registry,boss,'thorn-loot-v2'))
            from src.systems.equipment import items
            gear=items.add(items.initial(),registry,'trial-equipment',result['equipment'],'trial-boss',0,False,
                           roll_version=loot.equipment_roll_version(battle))
            items.validate(gear,registry,'trial-save')

    def test_trial_configuration_id_must_match_declaration(self):
        with trial_content() as fixture:
            fixture.data['id']='wrong_id';fixture.source.write_text(json.dumps(fixture.data))
            with self.assertRaisesRegex(ValidationError,'invalid expedition package'):fixture.loader.load()

    def test_trial_missing_references_fail_assembly(self):
        with trial_content() as fixture:
            fixture.data['loot']['normal_materials'][0]='missing_trial_material'
            fixture.source.write_text(json.dumps(fixture.data))
            with self.assertRaises(ValidationError):fixture.loader.load()

    def test_trial_duplicate_resource_id_fails_assembly(self):
        with trial_content() as fixture:
            fixture.data['materials'][0]['id']='coins';fixture.source.write_text(json.dumps(fixture.data))
            with self.assertRaises(ValidationError):fixture.loader.load()

    def test_missing_unlock_target_fails_current_assembly(self):
        with trial_content() as fixture:
            fixture.data['unlock']['dungeon_id']='missing_dungeon';fixture.source.write_text(json.dumps(fixture.data))
            with self.assertRaisesRegex(ValidationError,'unregistered dungeon unlock target'):fixture.loader.load()

    def test_cyclic_unlock_graph_fails_current_assembly(self):
        with trial_content() as fixture:
            path=fixture.root/'src/data/dungeons/red_copper_mine.json';parent=json.loads(path.read_text())
            parent['unlock']['dungeon_id']=TRIAL;path.write_text(json.dumps(parent))
            fixture.data['unlock']['dungeon_id']='red_copper_mine';fixture.source.write_text(json.dumps(fixture.data))
            with self.assertRaisesRegex(ValidationError,'cyclic dungeon unlock graph'):fixture.loader.load()

    def test_unlock_floor_over_target_range_is_rejected(self):
        with trial_content() as fixture:
            fixture.data['unlock']['cleared_floor']=101;fixture.source.write_text(json.dumps(fixture.data))
            with self.assertRaisesRegex(ValidationError,'unlock floor out of range'):fixture.loader.load()

    def test_market_source_accepts_new_registered_dungeon(self):
        with trial_content() as fixture:
            path=fixture.root/'src/data/economy/market.json';data=json.loads(path.read_text())
            resource=next(iter(data['items']));data['items'][resource]['unlock']={TRIAL:10}
            path.write_text(json.dumps(data));registry=fixture.loader.load()
            self.assertEqual(dict(registry.lookup(DefinitionKey('market_rules','shipping')).values['items'][resource]['unlock']),{TRIAL:10})

    def test_unknown_market_source_blocks_assembly(self):
        with trial_content() as fixture:
            path=fixture.root/'src/data/economy/market.json';data=json.loads(path.read_text())
            data['items'][next(iter(data['items']))]['unlock']={'unknown_dungeon':10}
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValidationError,'invalid material source'):fixture.loader.load()

    def test_postassembly_market_source_cannot_be_unregistered_or_out_of_range(self):
        registry=load_dungeons(management=True,cold_jade=True,ecology=True)
        key=DefinitionKey('market_rules','shipping');original=registry.lookup(key)
        for source,floor in (('missing_dungeon',1),('thorn_path',101)):
            data=thaw_json(original.values);data['items'][next(iter(data['items']))]['unlock']={source:floor}
            broken=replace(original,values=freeze_json(data))
            fake=SimpleNamespace(is_sealed=True,_definitions=registry._definitions,contains=registry.contains,
                                 lookup=lambda requested:broken if requested==key else registry.lookup(requested))
            with self.subTest(source=source),self.assertRaises(ValidationError):catalog.validate_registry(fake)

    def test_current_registry_coverage_cannot_omit_a_declaration(self):
        registry=load_dungeons(management=True,cold_jade=True,ecology=True)
        with patch.object(catalog,'ENTRIES',(*catalog.ENTRIES,DECLARATION)):
            with self.assertRaisesRegex(ValidationError,'coverage differs'):catalog.validate_registry(registry)


class DungeonCatalogSaveTests(unittest.TestCase):
    def temporary_save(self):
        from src.core.save.sqlite import V2_ROOT
        temp=tempfile.TemporaryDirectory(dir=V2_ROOT/'tests');self.addCleanup(temp.cleanup)
        root=Path(temp.name)
        return root,root/'catalog.sqlite3'

    def test_legacy_missing_progress_defaults_are_not_saved_on_read(self):
        from src.application.danding import initial_slice
        from src.application.sect_management import ManagementApplication
        from src.core.save.sqlite import SQLiteSave
        from tests.fixtures.time import ManualClock
        root,path=self.temporary_save();clock=ManualClock()
        registry=load_dungeons(management=True,cold_jade=True)
        state=initial_slice(registry,last_settled_at_ms=clock.now_ms())
        with SQLiteSave.initialize(path,allowed_root=root) as store:
            app=ManagementApplication(store,registry,clock);app.create(state);before=app.query(state.save_id)
            self.assertNotIn('selected_id',before.domains['dungeon']);self.assertNotIn('progress',before.domains['dungeon'])
        with SQLiteSave(path,allowed_root=root) as store:
            app=ManagementApplication(store,load_dungeons(management=True,cold_jade=True),clock)
            app.view(state.save_id);app.view(state.save_id)
            self.assertEqual(before,app.query(state.save_id))

    def test_existing_progress_farm_cursor_and_event_deadline_survive_reopen(self):
        from src.application.danding import initial_slice
        from src.application.ecology import EcologyApplication
        from src.application.memory import Command
        from src.core.save.sqlite import SQLiteSave
        from tests.fixtures.time import ManualClock
        root,path=self.temporary_save();clock=ManualClock();registry=content_loader.load_current()
        state=initial_slice(registry,last_settled_at_ms=clock.now_ms())
        dungeon={**progress.initial(),'cleared_floor':100,'selected_id':'cold_jade_cave',
                 'progress':{'red_copper_mine':100,'mist_marsh':100,'cold_jade_cave':17}}
        state=replace(state,domains={**state.domains,'dungeon':dungeon})
        with SQLiteSave.initialize(path,allowed_root=root) as store:
            app=EcologyApplication(store,registry,clock);app.create(state);current=app.query(state.save_id)
            req=Command(state.save_id,current.generation,current.revision,str(uuid4()),'dungeon_auto',
                        {'enabled':True,'mode':'farm','floor':10,'floor_count':3})
            receipt=app.execute(req);before=app.query(state.save_id)
            auto=before.domains['dungeon']['auto']
            self.assertTrue(auto['enabled']);self.assertIsNotNone(auto['wake'])
            self.assertEqual(auto['floor_count'],3)
        with SQLiteSave(path,allowed_root=root) as store:
            app=EcologyApplication(store,content_loader.ContentLoader().load(),clock)
            app.view(state.save_id);after=app.query(state.save_id)
            self.assertEqual(before,after);self.assertEqual(auto,after.domains['dungeon']['auto'])
            self.assertEqual(receipt,app.execute(req));self.assertEqual(before,app.query(state.save_id))

    def test_trial_selection_active_battle_and_receipt_survive_real_sqlite_reopen(self):
        from src.application.danding import initial_slice
        from src.application.ecology import EcologyApplication
        from src.application.memory import Command
        from src.core.save.sqlite import SQLiteSave
        from tests.fixtures.time import ManualClock
        root,path=self.temporary_save();clock=ManualClock()
        with trial_content() as fixture:
            registry=fixture.loader.load();state=initial_slice(registry,last_settled_at_ms=clock.now_ms())
            state=replace(state,domains={**state.domains,'dungeon':{**progress.initial(),'cleared_floor':100}})
            with SQLiteSave.initialize(path,allowed_root=root) as store:
                app=EcologyApplication(store,registry,clock);app.create(state)
                def command(name,payload):
                    current=app.query(state.save_id)
                    request=Command(state.save_id,current.generation,current.revision,str(uuid4()),name,payload)
                    return request,app.execute(request)
                command('dungeon_select',{'dungeon_id':TRIAL})
                encounter=progress.definition(registry,TRIAL).encounters[0]
                request,receipt=command('combat_start',{'encounter_id':encounter})
                before=app.query(state.save_id)
                self.assertEqual(before.domains['combat']['battle']['status'],'ACTIVE')
                self.assertEqual([row['id'] for row in app.view(state.save_id)['combat']['dungeons']][-1],TRIAL)
            with SQLiteSave(path,allowed_root=root) as store:
                app=EcologyApplication(store,fixture.loader.load(),clock)
                app.view(state.save_id)
                self.assertEqual(before,app.query(state.save_id))
                self.assertEqual(receipt,app.execute(request));self.assertEqual(before,app.query(state.save_id))


if __name__=='__main__':unittest.main()

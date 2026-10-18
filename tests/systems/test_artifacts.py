"""Disposable SQLite integration: crafting, preservation, growth and shared combat."""
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
from unittest.mock import patch
import json
import unittest

from src.application.danding import initial_slice
from src.application.ecology import EcologyApplication
from src.application.memory import Command
from src.application.settlement import SettlementRequest
from src.application.artifact_upgrade import upgrade
from src.core.save.sqlite import SQLiteSave, V2_ROOT
from src.core.state.envelope import thaw_json
from src.core.validation import ValidationError, ConflictError
from src.core.time.model import Continuation
from src.data.content_loader import load_current
from src.data.dungeons.definitions import load_dungeons
from src.data.artifacts import definitions as data
from src.data.registry import DefinitionKey
from src.systems.artifacts import artifacts
from src.systems.dungeons import progress
from src.systems.combat import battle
from tests.fixtures.time import ManualClock


class ArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.registry=load_current()

    def setUp(self):
        self.temp=TemporaryDirectory(dir=V2_ROOT/'tests');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.path=self.root/'test.sqlite3';self.clock=ManualClock()
        self.key='slayer_sword';self.row=data.definition(self.registry,self.key)
        state=initial_slice(self.registry,last_settled_at_ms=self.clock.now_ms());self.sid=state.save_id
        stock=thaw_json(state.domains['inventory']);stock['holdings'].update(self.row['inputs']);stock['holdings'].update(coins=10000,crafting_essence=100,beast_bone=150)
        dungeon=thaw_json(progress.initial());dungeon['cleared_floor']=100
        self.seed=replace(state,domains={**state.domains,'inventory':stock,'dungeon':dungeon})
        with SQLiteSave.initialize(self.path,allowed_root=self.root) as store:EcologyApplication(store,self.registry,self.clock).create(self.seed)

    def read(self):
        with SQLiteSave(self.path,allowed_root=self.root) as store:return EcologyApplication(store,self.registry,self.clock).query(self.sid)

    def execute(self,name,payload,request=None):
        state=self.read();q=request or Command(self.sid,state.generation,state.revision,str(uuid4()),name,payload)
        with SQLiteSave(self.path,allowed_root=self.root) as store:return EcologyApplication(store,self.registry,self.clock).execute(q)

    def settle(self,ms):
        self.clock.advance(ms)
        for _ in range(50):
            s=self.read();q=SettlementRequest(self.sid,s.generation,s.revision,str(uuid4()),max_events=1000,continuation=Continuation.for_state(s) if s.time['pending'] else None)
            with SQLiteSave(self.path,allowed_root=self.root) as store:result=EcologyApplication(store,self.registry,self.clock).settle(q)
            if not self.read().time['pending']:return result
        self.fail('bounded continuation did not complete')

    def craft(self,key=None):
        key=key or self.key;self.execute('artifact_craft',{'artifact_id':key});self.settle(data.definition(self.registry,key)['duration_ms'])

    def test_catalog_sealed_and_actual_boss_materials(self):
        self.assertTrue(self.registry.is_sealed);self.assertEqual(len(data.settings(self.registry)['artifacts']),5)
        for row in data.settings(self.registry)['artifacts'].values():
            d=self.registry.lookup(DefinitionKey('dungeons',row['source_dungeon_id']))
            self.assertEqual(row['source_boss_id'],self.registry.lookup(DefinitionKey('encounters',d.encounters[-1])).monster_id)

    def test_craft_deducts_once_and_completes_after_exact_duration(self):
        before=self.read();q=Command(self.sid,1,before.revision,str(uuid4()),'artifact_craft',{'artifact_id':self.key})
        first=self.execute('',{},q);self.assertEqual(first,self.execute('',{},q))
        after=self.read();self.assertEqual(after.domains['inventory']['holdings'].get(self.row['core_material_id'],0),0)
        self.settle(self.row['duration_ms']-1);self.assertNotIn(self.key,self.read().domains['artifacts']['owned'])
        self.settle(1);state=self.read();self.assertIn(self.key,state.domains['artifacts']['owned']);self.assertIsNone(state.domains['artifacts']['job'])
        self.settle(1);self.assertEqual(self.read().domains['artifacts'],state.domains['artifacts'])
        with self.assertRaises(ValidationError):self.execute('artifact_craft',{'artifact_id':self.key})

    def test_failure_and_stale_request_do_not_consume(self):
        before=self.read()
        with self.assertRaises(ValidationError):self.execute('artifact_craft',{'artifact_id':'fire_gourd'})
        self.assertEqual(before,self.read())
        with self.assertRaises(ConflictError):self.execute('',{},Command(self.sid,1,before.revision+1,str(uuid4()),'artifact_craft',{'artifact_id':self.key}))
        self.assertEqual(before,self.read())

    def test_second_craft_rejected_without_extra_deduction(self):
        self.execute('artifact_craft',{'artifact_id':self.key});before=self.read()
        with self.assertRaises(ValidationError):self.execute('artifact_craft',{'artifact_id':self.key})
        self.assertEqual(before,self.read())

    def test_reserve_protects_crafting_and_feeding(self):
        self.execute('material_reserve',{'resource_id':self.row['core_material_id'],'quantity':1})
        before=self.read()
        with self.assertRaises(ValidationError):self.execute('artifact_craft',{'artifact_id':self.key})
        self.assertEqual(before,self.read())

    def test_equip_enhance_projection_and_feed(self):
        self.craft();before=self.read()
        self.execute('artifact_equip',{'artifact_id':self.key})
        with SQLiteSave(self.path,allowed_root=self.root) as store:
            app=EcologyApplication(store,self.registry,self.clock);s=app.query(self.sid);actor=app.player_projection(s)
            self.assertEqual(app.project_world(s)['artifacts']['equipped'],self.key)
        self.execute('artifact_enhance',{'artifact_id':self.key})
        with SQLiteSave(self.path,allowed_root=self.root) as store:
            app=EcologyApplication(store,self.registry,self.clock);new=app.player_projection(app.query(self.sid))
        self.assertEqual(new['attack_milli']-actor['attack_milli'],200)
        # Feeding consumes a monster material left after crafting.
        self.execute('artifact_feed',{'artifact_id':self.key,'resource_id':'beast_bone','quantity':1})
        self.assertEqual(self.read().domains['artifacts']['owned'][self.key]['xp'],5)
        self.execute('artifact_unequip',{});self.assertIsNone(self.read().domains['artifacts']['equipped'])

    def test_battle_snapshot_and_reward_experience_exactly_once(self):
        self.craft();self.execute('artifact_equip',{'artifact_id':self.key})
        self.execute('combat_start',{'encounter_id':'thorn_path_v2_001'})
        state=self.read();b=state.domains['combat']['battle'];self.assertEqual(b['artifact_snapshot']['artifact_id'],self.key)
        with self.assertRaises(ValidationError):self.execute('artifact_enhance',{'artifact_id':self.key})
        for _ in range(50):
            state=self.read();b=state.domains['combat']['battle']
            if b['status']!='ACTIVE':break
            self.execute('combat_attack',{'battle_id':b['battle_id']})
        self.assertEqual(self.read().domains['combat']['battle']['status'],'PLAYER_WIN')
        s=self.read();q=Command(self.sid,1,s.revision,str(uuid4()),'combat_reward',{'battle_id':b['battle_id']})
        self.execute('',{},q);self.execute('',{},q)
        self.assertEqual(self.read().domains['artifacts']['owned'][self.key]['xp'],2)
        self.execute('combat_reward',{'battle_id':b['battle_id']})
        self.assertEqual(self.read().domains['artifacts']['owned'][self.key]['xp'],2)

    def test_all_effects_real_execution_and_frozen_source_validation(self):
        for key in data.settings(self.registry)['artifacts']:
            with self.subTest(key=key):
                p=dict(battle.player(self.registry,'design'));p.update(max_hp_milli=10000000,attack_milli=1000)
                snap={'artifact_id':key,'level':5,'enhancement':0}
                combat=battle.start(battle.initial(),self.registry,'design','test-artifact','thorn_path_v2_100',player_snapshot=p,artifact_snapshot=snap)
                fired=False
                for _ in range(20):
                    if combat['battle']['status']!='ACTIVE':break
                    combat=battle.attack(combat,self.registry,'design','test-artifact')
                    fired|=any(k.startswith('artifacts:') for k in combat['battle']['mechanics']['counts'])
                if key!='soul_banner':self.assertTrue(fired)
                battle.validate(combat,self.registry,'design')
                corrupt=thaw_json(combat);corrupt['battle']['artifact_snapshot']['level']=6
                with self.assertRaises(ValidationError):battle.validate(corrupt,self.registry,'design')

    def test_snapshot_source_is_not_current_training(self):
        self.craft();self.execute('artifact_equip',{'artifact_id':self.key})
        self.execute('combat_start',{'encounter_id':'thorn_path_v2_001'})
        snap=self.read().domains['combat']['battle']['artifact_snapshot']
        self.assertEqual(snap['level'],1)

    def test_content_extension_reuses_behavior_without_page_edits(self):
        source=Path('src/data/artifacts/catalog.json');cfg=json.loads(source.read_text())
        extra=dict(cfg['artifacts']['slayer_sword']);extra.update(name='扩展试炼剑',recipe_id='forge_artifact_extension')
        cfg['artifacts']['extension_sword']=extra
        from src.data.artifacts import definitions
        original=definitions.read_json
        def reader(path):return (cfg,'test') if path.name=='catalog.json' else original(path)
        with patch.object(definitions,'read_json',side_effect=reader):r=load_dungeons(management=True,cold_jade=True,ecology=True,mechanics=True,skill_timing=True,artifacts=True)
        self.assertIn('extension_sword',data.settings(r)['artifacts'])
        self.assertEqual(data.definition(r,'extension_sword')['effect_id'],'pursuit')

    def test_new_dungeon_boss_and_artifact_bind_through_catalog_only(self):
        from src.data.dungeons import catalog, expeditions
        from src.application.artifacts import view
        original=expeditions.content
        package=json.loads(json.dumps(thaw_json(original('red_copper_mine'))).replace('red_copper_mine','artifact_trial'))
        package['name']='法宝接入试炼';package['unlock']={'dungeon_id':'thorn_path','cleared_floor':100}
        cfg=json.loads(Path('src/data/artifacts/catalog.json').read_text())
        row=dict(cfg['artifacts']['mountain_cauldron']);row.update(name='试炼鼎',source_dungeon_id='artifact_trial',source_boss_id='artifact_trial_v1_enemy_100',core_material_id='artifact_trial_material_11',recipe_id='forge_artifact_trial',inputs={'artifact_trial_material_11':10,'artifact_trial_material_01':200,'coins':3000})
        cfg['artifacts']['trial_cauldron']=row;cfg['feed']['artifact_trial_material_01']=20
        entry=catalog.DungeonEntry('artifact_trial','expedition','artifact_trial.json')
        with patch.object(catalog,'ENTRIES',(*catalog.ENTRIES,entry)),patch.object(expeditions,'content',side_effect=lambda identity:package if identity=='artifact_trial' else original(identity)),patch.object(data,'read_json',return_value=(cfg,'test')):
            r=load_dungeons(management=True,cold_jade=True,ecology=True,mechanics=True,skill_timing=True,artifacts=True)
            current=view(self.read(),r)
            added=next(item for item in current['catalog'] if item['id']=='trial_cauldron')
            self.assertEqual(added['source_name'],'法宝接入试炼');self.assertEqual(added['effect_id'],'shield')
            self.assertTrue(r.contains(DefinitionKey('resources','artifact_trial_material_11')))

    def test_bad_effect_source_and_missing_material_rejected(self):
        source=Path('src/data/artifacts/catalog.json')
        for field,value in [('effect_id','unknown'),('source_boss_id','missing'),('core_material_id','beast_bone')]:
            cfg=json.loads(source.read_text());cfg['artifacts'][self.key][field]=value
            with patch.object(data,'read_json',return_value=(cfg,'test')):
                with self.assertRaises(ValidationError):load_dungeons(management=True,cold_jade=True,ecology=True,mechanics=True,skill_timing=True,artifacts=True)

    def test_get_is_pure(self):
        before=self.read()
        with SQLiteSave(self.path,allowed_root=self.root) as store:
            app=EcologyApplication(store,self.registry,self.clock);app.view(self.sid);app.view(self.sid)
        self.assertEqual(before,self.read())


    def test_feed_reserves_and_max_level_never_waste_stock(self):
        self.craft();self.execute('material_reserve',{'resource_id':'beast_bone','quantity':50})
        before=self.read()
        with self.assertRaises(ValidationError):self.execute('artifact_feed',{'artifact_id':self.key,'resource_id':'beast_bone','quantity':1})
        self.assertEqual(before,self.read())
        from src.application.artifacts import transition
        part=thaw_json(before.domains['artifacts']);maximum=artifacts.threshold(self.registry,20);part['owned'][self.key]['xp']=maximum-2
        reserves=thaw_json(before.domains['sect_management']);reserves['material_reserves']={}
        test=replace(before,domains={**before.domains,'artifacts':part,'sect_management':reserves})
        candidate,result=transition(test,self.registry,'artifact_feed',{'artifact_id':self.key,'resource_id':'beast_bone','quantity':50})
        self.assertEqual(result['cost'],{'beast_bone':1});self.assertEqual(candidate.domains['artifacts']['owned'][self.key]['xp'],maximum)
        with self.assertRaises(ValidationError):transition(candidate,self.registry,'artifact_feed',{'artifact_id':self.key,'resource_id':'beast_bone','quantity':1})

    def test_invalid_feed_and_uncrafted_equip_do_not_mutate(self):
        before=self.read()
        for name,payload in [('artifact_equip',{'artifact_id':self.key}),('artifact_feed',{'artifact_id':self.key,'resource_id':'coins','quantity':1})]:
            with self.assertRaises(ValidationError):self.execute(name,payload)
            self.assertEqual(before,self.read())

    def test_pause_blocks_crafting_and_freezes_elapsed_time(self):
        self.execute('artifact_craft',{'artifact_id':self.key});self.execute('world_pause',{})
        before=self.read()
        from src.core.time.world import WorldPaused
        with self.assertRaises(WorldPaused):self.settle(self.row['duration_ms'])
        after=self.read()
        self.assertEqual(before.domains['artifacts'],after.domains['artifacts']);self.assertEqual(before.time['sim_time_ms'],after.time['sim_time_ms'])
        self.execute('world_resume',{});self.settle(self.row['duration_ms']);self.assertIn(self.key,self.read().domains['artifacts']['owned'])

    def test_kill_heal_and_burn_have_real_special_effects(self):
        actor=dict(battle.player(self.registry,'design'));actor.update(max_hp_milli=90000,attack_milli=50000)
        state=thaw_json(battle.start(battle.initial(),self.registry,'design','soul-test','thorn_path_v2_001',player_snapshot=actor,artifact_snapshot={'artifact_id':'soul_banner','level':1,'enhancement':0}))
        state['battle']['player_hp_milli']=40000
        after=battle.attack(state,self.registry,'design','soul-test')['battle']
        self.assertEqual(after['status'],'PLAYER_WIN')
        heal=next(e for e in after['latest_events'] if e['kind']=='heal' and e.get('source_id')=='artifacts:soul_banner')
        self.assertEqual(heal['damage_milli'],3000)
        self.assertLessEqual(after['player_hp_milli'],43000)
        self.assertTrue(any(e['kind']=='heal' and e.get('source_id')=='artifacts:soul_banner' for e in after['latest_events']))
        state=battle.start(battle.initial(),self.registry,'design','fire-test','thorn_path_v2_100',player_snapshot=actor,artifact_snapshot={'artifact_id':'fire_gourd','level':1,'enhancement':0})
        after=battle.attack(state,self.registry,'design','fire-test')['battle']
        self.assertTrue(any(row['status_id']=='burn' for row in after['mechanics']['statuses']['enemy']))

    def test_online_offline_farming_awards_same_artifact_xp_and_loot(self):
        import shutil
        self.craft();self.execute('artifact_equip',{'artifact_id':self.key})
        self.execute('dungeon_auto',{'enabled':True,'mode':'farm','floor':1,'floor_count':1})
        alternate=self.root/'online.sqlite3';shutil.copy2(self.path,alternate);anchor=self.clock.value
        self.settle(20000);offline=self.read()
        self.path=alternate;self.clock.value=anchor
        for _ in range(10):self.settle(2000)
        online=self.read()
        self.assertGreater(offline.domains['artifacts']['owned'][self.key]['xp'],0)
        self.assertEqual(offline.domains['artifacts'],online.domains['artifacts'])
        self.assertEqual(offline.domains['inventory'],online.domains['inventory'])
        self.assertEqual(offline.domains['dungeon']['auto']['wins'],online.domains['dungeon']['auto']['wins'])

    def test_failed_sql_commit_rolls_back_inputs_and_crafting(self):
        before=self.read();q=Command(self.sid,1,before.revision,str(uuid4()),'artifact_craft',{'artifact_id':self.key})
        with SQLiteSave(self.path,allowed_root=self.root) as store:
            app=EcologyApplication(store,self.registry,self.clock)
            with patch.object(store,'commit',side_effect=RuntimeError('injected commit failure')):
                with self.assertRaises(RuntimeError):app.execute(q)
        self.assertEqual(before,self.read())
        self.execute('',{},q);self.assertIsNotNone(self.read().domains['artifacts']['job'])


class ArtifactUpgradeTests(unittest.TestCase):
    def test_upgrade_preserves_original_domains_and_replays(self):
        old=load_dungeons(management=True,cold_jade=True,ecology=True,mechanics=True,skill_timing=True);clock=ManualClock()
        with TemporaryDirectory(dir=V2_ROOT/'tests') as tmp:
            root=Path(tmp)
            with SQLiteSave.initialize(root/'upgrade.sqlite3',allowed_root=root) as store:
                app=EcologyApplication(store,old,clock);seed=initial_slice(old,last_settled_at_ms=clock.now_ms());app.create(seed);s=app.query(seed.save_id)
                q=Command(s.save_id,s.generation,s.revision,str(uuid4()),'artifact_content_upgrade',{})
                first=upgrade(store,clock,q);self.assertEqual(first,upgrade(store,clock,q))
                now=EcologyApplication(store,load_current(),clock).query(seed.save_id)
                self.assertEqual({k:now.domains[k] for k in s.domains},s.domains)
                self.assertEqual(now.domains['artifacts'],artifacts.initial());self.assertEqual(now.time,s.time);self.assertEqual(now.identity,s.identity)


class ArtifactHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.registry=load_current()
    read=ArtifactTests.read

    def setUp(self):
        from contextlib import contextmanager
        from werkzeug.test import Client
        from werkzeug.wrappers import Response
        from src.transport.danding import create_app
        ArtifactTests.setUp(self)
        @contextmanager
        def factory():
            with SQLiteSave(self.path,allowed_root=self.root) as store:yield EcologyApplication(store,self.registry,self.clock)
        app=create_app(factory,self.sid,lambda view:{},lambda _:None,'artifact-isolated-http-token-2026',secure=False,ui_root=Path('src/ui/pages/game').resolve(),cookie_path='/')
        app.testing=True;self.client=Client(app,Response)
        self.client.post('/login',data={'token':'artifact-isolated-http-token-2026'})

    def body(self):
        view=self.client.get('/api/view').json
        return {'protocol_version':1,'save_id':self.sid,'generation':view['generation'],'expected_revision':view['revision'],'request_id':str(uuid4()),'command':{'name':'artifact_craft','version':1,'payload':{'artifact_id':self.key}}}

    def test_real_http_craft_replay_and_pure_get(self):
        before=self.read();response=self.client.get('/api/view');self.assertEqual(response.status_code,200)
        self.assertEqual(len(response.json['view']['artifacts']['catalog']),5);self.assertEqual(before,self.read())
        body=self.body();headers={'X-CSRF-Token':self.client.get('/api/view').json['csrf']}
        self.assertEqual(self.client.post('/api/command',json=body,headers=headers).status_code,200)
        committed=self.read();self.assertEqual(self.client.post('/api/command',json=body,headers=headers).status_code,200)
        self.assertEqual(committed,self.read());self.assertIsNotNone(committed.domains['artifacts']['job'])

    def test_http_requires_csrf_and_rejects_bad_artifact(self):
        before=self.read();body=self.body();response=self.client.post('/api/command',json=body)
        self.assertEqual(response.status_code,403);self.assertEqual(before,self.read())
        body['command']['payload']['artifact_id']='missing'
        response=self.client.post('/api/command',json=body,headers={'X-CSRF-Token':self.client.get('/api/view').json['csrf']})
        self.assertIn(response.status_code,(400,422));self.assertEqual(before,self.read())


class ArtifactOperatorTests(unittest.TestCase):
    def test_dry_run_then_explicit_upgrade_with_backups(self):
        from tools.playable.artifact_upgrade import run
        old=load_dungeons(management=True,cold_jade=True,ecology=True,mechanics=True,skill_timing=True);clock=ManualClock()
        with TemporaryDirectory(dir=V2_ROOT/'.tmp') as temp:
            root=Path(temp);path=root/'danding.sqlite3'
            with SQLiteSave.initialize(path,allowed_root=root) as store:
                app=EcologyApplication(store,old,clock);seed=initial_slice(old,last_settled_at_ms=clock.now_ms());app.create(seed);before=app.query(seed.save_id)
            (root/'save-id').write_text(seed.save_id)
            self.assertEqual(run(root)['status'],'DRY_RUN')
            with SQLiteSave(path,allowed_root=root) as store:self.assertEqual(EcologyApplication(store,old,clock).query(seed.save_id),before)
            result=run(root,True)
            for key in ('backup','database_backup'):
                backup=Path(result[key]);self.assertTrue(backup.is_file());self.addCleanup(backup.unlink)
            self.assertEqual(result['status'],'UPGRADED')
            with SQLiteSave(path,allowed_root=root) as store:
                after=EcologyApplication(store,load_current(),clock).query(seed.save_id)
                self.assertEqual(after.domains['artifacts'],artifacts.initial())
                self.assertEqual({k:after.domains[k] for k in before.domains},before.domains)

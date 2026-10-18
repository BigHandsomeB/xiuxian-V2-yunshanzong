"""Real configured effects, legacy preservation and deterministic settlement parity."""
import json
import unittest
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from uuid import uuid4
from src.core.state.envelope import thaw_json,freeze_json
from src.core.validation import ValidationError
from src.data.content_loader import load_current
from src.data.combat.mechanics import settings,ROLL_VERSION
from src.data.dungeons.definitions import load_dungeons
from src.data.registry import DefinitionKey
from src.systems.combat import battle,mechanics
from src.systems.equipment import items

class EffectsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry=load_dungeons(management=True,cold_jade=True,ecology=True,mechanics=True);cls.config=settings(cls.registry)
        cls.manuals={r['name']:key for key,r in cls.config['techniques'].items()}
    def start(self,*names,enemy='thorn_path_v2_001',attack=10000,hp=1000000):
        p=dict(battle.player(self.registry,'design'));p.update(max_hp_milli=hp,attack_milli=attack,armor_milli=0,accuracy_bps=1000)
        part=thaw_json(battle.start(battle.initial(),self.registry,'design','effect-test',enemy,player_snapshot=p))
        part['battle']['mechanics']['sources']=[{'group':'techniques','id':self.manuals[n],'level':1} for n in names]
        return part
    def engine(self,part):
        b=part['battle'];return mechanics.Round(b,battle.effective_monster(self.registry,b),b['player_snapshot'],self.config)
    def test_catalog_complete_and_real_fifth_unlock(self):
        self.assertEqual(len(self.config['techniques']),150);self.assertEqual(len(self.config['equipment']),60)
        from src.data.dungeons.expeditions import content
        fifth=content('fire_elixir_ruins')
        self.assertEqual(fifth['unlock'],{'dungeon_id':'cold_jade_cave','cleared_floor':100})
        self.assertEqual(len(fifth['equipment']),12);self.assertEqual(len(fifth['materials']),12)
        self.assertEqual(self.registry.lookup(DefinitionKey('monsters','fire_elixir_ruins_v1_enemy_001')).base_hp_milli,304000)
    def test_old_ecology_factory_keeps_four_dungeons(self):
        from src.data.dungeons import catalog
        old=load_dungeons(management=True,cold_jade=True,ecology=True)
        self.assertEqual(len(catalog.registered_ids(old)),4)
        self.assertEqual(len(catalog.registered_ids(self.registry)),5)
    def test_fifth_material_sources_match_actual_monster_templates(self):
        from src.data.dungeons import loot,expeditions
        package=expeditions.content('fire_elixir_ruins');material_ids={r['id'] for r in package['materials']}
        floors=[1,2,21,22,41,42,61,62,81,82,10,30,50,70,90]
        expected=[r['id'] for r in package['materials'][:10]]+list(package['loot']['elite_materials'])
        for floor,resource in zip(floors,expected):
            found=False
            for seed in range(64):
                b=battle.start(battle.initial(),self.registry,'design',f'material:{floor}:{seed}',f'fire_elixir_ruins_v1_{floor:03}')['battle']
                drop=loot.plan(self.registry,b);actual=material_ids&set(drop['amounts'])
                self.assertLessEqual(actual,{resource})
                if actual:found=True;break
            self.assertTrue(found)
    def test_all_150_real_definitions_execute_multiple_turns(self):
        for name in self.manuals:
            with self.subTest(name=name):
                part=self.start(name,enemy='fire_elixir_ruins_v1_100',attack=2000,hp=10000000)
                for _ in range(12):
                    if part['battle']['status']!='ACTIVE':break
                    part=battle.attack(part,self.registry,'design','effect-test')
                battle.validate(part,self.registry,'design')
    def test_all_60_equipment_ranges_roll_and_validate_without_reroll(self):
        for key in self.config['equipment']:
            with self.subTest(key=key):
                p=items.add(items.initial(),self.registry,'design:1:i:1',key,'fixed-loot',1,False,roll_version=ROLL_VERSION)
                items.validate(p,self.registry,'design')
                self.assertTrue(items.known_stats(p['instances']['design:1:i:1'],items.definition(self.registry,key)))
                self.assertEqual(items.add(items.initial(),self.registry,'design:1:i:1',key,'fixed-loot',1,False,roll_version=ROLL_VERSION),p)
    def test_real_fire_skill_applies_dot_and_cooldown(self):
        part=self.start('赤炎掌',enemy='fire_elixir_ruins_v1_100',attack=50000)
        part=battle.attack(part,self.registry,'design','effect-test');b=part['battle']
        self.assertTrue(any(r['status_id']=='burn' for r in b['mechanics']['statuses']['enemy']))
        self.assertEqual(sum(v for k,v in b['mechanics']['counts'].items() if k.startswith('techniques:')),1)
        part=battle.attack(part,self.registry,'design','effect-test')
        self.assertEqual(sum(v for k,v in part['battle']['mechanics']['counts'].items() if k.startswith('techniques:')),1)
        self.assertTrue(any(e['kind']=='dot' for e in part['battle']['latest_events']))
    def test_damage_facts_keep_actual_element_and_type_for_presentation(self):
        part=self.start('赤炎掌',enemy='fire_elixir_ruins_v1_100',attack=50000)
        part=battle.attack(part,self.registry,'design','effect-test')
        fire=[e for e in part['battle']['latest_events'] if e.get('element')=='fire']
        self.assertTrue(any(e['damage_kind']=='skill' for e in fire))
        self.assertTrue(any(e['damage_kind']=='dot' for e in fire))
        battle.validate(part,self.registry,'design')
        old=thaw_json(part)
        for e in old['battle']['latest_events']:
            e.pop('element',None);e.pop('damage_kind',None)
        battle.validate(old,self.registry,'design')
        bad=thaw_json(part);row=next(e for e in bad['battle']['latest_events'] if 'element' in e)
        row['element']='imaginary'
        with self.assertRaises(ValidationError):battle.validate(bad,self.registry,'design')
        row['element']='fire';row.pop('damage_kind')
        with self.assertRaises(ValidationError):battle.validate(bad,self.registry,'design')
    def test_chill_threshold_freezes_and_has_control_protection(self):
        part=self.start();r=self.engine(part);r.actor='player';r.source='test'
        for _ in range(3):r.status('enemy','chill',0,3,1,'ice')
        self.assertEqual(r.stacks('enemy','chill'),0);self.assertEqual(r.stacks('enemy','freeze'),1)
        ready=r.s['control_ready']['enemy'];r.status('enemy','freeze',0,3,1,'ice')
        self.assertEqual(r.s['control_ready']['enemy'],ready)
    def test_shield_absorbs_damage_and_expires(self):
        part=self.start(enemy='fire_elixir_ruins_v1_001');r=self.engine(part);r.actor='player'
        r.apply({'op':'shield','amount':100000,'duration':2});before=r.b['player_hp_milli']
        r.damage('enemy','player',10000,'neutral','dot')
        self.assertEqual(r.b['player_hp_milli'],before);self.assertEqual(r.s['shields']['player'],90000)
        r.b['step']=3;r.turn();self.assertEqual(r.s['shields']['player'],0)
    def test_death_prevention_shared_by_two_different_manuals(self):
        part=self.start('流光遁','不灭法身诀',enemy='fire_elixir_ruins_v1_001',hp=10000)
        r=self.engine(part);r.damage('enemy','player',20000,'neutral','dot')
        self.assertEqual(r.b['player_hp_milli'],1);self.assertTrue(r.s['death_prevention'])
        r.damage('enemy','player',20000,'neutral','dot');self.assertEqual(r.b['player_hp_milli'],0)
    def test_dot_does_not_trigger_reflection(self):
        part=self.start(enemy='fire_elixir_ruins_v1_001');r=self.engine(part);r.p={**r.p,'reflect_bps':3500}
        before=r.b['enemy_hp_milli'];r.damage('enemy','player',10000,'poison','dot')
        self.assertEqual(r.b['enemy_hp_milli'],before)
    def test_ranged_skill_avoids_melee_reflection_and_melee_skill_does_not(self):
        part=self.start(enemy='fire_elixir_ruins_v1_001');r=self.engine(part);r.p={**r.p,'reflect_bps':3500}
        before=r.b['enemy_hp_milli'];r.damage('enemy','player',10000,'neutral','ranged')
        self.assertEqual(r.b['enemy_hp_milli'],before)
        r.damage('enemy','player',10000,'neutral','skill')
        self.assertLess(r.b['enemy_hp_milli'],before)
    def test_armor_debuff_is_local_and_does_not_mutate_enemy_definition(self):
        part=self.start(enemy='fire_elixir_ruins_v1_001');r=self.engine(part);armor=r.e.armor_milli
        r.actor='player';r.source='test';r.status('enemy','armor_down',0,2,1,'neutral')
        self.assertLess(r.stat('enemy','armor_milli'),armor);self.assertEqual(r.e.armor_milli,armor)
    def test_repeated_and_result_only_rounds_match_and_before_is_independent(self):
        part=self.start('赤炎掌','养气诀',enemy='fire_elixir_ruins_v1_001',attack=50000,hp=200000)
        fast,before,count=battle.result_only(part,self.registry,'design');slow=part
        for _ in range(count):slow=battle.attack(slow,self.registry,'design','effect-test')
        for key in ('player_hp_milli','enemy_hp_milli','status','step','reward','mechanics'):
            self.assertEqual(fast['battle'][key],slow['battle'][key])
        if count>1:self.assertLess(before['battle']['step'],fast['battle']['step'])
        self.assertEqual(part['battle']['step'],0)
    def test_legacy_fight_is_byte_preserved_under_new_registry(self):
        old=load_dungeons(management=True,cold_jade=True,ecology=True)
        part=battle.start(battle.initial(),old,'design','old-fight','thorn_path_v2_001')
        self.assertNotIn('mechanics',part['battle'])
        self.assertEqual(battle.attack(part,old,'design','old-fight'),battle.attack(part,self.registry,'design','old-fight'))
    def test_freeze_skips_exactly_one_enemy_action(self):
        part=self.start(enemy='fire_elixir_ruins_v1_001',attack=1000)
        r=self.engine(part);r.actor='player';r.source='test';r.status('enemy','freeze',0,1,1,'ice')
        part=battle.attack(part,self.registry,'design','effect-test')
        self.assertFalse(any(e['kind']=='enemy_attack' for e in part['battle']['latest_events']))
        part=battle.attack(part,self.registry,'design','effect-test')
        self.assertTrue(any(e['kind']=='enemy_attack' for e in part['battle']['latest_events']))
    def test_seal_suppresses_one_boss_special_and_leaves_basic_attack(self):
        part=self.start(enemy='red_copper_mine_v1_100',attack=1000);part['battle']['step']=3
        r=self.engine(part);r.actor='player';r.source='test';r.status('enemy','seal',0,1,1,'neutral')
        part=battle.attack(part,self.registry,'design','effect-test')
        self.assertTrue(any(e['kind']=='enemy_attack' for e in part['battle']['latest_events']))
        self.assertFalse(any(e['kind']=='skill' and e['actor']=='enemy' for e in part['battle']['latest_events']))
    def test_turn_start_movement_bonus_affects_this_turn_initiative(self):
        part=self.start('逐月步',enemy='fire_elixir_ruins_v1_001',attack=1000)
        r=self.engine(part);r.actor='enemy';r.source='test';r.status('enemy','speed',0,2,1,'neutral')
        after=battle.attack(part,self.registry,'design','effect-test')
        attacks=[e for e in after['battle']['latest_events'] if e['kind'] in ('player_attack','enemy_attack')]
        self.assertEqual(attacks[0]['actor'],'player')
    def test_low_life_stance_protects_incoming_attack_and_clears_its_old_phase(self):
        part=self.start('逍遥无极身',enemy='fire_elixir_ruins_v1_001',attack=1000);part['battle']['player_hp_milli']=400000
        after=battle.attack(part,self.registry,'design','effect-test')
        ids={s['status_id'] for s in after['battle']['mechanics']['statuses']['player']}
        self.assertIn('guard',ids);self.assertIn('evade',ids);self.assertNotIn('speed',ids)
    def test_positive_status_sources_are_independent_and_dot_cap_is_shared(self):
        part=self.start();r=self.engine(part);r.actor='player'
        for source in ('source_a','source_b'):
            r.source=source;r.status('player','guard',0,2,1,'neutral');r.status('enemy','burn',1000,3,4,'fire')
        self.assertEqual(len(r.rows('player','guard')),2)
        self.assertEqual(sum(s['stacks'] for s in r.rows('enemy','burn')),5)
        r.source='source_a';r.apply({'op':'consume','status':'guard'})
        self.assertEqual([s['source_id'] for s in r.rows('player','guard')],['source_b'])
    def test_rate_caps_include_temporary_statuses(self):
        part=self.start();r=self.engine(part);r.p={**r.p,'evasion_bps':2500};r.actor='player';r.source='test';r.status('player','evade',0,2,1,'neutral')
        self.assertEqual(r.stat('player','evasion_bps'),2500)
    def test_delayed_conversion_conserves_converted_amount(self):
        part=self.start();r=self.engine(part);r.incoming=12000
        r.apply({'op':'convert','amount':3000,'status':'delayed'})
        delayed=next(s for s in r.rows('player') if s['status_id']=='delayed')
        self.assertEqual(r.incoming,8400)
        self.assertEqual(delayed['magnitude']*delayed['duration'],3600)
    def test_next_heal_is_consumed_once(self):
        part=self.start('太极混元功',enemy='fire_elixir_ruins_v1_001');r=self.engine(part)
        r.damage('enemy','player',100000,'neutral','dot')
        before=r.b['player_hp_milli'];r.actor='player';r.apply({'op':'heal','amount':10000})
        first=r.b['player_hp_milli']-before;before=r.b['player_hp_milli'];r.apply({'op':'heal','amount':10000})
        second=r.b['player_hp_milli']-before
        self.assertEqual(first,12000);self.assertEqual(second,10000)
    def test_heal_and_shield_share_one_support_charge_per_turn(self):
        part=self.start('玄天炼元诀',enemy='fire_elixir_ruins_v1_001');r=self.engine(part)
        r.damage('enemy','player',50000,'neutral','dot');r.actor='player'
        r.apply({'op':'heal','amount':10000});r.apply({'op':'shield','amount':10000})
        charges=[s for s in r.rows('player') if s['status_id']=='charge_refine_support']
        self.assertEqual(sum(s['stacks'] for s in charges),1)
    def test_shield_only_resistance_ends_when_shield_expires(self):
        part=self.start('上清玄元功',enemy='fire_elixir_ruins_v1_001');r=self.engine(part);r.actor='player'
        r.apply({'op':'shield','amount':10000,'duration':1});self.assertGreater(r.stat('player','status_resist_bps'),0)
        r.turn();self.assertEqual(r.stat('player','status_resist_bps'),0)
    def test_forge_uses_new_subset_and_preserves_old_forge_roll(self):
        from src.data.combat.mechanics import CRAFT_ROLL_VERSION,equipment_ranges
        key='thorn_fang_blade';d=items.definition(self.registry,key)
        crafted=items.add(items.initial(),self.registry,'design:1:i:1',key,'fixed-forge',1,False,roll_version=CRAFT_ROLL_VERSION)
        items.validate(crafted,self.registry,'design')
        for stat,lo,hi,step in equipment_ranges(key,craft=True):self.assertTrue(lo<=crafted['instances']['design:1:i:1']['stats'][stat]<=hi)
        old=items.add(items.initial(),self.registry,'design:1:i:2',key,'old-forge',1,False,roll_version='thorn-forge-v1')
        items.validate(old,self.registry,'design');self.assertEqual(old['instances']['design:1:i:2']['stats'],items.rolled_stats(d,'old-forge','thorn-forge-v1'))
    def test_unknown_config_reference_and_bad_arity_fail_before_combat(self):
        from src.data.combat.mechanics import validate_rule
        for expression in ('own.made_up',['mul',1],['gt','own.stack:missing',0]):
            with self.subTest(expression=expression),self.assertRaises(ValidationError):
                validate_rule({'id':'invalid','trigger':'turn_start','condition':expression,'effects':[{'op':'heal','amount':1}]},self.config['statuses'])
    def test_bad_status_and_unknown_counter_rejected(self):
        part=self.start();part['battle']['mechanics']['counts']['arbitrary']=1
        with self.assertRaises(ValidationError):battle.validate(part,self.registry,'design')
        part=self.start();part['battle']['mechanics']['statuses']['player']=[{'status_id':'unknown'}]
        with self.assertRaises(ValidationError):battle.validate(part,self.registry,'design')

from tests.systems import test_ecology as _fixtures
from src.core.save.sqlite import SQLiteSave
from src.application.ecology import EcologyApplication
from src.application.memory import Command
from src.application.combat_effect_upgrade import upgrade

class UpgradeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.registry=load_dungeons(management=True,cold_jade=True,ecology=True)
    def setUp(self):_fixtures.EcologyTests.setUp(self)
    def test_known_equipped_snapshot_avoids_search_but_unknown_stats_do_not(self):
        from unittest.mock import patch
        from src.application import equipment as equip
        from src.systems.cultivation import growth
        from src.application.cultivation import partition
        with SQLiteSave(self.path,allowed_root=self.root) as store:
            state=EcologyApplication(store,self.registry,self.clock).query(self.sid)
        for key in ('thorn_fang_blade','thorn_vine_gloves','thorn_travel_belt','thorn_scale_shirt','thorn_moss_boots','thorn_feather_hood'):
            state,identity=equip.acquire(state,self.registry,key,'snapshot-witness')
            state=replace(state,domains={**state.domains,'equipment':items.equip(state.domains['equipment'],self.registry,identity,False)})
        g=partition(state);actor=items.projection(state.domains['equipment'],growth.projection(g,self.registry,self.sid))
        combat=battle.start(battle.initial(),self.registry,self.sid,'snapshot-witness','thorn_path_v2_001',player_snapshot=actor,growth_snapshot=g)
        state=replace(state,domains={**state.domains,'combat':combat})
        with patch.object(equip,'matches_random_projection',side_effect=AssertionError('unnecessary search')):
            equip.validate(state,load_current())
        domains=thaw_json(state.domains);row=domains['equipment']['instances'][identity]
        row['stats']['max_hp_milli']=999999999
        domains['combat']['battle']['player_snapshot']=thaw_json(items.projection(domains['equipment'],growth.projection(g,self.registry,self.sid)))
        with patch.object(equip,'matches_random_projection',return_value=False) as search:
            with self.assertRaises(ValidationError):equip.validate(replace(state,domains=domains),load_current())
            self.assertTrue(search.called)
    def test_explicit_upgrade_preserves_domains_time_and_receipt_replay(self):
        with SQLiteSave(self.path,allowed_root=self.root) as store:
            before=EcologyApplication(store,self.registry,self.clock).query(self.sid)
            request=Command(self.sid,before.generation,before.revision,str(uuid4()),'combat_effect_content_upgrade',{})
            first=upgrade(store,self.clock,request);after=EcologyApplication(store,load_dungeons(management=True,cold_jade=True,ecology=True,mechanics=True,skill_timing=True),self.clock).query(self.sid)
            self.assertEqual(after.domains,before.domains);self.assertEqual(after.time,before.time)
            self.assertEqual(after.identity,before.identity);self.assertEqual(upgrade(store,self.clock,request),first)
        with SQLiteSave(self.path,allowed_root=self.root) as store:
            reopened=EcologyApplication(store,load_dungeons(management=True,cold_jade=True,ecology=True,mechanics=True,skill_timing=True),self.clock)
            self.assertEqual(reopened.query(self.sid),after)
            self.assertEqual(len(reopened.view(self.sid)['techniques']['catalog']),150)



    def test_upgrade_keeps_active_old_battle_and_its_stats(self):
        with SQLiteSave(self.path,allowed_root=self.root) as store:
            app=EcologyApplication(store,self.registry,self.clock);state=app.query(self.sid)
            start=Command(self.sid,state.generation,state.revision,str(uuid4()),'combat_start',{'encounter_id':'thorn_path_v2_001'})
            app.execute(start);before=app.query(self.sid)
            self.assertNotIn('mechanics',before.domains['combat']['battle'])
            request=Command(self.sid,before.generation,before.revision,str(uuid4()),'combat_effect_content_upgrade',{})
            upgrade(store,self.clock,request);new=EcologyApplication(store,load_dungeons(management=True,cold_jade=True,ecology=True,mechanics=True,skill_timing=True),self.clock);after=new.query(self.sid)
            self.assertEqual(after.domains,before.domains)
            bid=after.domains['combat']['battle']['battle_id']
            expected=battle.attack(before.domains['combat'],self.registry,self.sid,bid)
            attack=Command(self.sid,after.generation,after.revision,str(uuid4()),'combat_attack',{'battle_id':bid})
            new.execute(attack)
            self.assertEqual(new.query(self.sid).domains['combat'],expected)

    def test_operator_cli_dry_run_and_full_database_backup_in_isolation(self):
        import tempfile
        from tools.playable.combat_effect_upgrade import run
        from src.core.save.sqlite import V2_ROOT
        with tempfile.TemporaryDirectory(dir=V2_ROOT/'.tmp') as folder:
            root=Path(folder);path=root/'danding.sqlite3'
            with SQLiteSave(self.path,allowed_root=self.root) as store:before=EcologyApplication(store,self.registry,self.clock).query(self.sid)
            (root/'save-id').write_text(self.sid)
            with SQLiteSave.initialize(path,allowed_root=root) as store:EcologyApplication(store,self.registry,self.clock).create(before)
            self.assertEqual(run(root)['status'],'DRY_RUN')
            result=run(root,True)
            json_backup=Path(result['backup']);database_backup=Path(result['database_backup'])
            self.addCleanup(json_backup.unlink,missing_ok=True);self.addCleanup(database_backup.unlink,missing_ok=True)
            self.assertEqual(json_backup.stat().st_mode&0o777,0o600);self.assertEqual(database_backup.stat().st_mode&0o777,0o600)
            self.assertEqual(json.loads(json_backup.read_text()),before.to_dict())
            with SQLiteSave(database_backup,allowed_root=V2_ROOT/'.tmp') as backup_store:
                self.assertEqual(EcologyApplication(backup_store,self.registry,self.clock).query(self.sid),before)


class ApplicationEffectsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.registry=load_current()
    def setUp(self):_fixtures.EcologyTests.setUp(self)
    read=_fixtures.EcologyTests.read
    view=_fixtures.EcologyTests.view
    fixture=_fixtures.EcologyTests.fixture
    request=_fixtures.EcologyTests.request
    execute=_fixtures.EcologyTests.execute
    command=_fixtures.EcologyTests.command
    settle=_fixtures.EcologyTests.settle
    def test_new_battle_freezes_starters_and_cannot_change_in_battle(self):
        self.command('combat_start',{'encounter_id':'thorn_path_v2_001'})
        state=self.read();b=state.domains['combat']['battle']
        self.assertEqual(b['rules_version'],'timed-skills-v1')
        self.assertEqual(len(b['mechanics']['sources']),2)
        key=next(iter(state.domains['cultivation']['techniques']['owned']))
        with self.assertRaises(ValidationError):self.command('technique_equip',{'technique_id':key,'slot':'movement'})
        self.assertEqual(self.read(),state)
        self.command('combat_attack',{'battle_id':b['battle_id']})
        self.assertEqual(self.read().domains['combat']['battle']['mechanics']['sources'],b['mechanics']['sources'])
        self.assertIn('effects',self.view()['combat'])
        projected=self.view()['combat']['latest_events']
        actual=self.read().domains['combat']['battle']['latest_events']
        for shown,fact in zip(projected,actual):
            if 'element' in fact:
                self.assertEqual((shown['element'],shown['damage_kind']),(fact['element'],fact['damage_kind']))
    def test_fifth_boss_rewards_and_replay_are_atomic(self):
        from src.systems.cultivation import leveling
        def prepare(s):
            p=thaw_json(s.domains['dungeon']);p['cleared_floor']=100;p['progress']={'red_copper_mine':100,'mist_marsh':100,'cold_jade_cave':100,'fire_elixir_ruins':99};p['selected_id']='fire_elixir_ruins'
            growth=thaw_json(s.domains['cultivation']);growth['total_xp']=leveling.table(leveling.config(self.registry))[1000];growth['current_realm']='realm_1';growth['growth_revision']=1
            return replace(s,domains={**s.domains,'dungeon':p,'cultivation':growth})
        self.fixture(prepare)
        self.command('combat_start',{'encounter_id':'fire_elixir_ruins_v1_100'})
        bid=self.read().domains['combat']['battle']['battle_id']
        # Isolated near-victory snapshot exercises reward authority, not balance.
        def near_victory(s):
            combat=thaw_json(s.domains['combat']);combat['battle']['enemy_hp_milli']=1000
            return replace(s,domains={**s.domains,'combat':combat})
        self.fixture(near_victory)
        for _ in range(300):
            if self.read().domains['combat']['battle']['status']!='ACTIVE':break
            self.command('combat_attack',{'battle_id':bid})
        self.assertEqual(self.read().domains['combat']['battle']['status'],'PLAYER_WIN')
        request=self.request('combat_reward',{'battle_id':bid});receipt=self.execute(request);after=self.read()
        self.assertEqual(self.execute(request),receipt);self.assertEqual(self.read(),after)
        self.assertEqual(after.domains['dungeon']['progress']['fire_elixir_ruins'],100)
        gear=next(r for r in after.domains['equipment']['instances'].values() if r['provenance']==bid)
        self.assertEqual(gear['roll_version'],ROLL_VERSION)
    def test_automatic_battle_and_pause_resume_are_real_commands(self):
        self.command('dungeon_auto',{'enabled':True,'mode':'push','floor':1})
        self.settle(4000,max_events=64)
        b=self.read().domains['combat']['battle'];self.assertIsNotNone(b)
        self.assertEqual(b['rules_version'],'timed-skills-v1')
        self.assertGreater(b['step'],0)

    def test_automatic_online_offline_authority_matches(self):
        import tempfile
        from tests.fixtures.time import ManualClock
        from src.application.settlement import SettlementRequest
        from src.core.time.model import Continuation
        self.command('dungeon_auto',{'enabled':True,'mode':'push','floor':1})
        seed=self.read();out=[]
        for compressed in (False,True):
            with tempfile.TemporaryDirectory(dir=self.root) as folder:
                root=Path(folder);path=root/'compare.sqlite3';clock=ManualClock(self.clock.now_ms())
                with SQLiteSave.initialize(path,allowed_root=root) as store:EcologyApplication(store,self.registry,clock).create(seed)
                clock.advance(120000)
                with SQLiteSave(path,allowed_root=root) as store:
                    app=EcologyApplication(store,self.registry,clock);app.engine.result_path=compressed
                    for _ in range(100):
                        state=app.query(self.sid)
                        request=SettlementRequest(self.sid,state.generation,state.revision,str(uuid4()),128,Continuation.for_state(state) if state.time['pending'] else None)
                        app.settle(request);state=app.query(self.sid)
                        if not state.time['pending']:break
                    else:self.fail('bounded effects settlement did not converge')
                    value=state.to_dict();value.pop('revision')
                    def canonical(v):
                        if isinstance(v,dict):return {k:canonical(x) for k,x in v.items() if k not in ('latest_events','completed_revision','visual_events_online')}
                        if isinstance(v,list):return [canonical(x) for x in v]
                        return v
                    out.append(canonical(value))
        self.assertEqual(out[0],out[1])

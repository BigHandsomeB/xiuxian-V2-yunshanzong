"""Real cooldown boundaries, preserved v1 battles and active-window behavior."""
import json
import unittest
from uuid import uuid4

from src.application.combat_effect_views import technique, battle as battle_view
from src.core.state.envelope import thaw_json, freeze_json
from src.core.validation import ValidationError
from src.data.combat.mechanics import settings, VERSION as LEGACY_VERSION
from src.data.combat.skill_timing import VERSION, CONTENT_VERSION, COOLDOWNS_MS
from src.data.content_loader import load_current
from src.data.content_compatibility import profile, transition
from src.data.dungeons.definitions import load_dungeons
from src.systems.combat import battle, mechanics
from src.systems.combat.equipment_effects import interval
from tests.systems import test_combat_mechanics as fixtures


class TimingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry=load_current();cls.config=settings(cls.registry)
        cls.legacy=load_dungeons(management=True,cold_jade=True,ecology=True,mechanics=True)
        cls.manuals={r['name']:key for key,r in cls.config['techniques'].items()}

    start=fixtures.EffectsTests.start
    engine=fixtures.EffectsTests.engine

    def test_100_active_and_50_unchanged_inner_manuals(self):
        old=settings(self.legacy);actives=0;inner=0
        for key,row in self.config['techniques'].items():
            detail=technique(self.registry,key)
            if row['category']=='passive':
                self.assertEqual(row,old['techniques'][key]);self.assertNotIn('active_skill',detail);inner+=1
            else:
                actives+=1;skill=detail['active_skill']
                self.assertEqual(skill['cooldown_ms'],COOLDOWNS_MS[row['category']])
                self.assertEqual(skill['cast_time_ms'],0);self.assertTrue(skill['automatic'])
                if row['category'] in ('movement','defense'):
                    self.assertEqual(skill['duration_turns'],6)
                    self.assertIn('持续6回合',skill['base_effect'])
                self.assertTrue(any('秒' in text for text in detail['effect_rules']))
        self.assertEqual((actives,inner),(100,50))
        self.assertEqual(settings(self.registry,LEGACY_VERSION),old)
        for section in ('equipment','enemies','balance'):
            self.assertEqual(self.config[section],old[section])

    def test_all_150_execute_with_bounded_work_and_validate(self):
        for name in self.manuals:
            with self.subTest(name=name):
                part=self.start(name,enemy='fire_elixir_ruins_v1_100',hp=10000000,attack=2000)
                for _ in range(18):
                    if part['battle']['status']!='ACTIVE':break
                    part=battle.attack(part,self.registry,'design','effect-test')
                battle.validate(part,self.registry,'design')
                self.assertLessEqual(len(part['battle']['latest_events']),self.config['balance']['event_limit'])

    def test_fixed_seconds_never_expire_early_even_at_max_speed(self):
        names={'movement':'流云步','defense':'铜皮功','special':'裂石掌','ultimate':'九天斩仙诀'}
        for category,name in names.items():
            for speed in (0,3000):
                with self.subTest(category=category,speed=speed):
                    part=self.start(name,enemy='fire_elixir_ruins_v1_100',hp=100000000,attack=1000)
                    part['battle']['player_snapshot']['speed_bps']=speed
                    casts=[];last=0
                    for _ in range(35):
                        part=thaw_json(part);part['battle']['mechanics']['resources']['player']=self.config['balance']['resource_cap']
                        part=battle.attack(part,self.registry,'design','effect-test')
                        state=part['battle']['mechanics'];key=next((k for k in state['ready_ms'] if self.manuals[name] in k),None)
                        count=state['counts'].get(key,0)
                        if count>last:casts.append(state['elapsed_ms']);last=count
                    self.assertGreaterEqual(len(casts),2)
                    delay=casts[1]-casts[0]
                    self.assertGreaterEqual(delay,COOLDOWNS_MS[category])
                    self.assertLess(delay,COOLDOWNS_MS[category]+interval({'speed_bps':speed}))

    def test_reactive_followup_requires_active_window(self):
        part=self.start('流云步',enemy='fire_elixir_ruins_v1_100',attack=1000)
        r=self.engine(part)
        r.trigger('player','on_evade');self.assertEqual(r.stacks('player','evade'),0)
        r.trigger('player','turn_start',phase='prepare')
        self.assertTrue(r.stacks('player','active_movement'))
        self.assertTrue(any(e['kind']=='skill' for e in r.events))
        r.s['turn_counts']={};r.trigger('player','on_evade')
        self.assertEqual(r.stacks('player','evade'),1)
        r.s['statuses']['player']=[];r.s['turn_counts']={}
        r.trigger('player','on_evade');self.assertEqual(r.stacks('player','evade'),0)

    def test_support_cast_before_initiative_and_stance(self):
        part=self.start('逐月步',enemy='fire_elixir_ruins_v1_100',attack=1000)
        r=self.engine(part);r.actor='enemy';r.source='test';r.status('enemy','speed',0,2,1,'neutral')
        after=battle.attack(part,self.registry,'design','effect-test')
        attacks=[e for e in after['battle']['latest_events'] if e['kind'] in ('player_attack','enemy_attack')]
        self.assertEqual(attacks[0]['actor'],'player')

    def test_six_turn_window_preserves_periodic_shield_and_still_expires(self):
        part=self.start('护元功',enemy='fire_elixir_ruins_v1_100',hp=100000000,attack=1000)
        part['battle']['player_snapshot']['speed_bps']=3000
        key='techniques:'+self.manuals['护元功']+':effect_1'
        for turn in range(1,8):
            part=battle.attack(part,self.registry,'design','effect-test')
            state=part['battle']['mechanics']
            self.assertEqual(state['counts'].get(key,0),min(2,turn//3))
            active=[r for r in state['statuses']['player'] if r['status_id']=='active_defense']
            self.assertEqual(bool(active),turn<6)
        skills=battle_view(self.registry,part['battle'])['effects']['skills']
        self.assertGreater(skills[0]['cooldown_remaining_ms'],0)
        self.assertEqual(skills[0]['used'],1)

    def test_frozen_or_sealed_cast_does_not_spend_cooldown(self):
        for status in ('freeze','seal'):
            part=self.start('流云步',enemy='fire_elixir_ruins_v1_100')
            r=self.engine(part);r.actor='enemy';r.source='test';r.status('player',status,0,1,1,'neutral')
            r.trigger('player','turn_start',phase='prepare')
            self.assertEqual(r.s['ready_ms'],{});self.assertEqual(r.s['counts'],{})

    def test_inner_skill_boost_still_applies_before_attack_damage(self):
        amounts=[]
        for names in [('裂石掌',),('裂石掌','先天一气诀')]:
            r=self.engine(self.start(*names,enemy='fire_elixir_ruins_v1_100',attack=50000))
            r.s['resources']['player']=100
            r.trigger('player','battle_start')
            r.trigger('player','turn_start',phase='active')
            amounts.append(sum(e['damage_milli'] for e in r.events if e.get('damage_kind')=='skill' and e['target']=='enemy'))
            self.assertEqual(r.stacks('player','skill_power'),0)
        self.assertGreater(amounts[1],amounts[0])

    def test_saved_cooldown_roundtrip_and_offline_authority_match(self):
        part=self.start('流云步','铜皮功','赤炎掌','九天斩仙诀','养气诀',enemy='fire_elixir_ruins_v1_100',hp=1000000,attack=50000)
        part=battle.attack(part,self.registry,'design','effect-test')
        restored=freeze_json(json.loads(json.dumps(thaw_json(part))))
        self.assertEqual(part,restored)
        self.assertEqual(battle_view(self.registry,part['battle']),battle_view(self.registry,restored['battle']))
        fast,_,count=battle.result_only(part,self.registry,'design');slow=restored
        for _ in range(count):slow=battle.attack(slow,self.registry,'design','effect-test')
        for key in ('step','status','mechanics','reward','player_hp_milli','enemy_hp_milli'):
            self.assertEqual(fast['battle'][key],slow['battle'][key])
        self.assertGreater(count,1)

    def test_v1_battle_remains_exact_under_new_registry(self):
        part=self.start('流云步','铜皮功','赤炎掌','九天斩仙诀',enemy='fire_elixir_ruins_v1_100',attack=1000)
        part['battle']['rules_version']=LEGACY_VERSION
        part['battle']['mechanics']=mechanics.initial(settings(self.legacy),part['battle']['mechanics']['sources'],part['battle']['mechanics']['enemy_source'])
        left=right=freeze_json(part)
        for _ in range(16):
            if left['battle']['status']!='ACTIVE':break
            left=battle.attack(left,self.legacy,'design','effect-test')
            right=battle.attack(right,self.registry,'design','effect-test')
            self.assertEqual(left,right)
        self.assertNotIn('ready_ms',right['battle']['mechanics'])
        self.assertTrue(all('cooldown_remaining_ms' not in s for s in battle_view(self.registry,right['battle'])['effects']['skills']))

    def test_unknown_and_out_of_bound_saved_timers_rejected(self):
        part=self.start('流云步')
        for key,value in [('elapsed_ms',True),('elapsed_ms',1000),('ready_ms',{'unknown':10})]:
            bad=thaw_json(part);bad['battle']['mechanics'][key]=value
            with self.assertRaises(ValidationError):battle.validate(bad,self.registry,'design')

    def test_battle_lists_four_independent_cooldowns(self):
        part=self.start('流云步','铜皮功','赤炎掌','九天斩仙诀',enemy='fire_elixir_ruins_v1_100')
        view=battle_view(self.registry,part['battle'])['effects']['skills']
        self.assertEqual({s['category']:s['cooldown_ms'] for s in view},COOLDOWNS_MS)
        self.assertTrue(all(s['cooldown_remaining_ms']==0 for s in view))
        part=battle.attack(part,self.registry,'design','effect-test')
        view=battle_view(self.registry,part['battle'])['effects']['skills']
        self.assertEqual({s['category']:s['cooldown_remaining_ms'] for s in view if s['category'] in ('movement','defense')},{'movement':10000,'defense':12000})

    def test_legacy_startup_profile_is_explicit_and_retained(self):
        old=self.legacy.content_version
        self.assertEqual(profile(old).loader,'dungeons')
        self.assertEqual(load_dungeons(**dict(profile(old).flags)).content_version,old)
        self.assertEqual(profile(CONTENT_VERSION).loader,'dungeons')
        self.assertEqual(load_dungeons(**dict(profile(CONTENT_VERSION).flags)).content_version,CONTENT_VERSION)
        self.assertEqual(transition(old,CONTENT_VERSION),'REQUIRES_EXPLICIT_MIGRATION')
        self.assertEqual(transition(CONTENT_VERSION,old),'BLOCKED')


class TimingUpgradeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.registry=load_dungeons(management=True,cold_jade=True,ecology=True,mechanics=True)
    setUp=fixtures.ApplicationEffectsTests.setUp
    read=fixtures.ApplicationEffectsTests.read
    fixture=fixtures.ApplicationEffectsTests.fixture
    request=fixtures.ApplicationEffectsTests.request
    execute=fixtures.ApplicationEffectsTests.execute
    command=fixtures.ApplicationEffectsTests.command

    def test_explicit_upgrade_preserves_all_domains_time_and_old_fight(self):
        from src.application.ecology import EcologyApplication
        from src.application.combat_effect_upgrade import upgrade
        from src.application.memory import Command
        from src.core.save.sqlite import SQLiteSave
        self.command('combat_start',{'encounter_id':'thorn_path_v2_001'})
        before=self.read()
        with SQLiteSave(self.path,allowed_root=self.root) as store:
            request=Command(self.sid,before.generation,before.revision,str(uuid4()),'combat_effect_content_upgrade',{})
            receipt=upgrade(store,self.clock,request)
            new=EcologyApplication(store,load_dungeons(management=True,cold_jade=True,ecology=True,mechanics=True,skill_timing=True),self.clock);after=new.query(self.sid)
            self.assertEqual(after.domains,before.domains);self.assertEqual(after.time,before.time)
            self.assertEqual(after.identity,before.identity);self.assertEqual(after.content_version,CONTENT_VERSION)
            self.assertEqual(upgrade(store,self.clock,request),receipt)
            self.assertEqual(new.query(self.sid),after)
            b=after.domains['combat']['battle']
            self.assertEqual(b['rules_version'],LEGACY_VERSION)
            self.assertEqual(battle.attack(after.domains['combat'],load_current(),self.sid,b['battle_id']),
                             battle.attack(before.domains['combat'],self.registry,self.sid,b['battle_id']))

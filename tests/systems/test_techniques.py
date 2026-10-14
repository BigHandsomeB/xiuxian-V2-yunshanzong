"""Focused technique checks on disposable shipping saves; no full regression."""
import unittest
from dataclasses import replace
from uuid import uuid4
from src.application.ecology import EcologyApplication
from src.application.cultivation import partition
from src.application.memory import Command
from src.application.settlement import SettlementRequest
from src.core.save.sqlite import SQLiteSave
from src.core.state.envelope import thaw_json
from src.core.validation import ValidationError
from src.systems.cultivation import techniques,leveling
from src.systems.combat import battle
from src.systems.dungeons import progress
from src.systems.economy import policy
from tests.systems import test_ecology as fixtures
from tests.systems import test_settlement_batch as batch_fixtures

class TechniqueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):fixtures.EcologyTests.setUpClass.__func__(cls)
    def setUp(self):fixtures.EcologyTests.setUp(self)
    read=fixtures.EcologyTests.read
    view=fixtures.EcologyTests.view
    fixture=fixtures.EcologyTests.fixture
    request=fixtures.EcologyTests.request
    execute=fixtures.EcologyTests.execute
    command=fixtures.EcologyTests.command
    def grant(self):
        self.fixture(lambda s:replace(s,domains={**s.domains,'cultivation':techniques.grant_test(partition(s),self.registry)}))
    def test_read_defaults_and_stats_reversible_with_caps(self):
        before=self.read();self.assertFalse(self.view()['techniques']['instances']);self.assertEqual(self.read(),before)
        app=EcologyApplication(None,self.registry,self.clock);base=app.player_projection(before);self.grant();s=self.read();actor=app.player_projection(s)
        self.assertEqual(techniques.grant_test(partition(s),self.registry),partition(s))
        bonus=techniques.bonuses(partition(s),self.registry)
        for key in ('max_hp_milli','attack_milli','armor_milli'):self.assertEqual(actor[key],base[key]+bonus[key])
        self.assertLessEqual(actor.get('speed_bps',0),3000);self.assertLessEqual(actor.get('evasion_bps',0),2500)
        for slot in techniques.config(self.registry)['slots']:self.command('technique_unequip',{'slot':slot})
        self.assertEqual(app.player_projection(self.read()),base)
    def test_equip_validation_atomic_and_replay(self):
        self.grant();q=self.request('technique_unequip',{'slot':'movement'});receipt=self.execute(q);after=self.read()
        self.assertEqual(self.execute(q),receipt);self.assertEqual(self.read(),after)
        for payload in [{'slot':'defense','technique_id':'test_wind_step'},{'slot':'movement','technique_id':'missing'}]:
            with self.assertRaises(ValidationError):self.command('technique_equip',payload)
            self.assertEqual(self.read(),after)
        self.command('technique_equip',{'slot':'passive_4','technique_id':'test_vitality'})
        self.assertEqual(len(set(partition(self.read())['techniques']['slots'].values())),6)
    def test_pause_freezes_changes_and_xp(self):
        self.grant();self.command('world_pause',{});before=self.read()
        with self.assertRaises(ValidationError):self.command('technique_unequip',{'slot':'movement'})
        self.assertEqual(self.read(),before)
        with SQLiteSave(self.path,allowed_root=self.root) as store:
            app=EcologyApplication(store,self.registry,self.clock);q=SettlementRequest(self.sid,before.generation,before.revision,str(uuid4()),128)
            self.clock.advance(3600000)
            with self.assertRaises(ValidationError):app.settle(q)
            self.assertEqual(partition(app.query(self.sid)),partition(before))
    def test_auto_blocks_equipping(self):
        self.grant()
        def enable(s):
            d=thaw_json(s.domains['dungeon']);d['cleared_floor']=1
            d=progress.set_auto(d,self.registry,True,'farm',1,1)
            return EcologyApplication(None,self.registry,self.clock).engine.wake(replace(s,domains={**s.domains,'dungeon':d}))
        self.fixture(enable);before=self.read()
        with self.assertRaises(ValidationError):self.command('technique_unequip',{'slot':'movement'})
        self.assertEqual(self.read(),before)
        self.assertFalse(self.view()['techniques']['can_change'])
    def test_kill_gate_integer_levels_and_grade_caps(self):
        p=partition(self.read());q,result=leveling.kill(p,self.registry,self.sid,1,'normal','battle-1')
        self.assertEqual(result['xp_gained'],0);self.assertNotIn('techniques',q)
        p=techniques.grant_test(p,self.registry);q,result=leveling.kill(p,self.registry,self.sid,1,'normal','battle-2')
        self.assertGreater(result['xp_gained'],0);self.assertTrue(all(n==100 for n in q['techniques']['owned'].values()))
        for i in range(64):q,_=leveling.kill(q,self.registry,self.sid,100,'boss',str(i))
        c=techniques.config(self.registry)
        for row in techniques.view(q,self.registry)['instances']:
            self.assertEqual(row['level'],c['grades'][row['grade']]);self.assertEqual(row['xp'],techniques.threshold(c,row['max_level']))
        leveling.validate(q,self.registry,self.sid)
    def test_64_fights_result_and_event_paths_same_growth(self):
        a=techniques.grant_test(partition(self.read()),self.registry);b=a
        for i in range(64):
            identity=f'sample:{i}';seed=battle.start(battle.initial(),self.registry,self.sid,identity,'thorn_path_v2_001',player_snapshot=leveling.projection(a,self.registry,self.sid),growth_snapshot=a)
            event=seed
            while event['battle']['status']=='ACTIVE':event=battle.attack(event,self.registry,self.sid,identity)
            compact,_,_=battle.result_only(seed,self.registry,self.sid)
            self.assertEqual(event['battle']['status'],compact['battle']['status'])
            if event['battle']['status']=='PLAYER_WIN':a,_=leveling.kill(a,self.registry,self.sid,1,'normal',identity)
            if compact['battle']['status']=='PLAYER_WIN':b,_=leveling.kill(b,self.registry,self.sid,1,'normal',identity)
        self.assertEqual(a,b)
    def test_one_hour_battle_and_auto_production_parity(self):
        self.grant();app=EcologyApplication(None,self.registry,self.clock);s=self.read()
        dungeon=thaw_json(s.domains['dungeon']);dungeon['cleared_floor']=1
        dungeon=progress.set_auto(dungeon,self.registry,True,'farm',1,1)
        s=replace(s,domains={**s.domains,'dungeon':dungeon})
        building=next(k for k,v in s.domains['sect']['buildings'].items() if v['definition_id']=='forest')
        from src.systems.disciples import work
        s=replace(s,domains={**s.domains,'disciples':work.assign_shared(s.domains['disciples'],self.registry,building,1)})
        s=app.start_candidate(s,building,'wood')
        auto=policy.set_production(s.domains['automation'],self.registry,building,{'enabled':True,'recipe_id':'wood','target':10000,'reserves':{},'max_consumption':10000})
        s=app.engine.wake(replace(s,domains={**s.domains,'automation':auto}))
        helper=batch_fixtures.SettlementBatchTests();helper.app=app
        app.engine.result_path=False;one,_,_=helper.drain(s,self.clock.now_ms()+3600000)
        app.engine.result_path=True;compact,_,_=helper.drain(s,self.clock.now_ms()+3600000)
        # Compressed combat intentionally omits individual attack presentation events.
        def without_visuals(state):
            domains=thaw_json(state.domains)
            if domains.get('combat',{}).get('battle'):domains['combat']['battle']['latest_events']=[]
            return replace(state,domains=domains)
        helper.assert_same(without_visuals(one),without_visuals(compact));self.assertEqual(partition(one),partition(compact))
        self.assertGreater(sum(partition(one)['techniques']['owned'].values()),0)
    def test_attack_speed_upgrade_at_fight_boundary_keeps_same_time(self):
        app=EcologyApplication(None,self.registry,self.clock);s=self.read()
        p=techniques.grant_test(partition(s),self.registry)
        p['techniques']['slots']={'movement':'test_wind_step'}
        dungeon=thaw_json(s.domains['dungeon']);dungeon['cleared_floor']=1
        dungeon=progress.set_auto(dungeon,self.registry,True,'farm',1,1)
        s=app.engine.wake(replace(s,domains={**s.domains,'cultivation':p,'dungeon':dungeon}))
        # First tick was scheduled before speed increased, as after a victory.
        p=thaw_json(partition(s));p['techniques']['owned']['test_wind_step']=100
        s=replace(s,domains={**s.domains,'cultivation':p})
        helper=batch_fixtures.SettlementBatchTests();helper.app=app
        app.engine.result_path=False;one,_,_=helper.drain(s,self.clock.now_ms()+180000)
        app.engine.result_path=True;compact,_,_=helper.drain(s,self.clock.now_ms()+180000)
        self.assertEqual(partition(one),partition(compact))
        self.assertEqual(one.domains['dungeon'],compact.domains['dungeon'])
        self.assertEqual(one.time,compact.time)
    def test_reward_settlement_replay_and_snapshot_validation(self):
        self.grant();app=EcologyApplication(None,self.registry,self.clock);s=self.read();counter=s.identity['instance_counter']+1
        fight=battle.start(battle.initial(),self.registry,self.sid,f'{self.sid}:1:i:{counter}','thorn_path_v2_001',player_snapshot=app.player_projection(s),growth_snapshot=partition(s))
        fight,_,_=battle.result_only(fight,self.registry,self.sid)
        self.assertEqual(fight['battle']['status'],'PLAYER_WIN')
        s=replace(s,identity={**s.identity,'instance_counter':counter},domains={**s.domains,'combat':fight})
        self.fixture(lambda _:s);before=self.read()
        with self.assertRaises(ValidationError):self.command('technique_unequip',{'slot':'movement'})
        self.assertEqual(self.read(),before)
        q=self.request('combat_reward',{'battle_id':fight['battle']['battle_id']});receipt=self.execute(q);after=self.read()
        self.assertGreater(sum(partition(after)['techniques']['owned'].values()),0)
        self.assertEqual(self.execute(q),receipt);self.assertEqual(self.read(),after)

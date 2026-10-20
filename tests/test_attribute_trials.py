"""Isolated targeted trial commands, rewards, snapshots and online/offline parity."""
import unittest
from dataclasses import replace
from uuid import uuid4
from src.core.state.envelope import thaw_json
from src.core.validation import ValidationError,ConflictError
from src.data.content_loader import load_current
from src.systems.cultivation import attribute_trials as rules,growth
from src.application.cultivation import partition
from src.application import attribute_trials as trial_app
from src.application.memory import Command
import tests.test_market_restock as restock

class AttributeTrialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.registry=load_current()
    setUp=restock.RestockTests.setUp
    app=restock.RestockTests.app
    read=restock.RestockTests.read
    view=restock.RestockTests.view
    request=restock.RestockTests.request
    command=restock.RestockTests.command
    settle=restock.RestockTests.settle
    fixture=restock.RestockTests.fixture

    def start(self,stat='attack_milli',wave=1):return self.command('attribute_trial_start',{'stat':stat,'wave':wave})
    def ledger(self):return partition(self.read())
    def test_old_missing_fields_read_only_and_default_bonus_zero(self):
        before=self.read();self.assertNotIn('trial_attributes',partition(before));view=self.view()['cultivation']['attribute_trials'];self.assertEqual(len(view['rows']),3)
        self.assertTrue(all(r['level']==0 and r['bonus']==0 for r in view['rows']));self.assertEqual(self.read(),before)
    def test_start_receipt_replay_stop_and_no_inventory(self):
        before=self.read();q=self.request('attribute_trial_start',{'stat':'attack_milli','wave':1});first=self.command('',{},q);self.assertEqual(self.command('',{},q),first)
        self.assertTrue(rules.running(self.ledger()));self.assertEqual(self.read().domains['inventory'],before.domains['inventory'])
        self.command('attribute_trial_stop',{});self.assertFalse(rules.running(self.ledger()));self.assertIsNone(rules.part(self.ledger())['wake'])
    def test_wave_strength_xp_and_attribute_thresholds(self):
        c=rules.config(self.registry);a=rules.TrialRegistry(self.registry,1);b=rules.TrialRegistry(self.registry,30)
        self.assertGreater(b.enemy.base_hp_milli,a.enemy.base_hp_milli);self.assertGreater(b.enemy.attack_milli,a.enemy.attack_milli);self.assertGreater(b.enemy.armor_milli,a.enemy.armor_milli)
        p=thaw_json(self.ledger());baseline=growth.projection(p,self.registry,self.sid);p['trial_attributes']={'attack_milli':rules.threshold(c,2)}
        changed=growth.projection(p,self.registry,self.sid);self.assertEqual(changed['attack_milli']-baseline['attack_milli'],2*c['gains']['attack_milli']);self.assertEqual(changed['max_hp_milli'],baseline['max_hp_milli'])
    def test_reject_locked_wave_and_other_combat(self):
        with self.assertRaises(ValidationError):self.start(wave=2)
        self.start()
        with self.assertRaises((ValidationError,ConflictError)):self.command('dungeon_auto',{'enabled':True,'mode':'push','floor':1})
        with self.app() as app:
            with self.assertRaises(ConflictError):app.require_manual_combat(self.read())
    def test_real_combat_wins_grant_only_target_xp(self):
        before=self.read();self.start();self.settle(30000);p=self.ledger();self.assertGreater(p.get('trial_attributes',{}).get('attack_milli',0),0);self.assertEqual(p.get('trial_attributes',{}).get('max_hp_milli',0),0)
        self.assertGreaterEqual(rules.part(p)['highest']['attack_milli'],1);self.assertEqual(self.read().domains['inventory'],before.domains['inventory']);self.assertEqual(partition(before).get('total_xp'),p.get('total_xp'));trial_app.validate_state(self.read(),self.registry)
    def test_failure_stops_and_keeps_earned_xp(self):
        self.start();self.settle(600000);p=self.ledger();self.assertFalse(rules.running(p));self.assertEqual(rules.part(p)['reason'],'DEFEATED');xp=p['trial_attributes']['attack_milli'];self.settle(10000);self.assertEqual(self.ledger()['trial_attributes']['attack_milli'],xp)
    def test_trial_snapshot_does_not_nest_runtime(self):
        self.start();self.settle(30000);b=rules.part(self.ledger())['battle'];self.assertNotIn('attribute_trial',b['growth_snapshot']);self.assertIsNotNone(self.view()['cultivation']['attribute_trials']['battle'])
    def test_stop_under_world_pause(self):
        self.start();self.command('world_pause',{});before=self.ledger();self.clock.advance(60000);self.assertEqual(self.ledger(),before);self.command('attribute_trial_stop',{});self.assertFalse(rules.running(self.ledger()))
    def test_switch_preserves_separate_progress(self):
        self.start();self.settle(30000);self.command('attribute_trial_stop',{});earned=self.ledger()['trial_attributes']['attack_milli'];self.start('max_hp_milli');self.settle(30000);p=self.ledger();self.assertEqual(p['trial_attributes']['attack_milli'],earned);self.assertGreater(p['trial_attributes']['max_hp_milli'],0)

    def test_online_offline_and_small_continuations_are_identical(self):
        from src.core.time.model import Continuation
        self.start();initial=self.read();start=self.clock.now_ms()
        def advance(state,target,limit):
            with self.app() as app:
                for _ in range(100):
                    state,result=app.engine.advance(state,max_events=limit,**({'continuation':Continuation.for_state(state)} if state.time['pending'] else {'now_ms':target}))
                    if not state.time['pending']:return state
                self.fail('trial continuation did not finish')
        offline=advance(initial,start+60000,1);online=initial
        for elapsed in range(4000,60001,4000):online=advance(online,start+elapsed,1000)
        self.assertEqual(partition(offline),partition(online));self.assertEqual(offline.identity,online.identity);self.assertEqual(offline.domains['inventory'],online.domains['inventory'])
    def test_failed_commit_rolls_back_start_and_identity(self):
        from unittest.mock import patch
        before=self.read();q=self.request('attribute_trial_start',{'stat':'attack_milli','wave':1})
        with self.app() as app:
            with patch.object(app.store,'commit',side_effect=RuntimeError('injected')):
                with self.assertRaises(RuntimeError):app.execute(q)
        self.assertEqual(self.read(),before)
    def test_main_battle_blocks_trial_and_trial_blocks_pills(self):
        with self.app() as app:encounter=app.default_encounter(self.read())
        self.command('combat_start',{'encounter_id':encounter})
        with self.assertRaises(ConflictError):self.start()
    def test_caps_reject_bad_experience_without_changing_old_values(self):
        c=rules.config(self.registry);p=thaw_json(self.ledger());p['trial_attributes']={'attack_milli':rules.threshold(c,c['max_level'])+1}
        with self.assertRaises(ValidationError):growth.validate(p,self.registry,self.sid)
    def test_restarting_at_unlocked_wave_retains_all_earned_attributes(self):
        self.start();self.settle(30000);self.command('attribute_trial_stop',{});old=thaw_json(self.ledger()['trial_attributes']);high=rules.part(self.ledger())['highest']['attack_milli'];self.start(wave=high+1);self.assertEqual(self.ledger()['trial_attributes'],old)

    def test_real_monster_presentation_and_existing_terminal_battle_preserved(self):
        from src.rendering.game import present
        from src.rendering.game_runtime import GameRuntimeAssets
        from pathlib import Path
        with self.app() as app:encounter=app.default_encounter(self.read())
        self.command('combat_start',{'encounter_id':encounter})
        self.command('combat_abandon',{'battle_id':self.read().domains['combat']['battle']['battle_id']})
        old=self.read().domains['combat'];self.start();self.settle(30000)
        self.assertEqual(old,self.read().domains['combat'])
        presentation=present(self.view(),GameRuntimeAssets(Path(__file__).resolve().parents[1]/'assets'))
        self.assertIsNotNone(presentation['attribute_trial_enemy']['asset'])
    def test_event_alias_is_rejected(self):
        self.start();state=self.read();p=thaw_json(partition(state));w=p['attribute_trial']['wake'];w['next_event_id']=w['event_id'];candidate=replace(state,domains={**state.domains,'cultivation':p})
        with self.assertRaises(ValidationError):trial_app.validate_state(candidate,self.registry)

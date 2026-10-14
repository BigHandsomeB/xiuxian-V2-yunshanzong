"""Real deterministic Domain/atomic Inventory/save tests in isolated V2 fixtures."""
import copy,json,tempfile,unittest
from pathlib import Path
from contextlib import contextmanager
from dataclasses import replace
from uuid import uuid4
from unittest.mock import patch
from src.data.combat.definitions import load_combat, MonsterDefinition
from src.data.registry import DefinitionKey
from src.application.danding import initial_slice
from src.application.game import GameApplication
from src.application.memory import Command
from src.application.settlement import SettlementRequest
from src.core.save.sqlite import SQLiteSave,V2_ROOT
from src.core.save.codec import PersistenceError
from src.core.state.envelope import thaw_json,freeze_json
from src.core.validation import ValidationError,ConflictError,NotFoundError
from src.systems.combat import battle
from src.systems.inventory import operations,holdings
from src.application import sect
from tests.fixtures.time import ManualClock


class CombatTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=V2_ROOT/'tests');self.root=Path(self.temp.name);self.path=self.root/'combat.sqlite3';self.registry=load_combat();self.clock=ManualClock()
        self.state=initial_slice(self.registry,last_settled_at_ms=self.clock.now_ms());self.save=self.state.save_id
        with SQLiteSave.initialize(self.path,allowed_root=self.root) as store:GameApplication(store,self.registry,self.clock).create(self.state)
    def tearDown(self):self.temp.cleanup()
    @contextmanager
    def application(self):
        with SQLiteSave(self.path,allowed_root=self.root) as store:yield GameApplication(store,self.registry,self.clock)
    def state_now(self):
        with self.application() as g:return g.query(self.save)
    def command(self,name,payload,**overrides):
        s=self.state_now();fields=dict(save_id=self.save,generation=s.generation,expected_revision=s.revision,request_id=str(uuid4()),name=name,payload=payload);fields.update(overrides);return Command(**fields)
    def execute(self,request):
        with self.application() as g:return g.execute(request)
    def start(self):
        self.execute(self.command('combat_start',{'encounter_id':'thorn_first'}));return self.state_now().domains['combat']['battle']['battle_id']
    def attack(self,bid):return self.execute(self.command('combat_attack',{'battle_id':bid}))
    def win(self):
        bid=self.start()
        for _ in range(4):self.attack(bid)
        return bid
    def settle(self,bid):return self.execute(self.command('combat_reward',{'battle_id':bid}))

    def test_definition_validation_and_references(self):
        p=json.loads((V2_ROOT/'src/data/combat/content.json').read_text())
        for mutate in [lambda p:p['monsters'][0].update(base_hp_milli=0),lambda p:p['monsters'][0].update(attack_milli=True),lambda p:p['monsters'][0].update(reward={'unknown':1}),lambda p:p['encounters'][0].update(monster_id='missing'),lambda p:p['player'].update(level=2),lambda p:p['monsters'].append(p['monsters'][0])]:
            x=copy.deepcopy(p);mutate(x)
            with self.assertRaises((ValidationError,NotFoundError)):load_combat(json.dumps(x))
        with self.assertRaises(ValidationError):load_combat('{"schema_version":NaN}')
    def test_existing_alchemy_definitions_exactly_preserved(self):
        from src.data.recipes.alchemy import load_alchemy
        old=load_alchemy()
        for key,value in old._definitions.items():self.assertEqual(self.registry.lookup(key),value)
        self.assertEqual(self.registry.schema_version,old.schema_version);self.assertNotEqual(self.registry.content_version,old.content_version)
    def test_formal_player_projection_has_one_stable_identity(self):
        p=battle.player(self.registry,self.save);self.assertEqual(p['id'],self.save+':hero');self.assertEqual((p['max_hp_milli'],p['attack_milli'],p['armor_milli']),(80000,10000,500))
        self.assertNotIn('player',self.state_now().domains)
    def test_ready_queries_never_initialize_or_mutate(self):
        before=self.state_now()
        with self.application() as g,patch.object(self.clock,'now_ms',side_effect=AssertionError('no combat clock')):
            self.assertEqual(g.combat_view(self.save)['status'],'READY');g.view(self.save);g.combat_view(self.save)
        self.assertEqual(self.state_now(),before)
    def test_start_one_monster_with_definition_immutable(self):
        definition=self.registry.lookup(DefinitionKey('monsters','thorn_rat'));bid=self.start();b=self.state_now().domains['combat']['battle']
        self.assertTrue(bid.startswith(self.save+':1:i:'));self.assertEqual((b['enemy_id'],b['player_hp_milli'],b['enemy_hp_milli']),('thorn_rat',80000,35000));self.assertEqual(definition,self.registry.lookup(DefinitionKey('monsters','thorn_rat')))
    def test_cannot_start_duplicate_active_encounter(self):
        self.start();before=self.state_now()
        with self.assertRaises(ConflictError):self.start()
        self.assertEqual(self.state_now(),before)
    def test_start_replay_same_command_returns_original_battle(self):
        q=self.command('combat_start',{'encounter_id':'thorn_first'});r=self.execute(q);before=self.state_now();self.assertEqual(self.execute(q),r);self.assertEqual(self.state_now(),before)
    def test_attack_and_enemy_action_real_hp(self):
        bid=self.start();self.attack(bid);b=self.state_now().domains['combat']['battle'];self.assertEqual((b['enemy_hp_milli'],b['player_hp_milli'],b['step']),(25000,74500,1));self.assertEqual([e['kind'] for e in b['latest_events']],['player_attack','damage','enemy_hit','enemy_attack','damage','player_hit'])
    def test_attack_replay_does_not_apply_damage_twice(self):
        bid=self.start();q=self.command('combat_attack',{'battle_id':bid});r=self.execute(q);before=self.state_now();self.assertEqual(self.execute(q),r);self.assertEqual(self.state_now(),before)
    def test_concurrent_stale_attack_rejected(self):
        bid=self.start();a=self.command('combat_attack',{'battle_id':bid});b=self.command('combat_attack',{'battle_id':bid});self.execute(a)
        with self.assertRaises(ConflictError):self.execute(b)
        self.assertEqual(self.state_now().domains['combat']['battle']['step'],1)
    def test_generation_conflict(self):
        q=self.command('combat_start',{'encounter_id':'thorn_first'},generation=2)
        with self.assertRaises(ConflictError):self.execute(q)
    def test_command_id_cannot_change_intent(self):
        bid=self.start();a=self.command('combat_attack',{'battle_id':bid});self.execute(a)
        with self.assertRaises(ConflictError):self.execute(replace(a,name='combat_abandon'))
    def test_hp_clamps_and_overkill_actual_damage(self):
        bid=self.win();b=self.state_now().domains['combat']['battle'];self.assertEqual(b['enemy_hp_milli'],0);e=next(e for e in b['latest_events'] if e['kind']=='damage');self.assertEqual((e['damage_milli'],e['formula_damage_milli']),(5000,10000));self.assertEqual(b['player_hp_milli'],63500)
    def test_minimum_damage_including_zero_attack_and_high_armor(self):
        self.assertEqual(battle.damage(0,999999),1000);self.assertEqual(battle.damage(0,0),1000);self.assertEqual(battle.damage(10000,500),9500)
        for a,d in [(-1,0),(0,-1),(True,0)]:
            with self.assertRaises(ValidationError):battle.damage(a,d)
    def test_enemy_death_stops_counterattack_and_produces_win(self):
        bid=self.win();b=self.state_now().domains['combat']['battle'];self.assertEqual(b['status'],'PLAYER_WIN');self.assertNotIn('enemy_attack',[e['kind'] for e in b['latest_events']]);self.assertEqual(b['reward'],{'coins':3,'dewleaf':1});self.assertEqual(b['reward_state'],'READY')
    def test_player_death_lose_clamp_on_isolated_monster_fixture(self):
        # Same formal Domain and definition schema; no second production encounter.
        content=json.loads((V2_ROOT/'src/data/combat/content.json').read_text());content['monsters'][0]['attack_milli']=999000;r=load_combat(json.dumps(content))
        p=battle.start(battle.initial(),r,self.save,'test-battle','thorn_first');p=battle.attack(p,r,self.save,'test-battle');b=p['battle'];self.assertEqual((b['status'],b['player_hp_milli'],b['enemy_hp_milli']),('PLAYER_LOSE',0,25000));self.assertEqual(b['reward'],{});self.assertIn('player_defeated',[e['kind'] for e in b['latest_events']])
        with self.assertRaises(ValidationError):battle.reward_settled(p,r,self.save,'test-battle')
    def test_cannot_attack_completed_battle(self):
        bid=self.win();before=self.state_now()
        with self.assertRaises(ValidationError):self.attack(bid)
        self.assertEqual(self.state_now(),before)
    def test_cannot_reward_before_win(self):
        bid=self.start();before=self.state_now()
        with self.assertRaises(ValidationError):self.settle(bid)
        self.assertEqual(self.state_now(),before)
    def test_reward_enters_real_inventory_and_query(self):
        bid=self.win();self.settle(bid);state=self.state_now();self.assertEqual(state.domains['inventory']['holdings']['coins'],3);self.assertEqual(state.domains['inventory']['holdings']['dewleaf'],1)
        with self.application() as g:self.assertEqual(g.view(self.save)['holdings']['dewleaf']['quantity'],1);self.assertEqual(g.combat_view(self.save)['reward_state'],'SETTLED')
    def test_repeat_settlement_same_command_idempotent(self):
        bid=self.win();q=self.command('combat_reward',{'battle_id':bid});r=self.execute(q);before=self.state_now();self.assertEqual(self.execute(q),r);self.assertEqual(self.state_now(),before)
    def test_repeat_settlement_new_id_no_double_reward(self):
        bid=self.win();self.settle(bid);before=self.state_now();self.settle(bid);self.assertEqual(self.state_now(),before)
    def test_cannot_start_before_claiming_earned_reward(self):
        self.win()
        with self.assertRaises(ConflictError):self.start()
    def test_abandon_gives_no_reward(self):
        bid=self.start();self.attack(bid);before=self.state_now().domains['inventory'];self.execute(self.command('combat_abandon',{'battle_id':bid}));self.assertEqual(self.state_now().domains['combat']['battle']['status'],'ABANDONED');self.assertEqual(self.state_now().domains['inventory'],before)
        with self.assertRaises(ValidationError):self.settle(bid)
        self.start()
    def test_invalid_battle_id_and_unknown_encounter_do_not_mutate(self):
        before=self.state_now()
        with self.assertRaises(NotFoundError):self.execute(self.command('combat_start',{'encounter_id':'missing'}))
        self.assertEqual(self.state_now(),before);self.start();before=self.state_now()
        with self.assertRaises(NotFoundError):self.attack('missing')
        self.assertEqual(self.state_now(),before)
    def test_extra_client_hp_damage_and_rewards_rejected(self):
        before=self.state_now()
        with self.assertRaises(ValidationError):self.execute(self.command('combat_start',{'encounter_id':'thorn_first','player_hp':9999}))
        self.assertEqual(self.state_now(),before)
    def test_inventory_failure_rolls_back_and_retry_grants_once(self):
        bid=self.win();q=self.command('combat_reward',{'battle_id':bid});before=self.state_now()
        with patch('src.application.game.operations.grant',side_effect=ValidationError('injected inventory rejection')):
            with self.assertRaises(ValidationError):self.execute(q)
        self.assertEqual(self.state_now(),before);self.execute(q);self.execute(q);self.assertEqual(self.state_now().domains['inventory']['holdings']['dewleaf'],1)
    def test_commit_failure_atomic_and_no_receipt_then_retry(self):
        bid=self.win();q=self.command('combat_reward',{'battle_id':bid});before=self.state_now();original=SQLiteSave.commit
        def fail(store,*args):original(store,*args);raise PersistenceError('injected after candidate and receipt written')
        with patch.object(SQLiteSave,'commit',fail):
            with self.assertRaises(PersistenceError):self.execute(q)
        self.assertEqual(self.state_now(),before)
        with self.application() as g:self.assertIsNone(g.store.receipt(self.save,before.generation,q.request_id))
        self.execute(q);self.execute(q);self.assertEqual(self.state_now().domains['inventory']['holdings']['coins'],3)
    def test_attack_commit_failure_preserves_hp_and_replays_once(self):
        bid=self.start();q=self.command('combat_attack',{'battle_id':bid});before=self.state_now()
        with patch.object(SQLiteSave,'commit',side_effect=PersistenceError('failure')):
            with self.assertRaises(PersistenceError):self.execute(q)
        self.assertEqual(self.state_now(),before);self.execute(q);self.execute(q);self.assertEqual(self.state_now().domains['combat']['battle']['step'],1)
    def test_capacity_full_preserves_unsettled_reward(self):
        bid=self.win();s=self.state_now();capacity=sect.capacity_source(s,self.registry)['effective'];self.execute(self.command('inventory_grant',{'amounts':{'wood':capacity-30}}));before=self.state_now()
        with self.assertRaises(ValidationError):self.settle(bid)
        self.assertEqual(self.state_now(),before);self.execute(self.command('inventory_consume',{'amounts':{'wood':1}}));self.settle(bid);self.assertEqual(self.state_now().domains['combat']['battle']['status'],'SETTLED')
    def test_restart_refresh_and_no_offline_auto_combat(self):
        bid=self.start();self.attack(bid);before=self.state_now();self.clock.advance(60000)
        with self.application() as g:
            self.assertEqual(g.combat_view(self.save)['enemy']['hp'],25);self.assertEqual(g.query(self.save),before)
            g.settle(SettlementRequest(self.save,before.generation,before.revision,str(uuid4()),32,None))
        self.assertEqual(self.state_now().domains['combat'],before.domains['combat'])
    def test_checkpoint_and_generation_recovery_preserve_battle(self):
        from src.application.recovery import RecoveryApplication
        from src.core.save.recovery import RecoveryRequest
        bid=self.start();self.attack(bid)
        with self.application() as g:
            g.checkpoint(self.save);life=RecoveryApplication(g.foundation,self.clock);plan=life.inspect(self.save);request=RecoveryRequest(self.save,plan.current_generation,plan.current_fingerprint,plan.source_fingerprint,str(uuid4()),'isolated recovery test');self.assertEqual(life.recover(request).status,'SUCCESS')
        b=self.state_now().domains['combat']['battle'];self.assertEqual((b['battle_id'],b['enemy_hp_milli'],b['player_hp_milli']),(bid,25000,74500));self.attack(bid)
    def test_presentation_projection_cannot_mutate_or_recompute(self):
        bid=self.start();self.attack(bid);before=self.state_now()
        with self.application() as g,patch('src.systems.combat.battle.damage',side_effect=AssertionError('query cannot simulate')):
            v=g.combat_view(self.save);self.assertEqual(v['latest_events'][1]['damage'],10)
            with self.assertRaises(TypeError):v['enemy']['hp']=999
        self.assertEqual(self.state_now(),before)
    def test_tampered_domain_state_rejected_without_repair(self):
        bid=self.start();state=self.state_now();p=thaw_json(state.domains['combat']);p['battle']['enemy_hp_milli']=-1
        with self.application() as g:
            with self.assertRaises(ValidationError):g.foundation.validate_state(replace(state,domains={**state.domains,'combat':p}))
    def test_game_view_is_a_single_snapshot(self):
        with self.application() as g,patch.object(g,'query',wraps=g.query) as query:g.view(self.save);self.assertEqual(query.call_count,1)
    def test_new_battle_after_settlement_uses_fresh_id(self):
        first=self.win();self.settle(first);second=self.start();self.assertNotEqual(first,second);self.assertEqual(self.state_now().domains['combat']['battle']['player_hp_milli'],80000)

    def test_explicit_content_upgrade_preserves_existing_state_and_replays(self):
        from src.application.combat_upgrade import upgrade
        from src.application.danding import DandingApplication
        from src.data.recipes.alchemy import load_alchemy
        r=load_alchemy();s=initial_slice(r,last_settled_at_ms=1000);path=self.root/'upgrade.sqlite3'
        with SQLiteSave.initialize(path,allowed_root=self.root) as store:
            DandingApplication(store,r,self.clock).create(s);q=Command(s.save_id,s.generation,s.revision,str(uuid4()),'game_content_upgrade',{})
            receipt=upgrade(store,self.clock,q);after=store.inspect(s.save_id).current
            self.assertEqual(after,replace(s,content_version=self.registry.content_version,revision=s.revision+1));self.assertEqual(store.inspect(s.save_id).recovery,s)
            self.assertEqual(upgrade(store,self.clock,q),receipt);self.assertEqual(store.inspect(s.save_id).current,after)
            again=replace(q,request_id=str(uuid4()),expected_revision=after.revision);self.assertEqual(upgrade(store,self.clock,again).result['status'],'ALREADY_UPGRADED');self.assertEqual(store.inspect(s.save_id).current,after)
    def test_content_upgrade_failure_rolls_back_and_unknown_version_rejected(self):
        from src.application.combat_upgrade import upgrade
        from src.application.danding import DandingApplication
        from src.data.recipes.alchemy import load_alchemy
        r=load_alchemy();s=initial_slice(r,last_settled_at_ms=1000);path=self.root/'upgrade.sqlite3'
        with SQLiteSave.initialize(path,allowed_root=self.root) as store:
            DandingApplication(store,r,self.clock).create(s);q=Command(s.save_id,s.generation,s.revision,str(uuid4()),'game_content_upgrade',{})
            with patch.object(store,'commit',side_effect=PersistenceError('failure')):
                with self.assertRaises(PersistenceError):upgrade(store,self.clock,q)
            self.assertEqual(store.inspect(s.save_id).current,s);self.assertIsNone(store.inspect(s.save_id).recovery)
            with self.assertRaises(ValidationError):upgrade(store,self.clock,replace(q,name='inventory_grant'))

    def test_actual_fresh_process_recovers_active_battle_and_receipt(self):
        import subprocess,sys
        bid=self.start();q=self.command('combat_attack',{'battle_id':bid});self.execute(q);before=self.state_now()
        code="""import json,sys
from pathlib import Path
from src.core.save.sqlite import SQLiteSave
from src.data.combat.definitions import load_combat
from src.application.game import GameApplication
from src.application.memory import Command
from src.core.state.envelope import thaw_json
from tests.fixtures.time import ManualClock
root=Path(sys.argv[1]);q=Command(**json.loads(sys.argv[2]))
with SQLiteSave(root/'combat.sqlite3',allowed_root=root) as store:
 g=GameApplication(store,load_combat(),ManualClock());g.execute(q);print(json.dumps(thaw_json(g.combat_view(q.save_id))))
"""
        args={'save_id':q.save_id,'generation':q.generation,'expected_revision':q.expected_revision,'request_id':q.request_id,'name':q.name,'payload':thaw_json(q.payload)}
        result=subprocess.run([sys.executable,'-B','-c',code,str(self.root),json.dumps(args)],cwd=V2_ROOT,capture_output=True,text=True,check=True)
        view=json.loads(result.stdout);self.assertEqual((view['player']['hp'],view['enemy']['hp'],view['battle_id']),(74.5,25,bid));self.assertEqual(self.state_now(),before)

if __name__=='__main__':unittest.main()

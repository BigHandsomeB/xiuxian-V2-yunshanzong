"""Focused XP/settlement checks; no full regression or long simulation."""
import tempfile,unittest,json
from pathlib import Path
from uuid import uuid4
from dataclasses import replace,asdict
from unittest.mock import patch
from src.data.dungeons.definitions import load_dungeons
from src.data.cultivation.levels import thresholds
from src.systems.cultivation import growth,leveling
from src.systems.combat import battle
from src.application.cultivation import partition
from src.application.sect_management import ManagementApplication
from src.application.memory import Command
from src.application.settlement import SettlementRequest
from src.core.save.sqlite import SQLiteSave,V2_ROOT
from src.core.save.codec import StoredReceipt
from src.core.state.envelope import thaw_json
from src.core.validation import ValidationError
from tests.systems import test_settlement_batch as fixtures

class LevelCultivationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.registry=load_dungeons(management=True);cls.c=leveling.config(cls.registry)
    def p(self,L=1):return {'player_id':'design:hero','current_realm':'realm_0' if L<=500 else 'realm_1','total_xp':leveling.table(self.c)[L],'growth_revision':1}
    def test_thresholds_all_boundaries_and_monotonic(self):
        T=leveling.table(self.c);self.assertEqual(len(T),3002);self.assertEqual(T[2],160)
        self.assertTrue(all(T[i+1]>T[i] for i in range(1,3001)))
        for L in range(1,1001):
            p=self.p(L);self.assertEqual(leveling.level(p,self.c),L)
            if L not in (1,501):self.assertEqual(leveling.level({**p,'total_xp':T[L]-1},self.c),L-1)
        self.assertEqual(thresholds(160,2,1,1)[3],480)
    def test_gain_counts_and_realm_clamp(self):
        p=self.p(99);q,result=leveling.gain(p,self.registry,'design',leveling.table(self.c)[102]-p['total_xp']);self.assertEqual(result['levels_gained'],3)
        q,result=leveling.gain(self.p(500),self.registry,'design',10**12);self.assertEqual(q['total_xp'],leveling.table(self.c)[501]);self.assertEqual(leveling.level(q,self.c),500);self.assertNotIn('level',q);self.assertNotIn('progress',q)
    def test_penalty_boundaries(self):
        for L,expected in [(12,100),(13,90),(21,10),(22,10),(1000,10),(1,100)]:
            n,d=leveling.multiplier(L,10,self.c);self.assertEqual(n*100//d,expected)
    def test_migration_all_progress_values_no_attribute_loss(self):
        for realm,maximum,start in [('realm_0',1800,1),('realm_1',6000,501)]:
            for progress in range(maximum+1):
                old={'player_id':'design:hero','current_realm':realm,'progress':progress,'growth_revision':1};unchanged=dict(old)
                self.assertEqual(leveling.level(old,self.c),start+499*progress//maximum)
                new=leveling.projection(old,self.registry,'design');before=leveling.legacy_stats(old,self.registry)
                self.assertTrue(all(new[k]>=n for k,n in before.items()));self.assertEqual(old,unchanged)
            normalized=leveling.normalized(old,self.registry,'design');self.assertEqual(leveling.projection(old,self.registry,'design'),leveling.projection(normalized,self.registry,'design'))
    def test_pills_48_full_then_quarter_shared_count_world_period(self):
        stock={'ju_qi_pill':100};p=self.p();full=self.c['X0']*5//60
        # Near max of first interval would stop early, so independently verify 49 doses at level 1 with low configured X0.
        c=thaw_json(self.c);c['X0']=60
        with patch.object(leveling,'config',return_value=c):
            q,e=leveling.use_pill(p,self.registry,'design',stock,'ju_qi_pill',count=49,world_ms=0)
            self.assertEqual(q['total_xp'],48*5+1);self.assertEqual(q['pill_count'],49)
            q,e=leveling.use_pill(q,self.registry,'design',stock,'ju_qi_pill',world_ms=86400000)
            self.assertEqual(q['pill_count'],1);self.assertEqual(q['pill_window_start_ms'],86400000)
            with self.assertRaises(ValidationError):leveling.use_pill(q,self.registry,'design',stock,'ju_qi_pill',world_ms=0)
        q,e=leveling.use_pill(p,self.registry,'design',stock,'ju_qi_pill');self.assertEqual(q['total_xp'],full)
    def test_pill_intervals_and_batch_stop_without_extra_consumption(self):
        for key,row in self.c['pills'].items():
            for L in (row['minimum_level'],row['maximum_level']):self.assertFalse(leveling.pill_reasons(self.p(L),self.registry,'design',{key:10},key))
            outside=101 if row['maximum_level']==100 else row['minimum_level']-1
            with self.assertRaises(growth.CultivationBlocked):leveling.use_pill(self.p(outside),self.registry,'design',{key:10},key)
        p=self.p(100);p['total_xp']=leveling.table(self.c)[101]-1
        q,e=leveling.use_pill(p,self.registry,'design',{'ju_qi_pill':100},'ju_qi_pill',count=100)
        self.assertEqual(e[0]['quantity'],1);self.assertGreaterEqual(leveling.level(q,self.c),101)
    def test_breakthrough_requires_full_bar_cost_and_open_realm(self):
        cost=self.c['realms'][0]['cost']
        with self.assertRaises(growth.CultivationBlocked):leveling.breakthrough(self.p(500),self.registry,'design',cost)
        p=self.p(500);p['total_xp']=leveling.table(self.c)[501]
        with self.assertRaises(growth.CultivationBlocked):leveling.breakthrough(p,self.registry,'design',{})
        q,e=leveling.breakthrough(p,self.registry,'design',cost);self.assertEqual(leveling.level(q,self.c),501);self.assertEqual(q['total_xp'],p['total_xp'])
        with self.assertRaises(growth.CultivationBlocked):leveling.breakthrough(self.p(1000),self.registry,'design',cost)
    def test_64_fights_result_path_and_event_path_same_xp(self):
        p=self.p(24);actor=leveling.projection(p,self.registry,'design');a=p;b=p
        for i in range(64):
            identity=f'xp64:{i}';seed=battle.start(battle.initial(),self.registry,'design',identity,'thorn_path_v2_002',player_snapshot=actor)
            one=seed
            while one['battle']['status']=='ACTIVE':one=battle.attack(one,self.registry,'design',identity)
            compact,_,_=battle.result_only(seed,self.registry,'design');self.assertEqual(one['battle']['status'],compact['battle']['status'])
            if one['battle']['status']=='PLAYER_WIN':a,_=leveling.kill(a,self.registry,'design',2,'normal',identity)
            if compact['battle']['status']=='PLAYER_WIN':b,_=leveling.kill(b,self.registry,'design',2,'normal',identity)
        self.assertEqual(a,b);self.assertGreater(leveling.level(a,self.c),24)
    def fixture(self):
        f=fixtures.SettlementBatchTests();f.setUp();self.addCleanup(f.doCleanups);return f
    def test_one_hour_battle_and_auto_production_exact_parity(self):
        from src.systems.economy import policy
        f=self.fixture();s=f.state;p={**partition(s),'total_xp':leveling.table(self.c)[24],'growth_revision':1};p.pop('progress',None)
        inventory=thaw_json(s.domains['inventory']);inventory['holdings']['spring_water']=500
        s=replace(s,domains={**s.domains,'cultivation':p,'inventory':inventory})
        for kind,recipe in [('garden','grain'),('forest','wood')]:
            building=next(k for k,v in s.domains['sect']['buildings'].items() if v['definition_id']==kind)
            s=f.app.start_candidate(s,building,recipe)
            auto=policy.set_production(s.domains['automation'],f.registry,building,{'enabled':True,'recipe_id':recipe,'target':10000,'reserves':{},'max_consumption':10000});s=replace(s,domains={**s.domains,'automation':auto})
        s=f.app.engine.wake(s);f.app.engine.result_path=False;one,_,_=f.drain(s,3601000);f.app.engine.result_path=True;compact,_,_=f.drain(s,3601000)
        f.assert_same(one,compact);self.assertEqual(partition(one),partition(compact));self.assertGreater(partition(one)['total_xp'],p['total_xp']);self.assertGreater(one.domains['inventory']['holdings'].get('grain',0),s.domains['inventory']['holdings'].get('grain',0))
        self.assertEqual(one.domains['offline_reports']['unread'][-1]['cultivation'],compact.domains['offline_reports']['unread'][-1]['cultivation'])
    def store_fixture(self):
        f=self.fixture();tmp=tempfile.TemporaryDirectory(dir=V2_ROOT/'tests');self.addCleanup(tmp.cleanup);root=Path(tmp.name)
        store=SQLiteSave.initialize(root/'xp.sqlite3',allowed_root=root);self.addCleanup(store.close);app=ManagementApplication(store,f.registry,f.clock)
        s=f.state;d=thaw_json(s.domains['dungeon']);d['auto'].update(enabled=False,wake=None,tick_ready=False)
        inventory=thaw_json(s.domains['inventory']);inventory['holdings']['ju_qi_pill']=100
        s=replace(s,domains={**s.domains,'dungeon':d,'inventory':inventory});app.create(s);return app,app.query(s.save_id),f
    def test_pill_transaction_replay_restart_and_pause(self):
        app,s,f=self.store_fixture();q=Command(s.save_id,s.generation,s.revision,str(uuid4()),'cultivation_use_pill',{'item_id':'ju_qi_pill'})
        result=app.execute(q);first=app.query(s.save_id);self.assertEqual(first.domains['inventory']['holdings']['ju_qi_pill'],99)
        self.assertEqual(app.execute(q),result);self.assertEqual(app.query(s.save_id),first)
        restarted=ManagementApplication(app.store,f.registry,f.clock);self.assertEqual(restarted.execute(q),result)
        q=Command(s.save_id,s.generation,first.revision,str(uuid4()),'world_pause',{});app.execute(q);paused=app.query(s.save_id)
        f.clock.advance(86400000*10)
        with self.assertRaises(ValidationError):app.execute(Command(s.save_id,s.generation,paused.revision,str(uuid4()),'cultivation_use_pill',{'item_id':'ju_qi_pill'}))
        self.assertEqual(app.query(s.save_id),paused)
        with self.assertRaises(ValidationError):app.engine.advance(paused,max_events=64,now_ms=f.clock.now_ms())
    def test_reward_xp_rollback_and_repeat(self):
        app,s,f=self.store_fixture()
        n=s.identity['instance_counter']+1;identity=f'{s.save_id}:{s.generation}:i:{n}'
        combat=battle.start(battle.initial(),f.registry,s.save_id,identity,'thorn_path_v2_001',player_snapshot=app.player_projection(s),growth_snapshot=partition(s))
        while combat['battle']['status']=='ACTIVE':combat=battle.attack(combat,f.registry,s.save_id,identity)
        winning=replace(s,revision=s.revision+1,identity={**s.identity,'instance_counter':n},domains={**s.domains,'combat':combat});self.commit_fixture(app,s,winning)
        q=Command(s.save_id,s.generation,winning.revision,str(uuid4()),'combat_reward',{'battle_id':identity})
        with patch.object(app.store,'commit',side_effect=RuntimeError('write failed')):
            with self.assertRaises(RuntimeError):app.execute(q)
        self.assertEqual(app.query(s.save_id),winning)
        receipt=app.execute(q);after=app.query(s.save_id);self.assertGreater(receipt.result['xp_gained'],0);self.assertEqual(app.execute(q),receipt);self.assertEqual(app.query(s.save_id),after)
    def test_settlement_receipt_replay_includes_xp(self):
        app,s,f=self.store_fixture();d=thaw_json(s.domains['dungeon']);d['auto'].update(enabled=True);s=app.engine.wake(replace(s,domains={**s.domains,'dungeon':d}));before=app.query(s.save_id);s=replace(s,revision=before.revision+1);self.commit_fixture(app,before,s)
        f.clock.advance(120000);q=SettlementRequest(s.save_id,s.generation,s.revision,str(uuid4()),4096)
        receipt=app.settle(q);self.assertGreater(receipt.result.xp_gained,0);self.assertEqual(app.settle(q),receipt)
    def test_boss_equipment_gate_and_already_equipped_unchanged(self):
        from src.application.equipment import can_equip_realm
        app,s,f=self.store_fixture();self.assertFalse(can_equip_realm(s,f.registry,'thorn_king_blade'));self.assertTrue(can_equip_realm(s,f.registry,'thorn_fang_blade'))
        p={**self.p(501),'player_id':s.save_id+':hero'};s=replace(s,domains={**s.domains,'cultivation':p});self.assertTrue(can_equip_realm(s,f.registry,'thorn_king_armor'))
    def test_shipping_ecology_projection_and_legacy_snapshot(self):
        from src.application.ecology import EcologyApplication
        from src.application.danding import initial_slice
        registry=load_dungeons(management=True,cold_jade=True,ecology=True);app=EcologyApplication(None,registry,fixtures.ManualClock(1000));s=initial_slice(registry,last_settled_at_ms=1000)
        self.assertEqual(app.project_cultivation(s)['level'],1)
        self.assertEqual(len(app.project_cultivation(s)['foundation_pills']),10)
        self.assertIsNotNone(app.project_cultivation(s)['next_realm_preview'])

    def commit_fixture(self,app,before,candidate):
        q=Command(before.save_id,before.generation,before.revision,str(uuid4()),'fixture',{})
        with app.store.transaction():app.store.commit(before,candidate,StoredReceipt(candidate.save_id,candidate.generation,q.request_id,q.digest(),candidate.revision,'command',{}))
    def test_old_battle_snapshot_and_old_boss_equipment_stay_valid(self):
        from src.systems.equipment import items
        app,s,f=self.store_fixture();p={'player_id':s.save_id+':hero','current_realm':'realm_0','progress':1200,'growth_revision':1}
        actor=dict(leveling.projection(p,f.registry,s.save_id));actor.update(leveling.legacy_stats(p,f.registry));actor.pop('speed_bps',None);actor.pop('evasion_bps',None)
        n=s.identity['instance_counter']+1;identity=f'{s.save_id}:{s.generation}:i:{n}'
        combat=battle.start(battle.initial(),f.registry,s.save_id,identity,'thorn_path_v2_001',player_snapshot=actor)
        candidate=replace(s,identity={**s.identity,'instance_counter':n},domains={**s.domains,'cultivation':p,'combat':combat});app.foundation.validate_state(candidate)
        oldeq=items.add(s.domains['equipment'],f.registry,identity,'thorn_king_blade','old-boss',0,False)
        oldeq=items.equip(oldeq,f.registry,identity,False);candidate=replace(s,identity={**s.identity,'instance_counter':n},domains={**s.domains,'equipment':oldeq})
        app.foundation.validate_state(candidate);self.assertEqual(candidate.domains['equipment']['slots'][items.definition(f.registry,'thorn_king_blade').slot],identity)

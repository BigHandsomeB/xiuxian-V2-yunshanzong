"""Shipping command/receipt seam with disposable saves; no live mutations."""
import unittest
from dataclasses import replace
from src.core.state.envelope import thaw_json
from src.core.validation import ValidationError,ConflictError
from src.data.registry import DefinitionKey
from src.application.ecology import EcologyApplication
from src.application.sect_activities import transition
from src.systems.sect import activities
from src.systems.dungeons import progress
from tests.systems import test_ecology as fixtures

class ActivityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):fixtures.EcologyTests.setUpClass.__func__(cls)
    setUp=fixtures.EcologyTests.setUp
    read=fixtures.EcologyTests.read
    view=fixtures.EcologyTests.view
    fixture=fixtures.EcologyTests.fixture
    request=fixtures.EcologyTests.request
    execute=fixtures.EcologyTests.execute
    command=fixtures.EcologyTests.command
    settle=fixtures.EcologyTests.settle
    def seed(self,balance=1000,extra=None):
        def change(s):
            m=thaw_json(s.domains['sect_management']);p=activities.initial();p.update(contribution=balance,earned=balance)
            if extra:p.update(extra)
            m['activities']=p
            return replace(s,domains={**s.domains,'sect_management':m})
        self.fixture(change)
    def fill_order(self,row):
        def change(s):
            stock=thaw_json(s.domains['inventory']);stock['holdings'][row['resource_id']]=row['quantity']+10
            return replace(s,domains={**s.domains,'inventory':stock})
        self.fixture(change)
    def test_old_save_projection_is_pure_and_has_three_orders(self):
        s=self.read();self.assertNotIn('activities',s.domains['sect_management'])
        v=self.view()['sect_activities'];self.assertEqual(self.read(),s);self.assertEqual(v['contribution'],0);self.assertEqual(len(v['orders']),3);self.assertFalse(v['chests'])
    def test_claim_is_atomic_idempotent_and_protects_reserves(self):
        row=activities.orders(self.read(),self.registry)[0];self.fill_order(row)
        payload={k:row[k] for k in ('order_id','market_day','quote_id')};q=self.request('sect_commission_claim',payload)
        receipt=self.execute(q);s=self.read();self.assertEqual(self.execute(q),receipt);self.assertEqual(self.read(),s)
        self.assertEqual(activities.ledger(s)['contribution'],20)
        with self.assertRaises(ValidationError):self.command('sect_commission_claim',payload)
        self.assertEqual(self.read(),s)
        row=activities.orders(s,self.registry)[1];self.fill_order(row)
        def reserve(s):
            p=thaw_json(s.domains['sect_management']);p['material_reserves'][row['resource_id']]=11
            return replace(s,domains={**s.domains,'sect_management':p})
        self.fixture(reserve);before=self.read()
        with self.assertRaises(ValidationError):self.command('sect_commission_claim',{k:row[k] for k in ('order_id','market_day','quote_id')})
        self.assertEqual(self.read(),before)
    def test_saved_day_and_old_quote_rejection(self):
        row=activities.orders(self.read(),self.registry)[0];self.fill_order(row);s=self.read();payload={k:row[k] for k in ('order_id','market_day','quote_id')}
        candidate,_=transition(s,self.registry,'sect_commission_claim',payload,100000)
        later=replace(candidate,time={**candidate.time,'sim_time_ms':candidate.time['sim_time_ms']+candidate.time['day_length_ms']})
        self.assertEqual(activities.today(later)['contribution'],20);self.assertFalse(activities.today(later)['completed'])
        with self.assertRaises(ValidationError):transition(later,self.registry,'sect_commission_claim',payload,100000)
    def test_exchange_spends_contribution_not_reputation_and_replays(self):
        self.seed();before=self.read();q=self.request('sect_contribution_exchange',{'exchange_id':'manual_page'});r=self.execute(q);after=self.read()
        self.assertEqual(activities.ledger(after)['contribution'],900);self.assertEqual(activities.ledger(after)['earned'],1000)
        self.assertEqual(after.domains['inventory']['holdings'].get('manual_page',0),before.domains['inventory']['holdings'].get('manual_page',0)+1)
        self.assertEqual(self.execute(q),r);self.assertEqual(self.read(),after)
    def test_capacity_and_invalid_choices_never_consume_chest(self):
        self.seed(extra={'issued':['thorn_path'],'chests':{'thorn_path':{'tier':1,'battle_id':'first-boss'}}});s=self.read()
        for payload in ({'chest_id':'thorn_path','choice':'invalid'},{'chest_id':'missing','choice':'equipment'}):
            with self.assertRaises(ValidationError):transition(s,self.registry,'boss_chest_open',payload,100000)
        with self.assertRaises(ValidationError):transition(s,self.registry,'boss_chest_open',{'chest_id':'thorn_path','choice':'equipment'},0)
        with self.assertRaises(ValidationError):transition(s,self.registry,'sect_contribution_exchange',{'exchange_id':'wood'},0)
        self.assertEqual(self.read(),s)
    def test_nonwarehouse_rewards_remain_claimable_with_full_warehouse(self):
        self.seed(extra={'issued':['thorn_path'],'chests':{'thorn_path':{'tier':1,'battle_id':'first-boss'}}})
        s=self.read();candidate,_=transition(s,self.registry,'sect_contribution_exchange',{'exchange_id':'coins'},0)
        self.assertEqual(candidate.domains['inventory']['holdings']['coins'],s.domains['inventory']['holdings']['coins']+200)
        candidate,_=transition(s,self.registry,'boss_chest_open',{'chest_id':'thorn_path','choice':'techniques'},0)
        self.assertEqual(candidate.domains['inventory']['holdings'].get('manual_page',0),s.domains['inventory']['holdings'].get('manual_page',0)+4)

    def test_chest_claim_once_all_choices_and_resume(self):
        for choice in ('equipment','management','techniques'):
            self.seed(extra={'issued':['thorn_path'],'chests':{'thorn_path':{'tier':1,'battle_id':'first-boss'}}})
            q=self.request('boss_chest_open',{'chest_id':'thorn_path','choice':choice});r=self.execute(q);after=self.read()
            self.assertFalse(activities.ledger(after)['chests']);self.assertEqual(self.execute(q),r);self.assertEqual(self.read(),after)
            with self.assertRaises(ValidationError):self.command('boss_chest_open',q.payload)
    def test_first_clear_new_chest_no_retroactive_or_repeat(self):
        s=self.read();did='thorn_path';b={'encounter_id':progress.definition(self.registry,did).encounters[-1],'battle_id':'first-boss'}
        p=activities.issue_chest(s,s,self.registry,b);self.assertEqual(p['chests'][did]['tier'],1)
        m=thaw_json(s.domains['sect_management']);m['activities']=p;issued=replace(s,domains={**s.domains,'sect_management':m})
        self.assertIsNone(activities.issue_chest(s,issued,self.registry,b))
        d=thaw_json(s.domains['dungeon']);d['cleared_floor']=100;old=replace(s,domains={**s.domains,'dungeon':d})
        self.assertIsNone(activities.issue_chest(old,old,self.registry,b))
    def test_paused_instant_operations_keep_world_time(self):
        self.seed();self.command('world_pause',{});before=self.read();self.command('sect_contribution_exchange',{'exchange_id':'coins'});after=self.read()
        self.assertEqual(before.time,after.time);self.assertEqual(activities.ledger(after)['contribution'],900)
    def test_real_boss_reward_issues_chest_and_keeps_existing_rewards(self):
        from src.application.cultivation import partition
        from src.systems.cultivation import techniques,leveling
        from src.systems.combat import battle
        state=self.read();p=thaw_json(partition(state));p.pop('progress',None)
        p.update(current_realm='realm_1',total_xp=leveling.table(leveling.config(self.registry))[1000],growth_revision=10)
        cfg=techniques.config(self.registry)
        names=['逍遥无极身','万劫不坏身','乾坤破界斩','混沌葬仙经','先天一气诀','鸿蒙养气经','混沌归元功','大道长生诀']
        rows=[next(r for r in cfg['techniques'] if r['name']==name) for name in names]
        p['techniques']['owned']={r['id']:techniques.threshold(cfg,cfg['grades'][r['grade']],r) for r in rows}
        p['techniques']['slots']=dict(zip(cfg['slots'],[r['id'] for r in rows]));p['techniques']['claims']={}
        d=thaw_json(state.domains['dungeon']);d['cleared_floor']=99
        state=replace(state,domains={**state.domains,'cultivation':p,'dungeon':d})
        app=EcologyApplication(None,self.registry,self.clock);counter=state.identity['instance_counter']+1
        encounter=progress.definition(self.registry,'thorn_path').encounters[-1]
        fight=battle.start(battle.initial(),self.registry,self.sid,f'{self.sid}:1:i:{counter}',encounter,player_snapshot=app.player_projection(state),growth_snapshot=p)
        fight,_,_=battle.result_only(fight,self.registry,self.sid);self.assertEqual(fight['battle']['status'],'PLAYER_WIN')
        state=replace(state,identity={**state.identity,'instance_counter':counter},domains={**state.domains,'combat':fight});self.fixture(lambda _:state)
        self.assertEqual(self.view()['combat']['choice_chest']['state'],'AWAITING_REWARD')
        q=self.request('combat_reward',{'battle_id':fight['battle']['battle_id']});receipt=self.execute(q);after=self.read()
        self.assertEqual(self.view()['combat']['choice_chest']['state'],'READY_IN_WAREHOUSE')
        self.assertIn('thorn_path',activities.ledger(after)['chests']);self.assertEqual(progress.cleared(after.domains['dungeon'],'thorn_path'),100)
        self.assertEqual(after.domains['inventory']['holdings'].get('manual_page'),1)
        for rid,n in app.stone_reward_quote(state,fight['battle']).items():
            self.assertEqual(after.domains['inventory']['holdings'].get(rid,0),state.domains['inventory']['holdings'].get(rid,0)+n)
        self.assertEqual(self.execute(q),receipt);self.assertEqual(self.read(),after)
        # A repeat kill reaches the same shipping reward path, without another chest.
        self.command('boss_chest_open',{'chest_id':'thorn_path','choice':'techniques'})
        repeat=self.read();app=EcologyApplication(None,self.registry,self.clock);counter=repeat.identity['instance_counter']+1
        fight=battle.start(battle.initial(),self.registry,self.sid,f'{self.sid}:1:i:{counter}',encounter,player_snapshot=app.player_projection(repeat),growth_snapshot=partition(repeat))
        fight,_,_=battle.result_only(fight,self.registry,self.sid)
        repeat=replace(repeat,identity={**repeat.identity,'instance_counter':counter},domains={**repeat.domains,'combat':fight});self.fixture(lambda _:repeat)
        self.command('combat_reward',{'battle_id':fight['battle']['battle_id']});self.assertFalse(activities.ledger(self.read())['chests'])

    def test_offline_cross_day_preserves_chests_without_free_contribution(self):
        self.seed(extra={'issued':['thorn_path'],'chests':{'thorn_path':{'tier':1,'battle_id':'first-boss'}}})
        for elapsed in (1800000,86400000):
            self.settle(elapsed);p=activities.ledger(self.read())
            self.assertEqual(p['contribution'],1000);self.assertEqual(p['earned'],1000)
            self.assertIn('thorn_path',p['chests']);self.assertEqual(len(self.view()['sect_activities']['orders']),3)
    def test_malformed_choice_payload_is_validation_error(self):
        self.seed(extra={'issued':['thorn_path'],'chests':{'thorn_path':{'tier':1,'battle_id':'first-boss'}}})
        before=self.read()
        with self.assertRaises(ValidationError):self.command('boss_chest_open',{'chest_id':[],'choice':'management'})
        row=activities.orders(before,self.registry)[0]
        with self.assertRaises(ValidationError):self.command('sect_commission_claim',{'order_id':row['order_id'],'market_day':False,'quote_id':row['quote_id']})
        self.assertEqual(self.read(),before)

    def test_corrupt_ledger_rejected(self):
        for change in ({'contribution':1},{'completed':['unknown']},{'issued':['missing']},{'chests':{'thorn_path':{'tier':1,'battle_id':'x'}}}):
            p=activities.initial();p.update(change)
            with self.assertRaises(ValidationError):activities.validate(p,self.registry)

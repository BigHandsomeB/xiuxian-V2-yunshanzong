"""Paused commands keep atomic, idempotent authority and a frozen time axis."""
import unittest
from dataclasses import replace
from uuid import uuid4
from pathlib import Path
from tests.systems import test_sect_management as f
from src.application import equipment as equip
from src.application.memory import Command
from src.application.settlement import SettlementRequest
from src.application.sect_management import ManagementApplication
from src.core.save.sqlite import SQLiteSave
from src.core.state.envelope import thaw_json
from src.core.time.world import WorldPaused
from src.core.time.model import Continuation
from src.core.validation import ConflictError,ValidationError
from tests.fixtures.time import ManualClock

class PausedCommandsTests(unittest.TestCase):
    app=f.ManagementTests.app
    read=f.ManagementTests.read
    view=f.ManagementTests.view
    q=f.ManagementTests.q
    execute=f.ManagementTests.execute
    cmd=f.ManagementTests.cmd
    fixture=f.ManagementTests.fixture
    rank_two=f.ManagementTests.rank_two
    offer_day=f.ManagementTests.offer_day
    settle=f.ManagementTests.settle
    drain=f.ManagementTests.drain
    def setUp(self):
        f.ManagementTests.setUp(self)
        for bid,p in self.read().domains['automation']['production'].items():
            if p['enabled']:self.cmd('automation_production',{'building_id':bid,'policy':{**thaw_json(p),'enabled':False}})
        for bid in {a['building_id'] for g in self.view()['disciples']['groups'] for a in g['assignments']}:self.cmd('work_unassign',{'building_id':bid})
        self.cmd('world_pause',{})
    def once(self,name,payload):
        before=self.read();q=self.q(name,payload);receipt=self.execute(q);after=self.read()
        self.assertEqual(before.time,after.time);self.assertEqual(self.execute(q),receipt);self.assertEqual(self.read(),after)
        return receipt
    def acquire(self):
        ids=[]
        def grant(s):
            s,identity=equip.acquire(s,self.r,'thorn_fang_blade','paused-test-'+str(s.identity['instance_counter']));ids.append(identity);return s
        self.fixture(grant);return ids[0]
    def roomy(self):
        def change(s):
            stock=thaw_json(s.domains['inventory']);stock['holdings']={k:n for k,n in stock['holdings'].items() if k in ('coins','pill','spring_water')}
            return replace(s,domains={**s.domains,'inventory':stock})
        self.fixture(change)
    def test_equipment_flags_wearing_sale_salvage_and_all(self):
        self.roomy();identity=self.acquire()
        for name,value in [('equipment_lock',True),('equipment_lock',False),('equipment_favorite',True),('equipment_favorite',False)]:self.once(name,{'instance_id':identity,'value':value})
        self.once('equipment_equip',{'instance_id':identity});self.assertTrue(next(r for r in self.view()['equipment']['instances'] if r['instance_id']==identity)['equipped'])
        self.once('equipment_unequip',{'instance_id':identity})
        self.once('equipment_sell',{'instance_id':identity});self.assertNotIn(identity,self.read().domains['equipment']['instances'])
        self.once('equipment_salvage',{'instance_ids':[self.acquire(),self.acquire()]})
        self.once('equipment_sell',{'instance_ids':[self.acquire(),self.acquire()]})
        for name in ('equipment_sell_all','equipment_salvage_all'):
            self.acquire();self.acquire();digest=self.view()['equipment']['bulk']['selection_digest'];self.once(name,{'selection_digest':digest});self.assertEqual(self.view()['equipment']['bulk']['count'],0)
    def test_settings_reserves_supply_and_policies(self):
        self.once('material_overflow',{'enabled':True});self.once('material_reserve',{'resource_id':'wood','quantity':5});self.once('sect_supply',{'enabled':True,'reserve':10})
        policy=self.view()['equipment']['policy'];self.once('automation_equipment',{'policy':thaw_json(policy)})
        bid=next(b['instance_id'] for b in self.view()['buildings'].values() if b['definition_id']=='garden')
        self.once('automation_production',{'building_id':bid,'policy':{'enabled':True,'recipe_id':'herb','target':10,'max_consumption':5,'reserves':{}}})
        before=self.read();self.clock.advance(3600000);self.assertEqual(self.read(),before)
    def test_craft_and_enhancement_with_existing_gate_rules(self):
        f.ManagementTests.test_craft_gates_and_correct_saved_roll(self)
        f.ManagementTests.test_enhancement_atomic_replay_base_unchanged_and_cap(self)
        self.assertTrue(self.read().time['world_paused'])
    def test_upgrade_and_facility_with_existing_gate_rules(self):
        f.ManagementTests.test_added_construction_material_boundaries_and_facility_unlock_path(self)
        self.assertTrue(self.read().time['world_paused'])
    def test_trade_exact_prices_and_replay(self):
        self.roomy();row=self.view()['sect_services']['market']['offers'][0]
        before=self.read();self.once('market_buy',{'resource_id':row['resource_id'],'quantity':1,'market_day':row['market_day'],'price_milli':row['price_milli']})
        self.assertEqual(before.domains['inventory']['holdings']['coins']-self.read().domains['inventory']['holdings']['coins'],(row['price_milli']+999)//1000)
        f.ManagementTests.test_high_stone_trade_atomic_and_replay(self)
    def test_time_commands_rejected_without_mutation(self):
        for name in ('dungeon_auto','dungeon_select','combat_start','combat_attack','combat_abandon','combat_reward','market_bid','market_consign','market_auction_claim','market_consignment_claim'):
            before=self.read()
            with self.assertRaisesRegex(WorldPaused,'世界已暂停'):self.cmd(name,{})
            self.assertEqual(self.read(),before)
        before=self.read()
        with self.assertRaises(WorldPaused):self.settle()
        self.assertEqual(before,self.read())
    def test_revision_and_generation_still_checked(self):
        s=self.read()
        for generation,revision in [(s.generation+1,s.revision),(s.generation,s.revision+1)]:
            with self.assertRaises(ConflictError):self.execute(Command(self.sid,generation,revision,str(uuid4()),'material_overflow',{'enabled':True}))
        self.assertEqual(self.read(),s)
    def test_paused_start_assignment_and_one_hour_resume_equivalence(self):
        # Clone one isolated save; no production or time authority outside SQLite.
        self.cmd('world_resume',{});base=self.read();path=self.root/'control.sqlite3';control_clock=ManualClock(self.clock.now_ms())
        with SQLiteSave.initialize(path,allowed_root=self.root) as store:ManagementApplication(store,self.r,control_clock).create(base)
        self.cmd('world_pause',{})
        bid=next(b['instance_id'] for b in self.view()['buildings'].values() if b['definition_id']=='garden')
        actions=[('work_assign',{'building_id':bid,'count':1}),('material_reserve',{'resource_id':'wood','quantity':3}),('sect_supply',{'enabled':True,'reserve':10}),('production_start',{'building_id':bid,'recipe_id':'herb'})]
        for name,payload in actions:
            self.once(name,payload)
            with SQLiteSave(path,allowed_root=self.root) as store:
                a=ManagementApplication(store,self.r,control_clock);s=a.query(self.sid);a.execute(Command(self.sid,s.generation,s.revision,str(uuid4()),name,payload))
        frozen=self.read();self.clock.advance(3600000);self.assertEqual(self.read(),frozen);self.cmd('world_resume',{});self.clock.advance(3600000);self.drain()
        control_clock.advance(3600000)
        with SQLiteSave(path,allowed_root=self.root) as store:
            a=ManagementApplication(store,self.r,control_clock)
            for _ in range(32):
                s=a.query(self.sid);a.settle(SettlementRequest(self.sid,s.generation,s.revision,str(uuid4()),32,None if not s.time['pending'] else Continuation.for_state(s)))
                if not a.query(self.sid).time['pending']:break
            other=a.query(self.sid)
        final=self.read();self.assertEqual(final.time['sim_time_ms'],other.time['sim_time_ms']);self.assertEqual(final.domains['inventory'],other.domains['inventory']);self.assertEqual(final.domains['production'],other.domains['production']);self.assertEqual(final.domains['disciples'],other.domains['disciples'])
        self.assertEqual(final.domains['sect_management']['material_reserves'],other.domains['sect_management']['material_reserves'])

    def test_pill_training_breakthrough_and_foundation_pill(self):
        from src.systems.cultivation import growth
        from math import ceil
        def supply(s):
            stock=thaw_json(s.domains['inventory']);stock['holdings'].update(pill=ceil(growth.realm(self.r,'realm_0').threshold/growth.action(self.r).gain)+10,gu_yuan_pill=3)
            for key,n in growth.realm(self.r,'realm_0').cost:stock['holdings'][key]=max(stock['holdings'].get(key,0),n+10)
            return replace(s,domains={**s.domains,'inventory':stock,'cultivation':growth.initial(self.sid)})
        self.fixture(supply);p=self.read().domains['cultivation'];threshold=growth.realm(self.r,p['current_realm']).threshold
        count=ceil(threshold/growth.action(self.r).gain)
        self.once('cultivation_train',{'count':count});self.assertEqual(self.read().domains['cultivation']['progress'],threshold)
        self.once('cultivation_breakthrough',{});self.assertEqual(self.read().domains['cultivation']['current_realm'],'realm_1')
        before=self.read();self.once('cultivation_use_pill',{'item_id':'gu_yuan_pill','count':1})
        self.assertEqual(self.read().domains['inventory']['holdings']['gu_yuan_pill'],before.domains['inventory']['holdings']['gu_yuan_pill']-1)
    def test_material_sell_and_order_delivery(self):
        f.ManagementTests.test_material_sell_reserve_replay_atomic(self)
        row=self.view()['sect_services']['orders'][0]
        def seed(s):
            stock=thaw_json(s.domains['inventory']);stock['holdings'][row['resource_id']]=row['quantity']+10
            return replace(s,domains={**s.domains,'inventory':stock})
        self.fixture(seed);self.once('material_reserve',{'resource_id':row['resource_id'],'quantity':0})
        before=self.read();self.once('market_order',{'order_id':row['order_id'],'market_day':row['market_day'],'quote_id':row['quote_id']})
        self.assertEqual(self.read().domains['inventory']['holdings']['coins']-before.domains['inventory']['holdings']['coins'],row['coins'])
    def test_safe_recruit_and_unassignment_do_not_release_inflight_workers(self):
        bid=next(b['instance_id'] for b in self.view()['buildings'].values() if b['definition_id']=='garden')
        self.once('work_assign',{'building_id':bid,'count':1});self.once('production_start',{'building_id':bid,'recipe_id':'herb'})
        before=self.read();self.once('work_unassign',{'building_id':bid});after=self.read()
        self.assertEqual(after.domains['disciples']['commitments'],before.domains['disciples']['commitments'])
        self.assertEqual(self.view()['buildings'][bid]['occupied_count'],1)
        self.once('sect_recruit',{'count':1});frozen=self.read();self.clock.advance(3600000);self.assertEqual(self.read(),frozen)
    def test_same_setting_new_request_keeps_revision_and_clock(self):
        self.once('material_overflow',{'enabled':True});before=self.read();self.once('material_overflow',{'enabled':True});self.assertEqual(self.read(),before)

    def test_reassignment_and_alchemy_start_at_frozen_time(self):
        from src.systems.resources import jobs
        garden=next(b['instance_id'] for b in self.view()['buildings'].values() if b['definition_id']=='garden')
        forest=next(b['instance_id'] for b in self.view()['buildings'].values() if b['definition_id']=='forest')
        alchemy=next(b['instance_id'] for b in self.view()['buildings'].values() if b['definition_id']=='alchemy')
        self.once('work_assign',{'building_id':garden,'count':1})
        gid=next(g['instance_id'] for g in self.view()['disciples']['groups'] if any(a['building_id']==garden for a in g['assignments']))
        self.once('work_reassign',{'worker_id':gid,'from_building_id':garden,'to_building_id':forest})
        self.once('work_assign',{'building_id':alchemy,'count':1})
        def seed(s):
            stock=thaw_json(s.domains['inventory'])
            for key,n in jobs.definition(self.r,'pill').inputs:stock['holdings'][key]=max(stock['holdings'].get(key,0),n)
            return replace(s,domains={**s.domains,'inventory':stock})
        self.fixture(seed);before=self.read();self.once('alchemy_start',{'building_id':alchemy,'recipe_id':'pill'})
        self.assertEqual(self.read().domains['production']['jobs'][alchemy]['started_ms'],before.time['sim_time_ms'])

    def test_paused_write_failure_rolls_back_state_and_receipt(self):
        from unittest.mock import patch
        before=self.read();q=self.q('material_overflow',{'enabled':not before.domains['automation']['material_overflow']});original=SQLiteSave.commit
        def fail(store,*args):original(store,*args);raise RuntimeError('fixture after-write failure')
        with patch.object(SQLiteSave,'commit',fail):
            with self.assertRaisesRegex(RuntimeError,'after-write'):self.execute(q)
        self.assertEqual(self.read(),before);receipt=self.execute(q);after=self.read();self.assertEqual(self.execute(q),receipt);self.assertEqual(self.read(),after)

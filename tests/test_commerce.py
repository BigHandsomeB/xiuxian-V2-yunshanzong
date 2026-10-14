import unittest
from dataclasses import replace
from unittest.mock import patch
from src.core.validation import ValidationError
from src.core.state.envelope import thaw_json
from src.core.save.sqlite import SQLiteSave
from src.data.economy.market import settings
from src.systems.sect import market,commerce
from src.systems.economy import overflow
from src.systems.equipment import items
from src.systems.economy.valuation import craft_inputs
from src.application.sect_economy import reserved
from tests.systems import test_sect_management as fixtures

class CommerceTests(unittest.TestCase):
    setUp=fixtures.ManagementTests.setUp
    app=fixtures.ManagementTests.app
    read=fixtures.ManagementTests.read
    view=fixtures.ManagementTests.view
    fixture=fixtures.ManagementTests.fixture
    q=fixtures.ManagementTests.q
    execute=fixtures.ManagementTests.execute
    cmd=fixtures.ManagementTests.cmd
    settle=fixtures.ManagementTests.settle
    drain=fixtures.ManagementTests.drain

    def unlock(self):
        def change(s):
            sect=thaw_json(s.domains['sect'])
            for r in sect['buildings'].values():r['level']=max(5,r['level'])
            return replace(s,domains={**s.domains,'sect':sect,'dungeon':{**s.domains['dungeon'],'cleared_floor':100,'progress':{'red_copper_mine':100,'mist_marsh':100}}})
        self.fixture(change)
    def time(self,ms):self.fixture(lambda s:replace(s,time={**s.time,'sim_time_ms':ms}))
    def seed(self,rid,n):self.fixture(lambda s:replace(s,domains={**s.domains,'inventory':{**s.domains['inventory'],'holdings':{**s.domains['inventory']['holdings'],rid:n}}}))
    def fill(self):
        v=self.view();self.seed('stone',self.read().domains['inventory']['holdings'].get('stone',0)+v['capacity']['effective']-v['capacity']['used'])
    def offer(self):return self.view()['sect_services']['market']['offers'][0]
    def bid(self,win=True):
        self.unlock();r=commerce.auction_offers(self.read(),self.r)[0];amount=r['npc_bid']+1 if win else r['start_coins']+(r['start_coins']+9)//10
        self.cmd('market_bid',{'auction_id':r['auction_id'],'bid':amount});return r,amount

    def test_old_save_read_defaults_are_pure(self):
        before=self.read();v=self.view();self.assertNotIn('commerce',before.domains['sect_management']);self.assertEqual(before,self.read());self.assertEqual(len(v['sect_services']['orders']),3)
    def test_boss_value_progress_and_offer_cap(self):
        cfg=settings(self.r)['items'];self.assertGreaterEqual(cfg['thorn_king_core']['sell_coins'],80)
        self.assertNotIn('thorn_king_core',market.eligible(self.read(),self.r));self.assertNotIn('red_copper_mine_material_01',market.eligible(self.read(),self.r));self.unlock();eligible=market.eligible(self.read(),self.r)
        for d in range(100):
            rows=market.offers(self.r,self.sid,d,eligible);self.assertEqual(len(rows),20);self.assertLessEqual(sum(cfg[r]['boss_only'] for r in rows),1)
    def test_cumulative_stock_no_reset_on_read_or_restart(self):
        row=self.offer();qty=row['remaining_stock'];q=self.q('market_buy',{'resource_id':row['resource_id'],'quantity':qty,'market_day':row['market_day'],'price_milli':row['price_milli']});receipt=self.execute(q);after=self.read();self.assertEqual(receipt,self.execute(q));self.assertEqual(after,self.read())
        self.assertEqual(market.stock_remaining(after,self.r,row['resource_id']),0);before=self.read()
        with self.assertRaises(ValidationError):self.cmd('market_buy',{'resource_id':row['resource_id'],'quantity':1,'market_day':row['market_day'],'price_milli':row['price_milli']})
        self.assertEqual(before,self.read());self.time(120000);self.assertGreater(market.stock_remaining(self.read(),self.r,row['resource_id']),0)
    def test_stock_rollback_and_invalid_quote(self):
        row=self.offer();before=self.read();p={'resource_id':row['resource_id'],'quantity':1,'market_day':row['market_day'],'price_milli':row['price_milli']}
        with patch.object(SQLiteSave,'commit',side_effect=RuntimeError('fixture')):
            with self.assertRaises(RuntimeError):self.cmd('market_buy',p)
        self.assertEqual(before,self.read())
        with self.assertRaises(ValidationError):self.cmd('market_buy',{**p,'price_milli':p['price_milli']+1})
        self.assertEqual(before,self.read())
    def test_order_one_delivery_replay_and_new_day(self):
        r=self.view()['sect_services']['orders'][0];self.seed(r['resource_id'],r['quantity']+10);q=self.q('market_order',{'order_id':r['order_id'],'market_day':r['market_day'],'quote_id':r['quote_id']});before=self.read();receipt=self.execute(q);after=self.read();self.assertEqual(before.domains['inventory']['holdings'][r['resource_id']]-after.domains['inventory']['holdings'][r['resource_id']],r['quantity']);self.assertEqual(after.domains['inventory']['holdings']['coins']-before.domains['inventory']['holdings']['coins'],r['coins']);self.assertEqual(receipt,self.execute(q))
        with self.assertRaises(ValidationError):self.cmd('market_order',dict(q.payload))
        self.time(120000)
        with self.assertRaises(ValidationError):self.cmd('market_order',dict(q.payload))
        self.assertEqual(receipt,self.execute(q))
    def test_order_reserves_and_pause(self):
        r=self.view()['sect_services']['orders'][0];self.seed(r['resource_id'],r['quantity']);self.cmd('material_reserve',{'resource_id':r['resource_id'],'quantity':1});before=self.read()
        with self.assertRaises(ValidationError):self.cmd('market_order',{'order_id':r['order_id'],'market_day':r['market_day'],'quote_id':r['quote_id']})
        self.assertEqual(before,self.read());self.cmd('world_pause',{});before=self.read()
        with self.assertRaises(ValidationError):self.cmd('market_order',{'order_id':r['order_id'],'market_day':r['market_day'],'quote_id':r['quote_id']})
        self.assertEqual(before,self.read())
    def test_win_escrow_deadline_and_once_claim(self):
        r,amount=self.bid();before=self.read()
        with self.assertRaises(ValidationError):self.cmd('market_auction_claim',{'auction_id':r['auction_id']})
        self.assertEqual(before,self.read());self.time(r['end_ms']);before=self.read();q=self.q('market_auction_claim',{'auction_id':r['auction_id']});receipt=self.execute(q);after=self.read();self.assertEqual(after.domains['inventory']['holdings'].get(r['resource_id'],0),before.domains['inventory']['holdings'].get(r['resource_id'],0)+1);self.assertEqual(after.domains['inventory']['holdings']['coins'],before.domains['inventory']['holdings']['coins']);self.assertEqual(receipt,self.execute(q))
        with self.assertRaises(ValidationError):self.cmd('market_auction_claim',{'auction_id':r['auction_id']})
    def test_lost_refund_even_full_warehouse(self):
        r,amount=self.bid(False);self.time(r['end_ms']);self.fill();before=self.read();self.cmd('market_auction_claim',{'auction_id':r['auction_id']});self.assertEqual(self.read().domains['inventory']['holdings']['coins']-before.domains['inventory']['holdings']['coins'],amount)
    def test_full_warehouse_preserves_winning_escrow(self):
        r,amount=self.bid();self.time(r['end_ms']);self.fill();before=self.read()
        with self.assertRaises(ValidationError):self.cmd('market_auction_claim',{'auction_id':r['auction_id']})
        self.assertEqual(before,self.read());self.seed('stone',self.read().domains['inventory']['holdings']['stone']-1);self.cmd('market_auction_claim',{'auction_id':r['auction_id']})
    def test_bid_raise_charges_delta_and_replay(self):
        r,amount=self.bid();before=self.read();new=amount+(amount+9)//10;q=self.q('market_bid',{'auction_id':r['auction_id'],'bid':new});receipt=self.execute(q);after=self.read();self.assertEqual(before.domains['inventory']['holdings']['coins']-after.domains['inventory']['holdings']['coins'],new-amount);self.assertEqual(receipt,self.execute(q))
        with self.assertRaises(ValidationError):self.cmd('market_bid',{'auction_id':r['auction_id'],'bid':new+1})
    def test_bid_closed_rejects_and_previous_cycle_can_claim(self):
        r,amount=self.bid();self.time(7*120000);before=self.read()
        with self.assertRaises(ValidationError):self.cmd('market_bid',{'auction_id':r['auction_id'],'bid':amount*2})
        self.assertEqual(before,self.read());self.cmd('market_auction_claim',{'auction_id':r['auction_id']})
    def test_consignment_sale_fee_and_unsold_return(self):
        self.unlock();rid='thorn_king_core'
        for sold in (True,False):
            for d in range(market.day(self.read()),market.day(self.read())+100):
                self.time(d*120000);r=commerce.consignment_quote(self.read(),self.r,rid)
                if (r['npc_bid']>=r['reserve'])==sold:break
            self.seed(rid,5);receipt=self.cmd('market_consign',{'resource_id':rid});aid=receipt.result['consignment_id'];self.assertEqual(self.read().domains['inventory']['holdings'][rid],4);self.time(r['end_ms']);before=self.read();q=self.q('market_consignment_claim',{'consignment_id':aid});receipt=self.execute(q);after=self.read()
            self.assertEqual(after.domains['inventory']['holdings'][rid],4 if sold else 5);self.assertEqual(after.domains['inventory']['holdings']['coins']-before.domains['inventory']['holdings']['coins'],r['npc_bid']*900//1000 if sold else 0);self.assertEqual(receipt,self.execute(q))
    def test_consignment_protection_limit_and_failure_atomic(self):
        self.unlock();rid='thorn_king_core';self.seed(rid,5);self.cmd('material_reserve',{'resource_id':rid,'quantity':5});before=self.read()
        with self.assertRaises(ValidationError):self.cmd('market_consign',{'resource_id':rid})
        self.assertEqual(before,self.read());self.cmd('material_reserve',{'resource_id':rid,'quantity':0})
        for _ in range(3):self.cmd('market_consign',{'resource_id':rid})
        before=self.read()
        with self.assertRaises(ValidationError):self.cmd('market_consign',{'resource_id':rid})
        self.assertEqual(before,self.read())
    def test_boss_never_auto_converted_and_other_prices_correct(self):
        cfg=settings(self.r)['items'];s=self.read();p={**s.domains['automation'],'material_overflow':True};amounts={'thorn_king_core':1,'thorn_boar_bone':3};stock={'thorn_king_core':9999,'thorn_boar_bone':9999};kept,converted=overflow.rewards(p,stock,self.r,amounts);self.assertEqual(kept['thorn_king_core'],1);self.assertNotIn('thorn_king_core',converted);self.assertEqual(kept['coins'],3*cfg['thorn_boar_bone']['sell_coins'])
    def test_all_spreads_orders_and_crafting_prevent_free_cycles(self):
        cfg=settings(self.r);values=cfg['items']
        for rid,r in values.items():self.assertGreater(r['buy_coins']*800,r['sell_coins']*1200)
        for rid,r in values.items():self.assertGreater(r['buy_coins']*800,r['value_coins']*cfg['order_reward_permille']*1200//1000)
        for r in self.view()['economy']['crafting']:
            cost=craft_inputs(self.r,r['equipment_id']);minimum=sum(n*(1 if rid=='coins' else values[rid]['buy_coins']*.8) for rid,n in cost.items());self.assertLess(items.sale_price(self.r,r['equipment_id']),minimum)

    def test_escrow_commit_faults_leave_money_and_materials_unchanged(self):
        self.unlock();self.seed('thorn_king_core',5);r=commerce.auction_offers(self.read(),self.r)[0]
        for name,p in [('market_bid',{'auction_id':r['auction_id'],'bid':r['npc_bid']+1}),('market_consign',{'resource_id':'thorn_king_core'})]:
            before=self.read()
            with patch.object(SQLiteSave,'commit',side_effect=RuntimeError('fixture')):
                with self.assertRaises(RuntimeError):self.cmd(name,p)
            self.assertEqual(before,self.read())
        self.cmd('market_bid',{'auction_id':r['auction_id'],'bid':r['npc_bid']+1});self.time(r['end_ms']);before=self.read()
        with patch.object(SQLiteSave,'commit',side_effect=RuntimeError('fixture')):
            with self.assertRaises(RuntimeError):self.cmd('market_auction_claim',{'auction_id':r['auction_id']})
        self.assertEqual(before,self.read())

    def test_stale_order_quote_and_forged_payload_rejected(self):
        r=self.view()['sect_services']['orders'][0];before=self.read()
        with self.assertRaises(ValidationError):self.cmd('market_order',{'order_id':r['order_id'],'market_day':r['market_day'],'quote_id':'old-or-forged'})
        self.assertEqual(before,self.read())
        for p in ({'auction_id':'forged','bid':100},{'auction_id':'forged','bid':True}):
            with self.assertRaises(ValidationError):self.cmd('market_bid',p)
            self.assertEqual(before,self.read())

    def test_unsold_return_waits_for_space_and_pause_freezes_time(self):
        self.unlock();rid='thorn_king_core'
        start=market.day(self.read())
        for d in range(start,start+100):
            self.time(d*120000);r=commerce.consignment_quote(self.read(),self.r,rid)
            if r['npc_bid']<r['reserve']:break
        self.seed(rid,1);aid=self.cmd('market_consign',{'resource_id':rid}).result['consignment_id'];self.cmd('world_pause',{});before=self.read();self.clock.advance(1000000)
        with self.assertRaises(ValidationError):self.drain()
        self.assertEqual(before,self.read());self.cmd('world_resume',{});self.clock.advance(max(0,r['end_ms']-self.read().time['sim_time_ms']));self.drain();self.fill();before=self.read()
        with self.assertRaises(ValidationError):self.cmd('market_consignment_claim',{'consignment_id':aid})
        self.assertEqual(before,self.read());self.seed('stone',self.read().domains['inventory']['holdings']['stone']-1-reserved(self.read(),self.r));self.cmd('market_consignment_claim',{'consignment_id':aid});self.assertEqual(self.read().domains['inventory']['holdings'][rid],1)

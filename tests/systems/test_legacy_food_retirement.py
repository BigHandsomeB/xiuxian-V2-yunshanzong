"""Current rice shop, atomic legacy stock projection/conversion, historical definitions."""
import unittest
from dataclasses import replace
from uuid import uuid4
from src.application.ecology import EcologyApplication
from src.application.memory import Command
from src.application.settlement import SettlementRequest
from src.core.save.sqlite import SQLiteSave
from src.core.save.codec import StoredReceipt
from src.core.state.envelope import thaw_json
from src.data.dungeons.definitions import load_dungeons
from src.data.economy.market import settings
from src.systems.sect import market
from src.systems.inventory import holdings
from tests.systems import test_ecology as fixtures


class LegacyFoodRetirementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):fixtures.EcologyTests.setUpClass.__func__(cls)
    def setUp(self):fixtures.EcologyTests.setUp(self)
    def app(self,store):return EcologyApplication(store,self.registry,self.clock)
    def read(self):
        with SQLiteSave(self.path,allowed_root=self.root) as store:return self.app(store).query(self.sid)
    def fixture(self,change):
        with SQLiteSave(self.path,allowed_root=self.root) as store:
            with store.transaction():
                app=self.app(store);before=app.query(self.sid);after=replace(change(before),revision=before.revision+1)
                app.foundation.validate_state(after)
                q=Command(self.sid,before.generation,before.revision,str(uuid4()),'test_fixture',{})
                store.commit(before,after,StoredReceipt(self.sid,before.generation,q.request_id,q.digest(),after.revision,'command',{}))
        return self.read()
    def old_stock(self):
        return self.fixture(lambda s:replace(s,domains={**s.domains,'inventory':{**s.domains['inventory'],'holdings':{**s.domains['inventory']['holdings'],'food':7}}}))
    def test_daily_selection_price_and_stock_identity_preserved(self):
        state=self.read();old=load_dungeons(management=True,cold_jade=True)
        self.assertIn('food',settings(old)['items']);self.assertNotIn('meal_qingling_rice',settings(old)['items'])
        self.assertNotIn('food',market.eligible(state,self.registry));self.assertIn('meal_qingling_rice',market.eligible(state,self.registry))
        for day in range(8):
            s=replace(state,time={**state.time,'sim_time_ms':day*state.time['day_length_ms']})
            expected=tuple('meal_qingling_rice' if k=='food' else k for k in market.current_offers(s,old))
            self.assertEqual(market.current_offers(s,self.registry),expected)
            self.assertEqual(market.price(self.registry,self.sid,day,'meal_qingling_rice'),market.price(old,self.sid,day,'food'))
            self.assertEqual(market.stock_total(self.registry,self.sid,day,'meal_qingling_rice'),market.stock_total(old,self.sid,day,'food'))
    def test_read_only_projection_then_command_conversion_and_replay(self):
        before=self.old_stock();old_rice=before.domains['inventory']['holdings'].get('meal_qingling_rice',0)
        with SQLiteSave(self.path,allowed_root=self.root) as store:
            app=self.app(store);view=app.view(self.sid)
            self.assertNotIn('food',view['inventory']);self.assertEqual(view['inventory']['meal_qingling_rice']['quantity'],old_rice+7)
            self.assertEqual(app.query(self.sid),before)
            row=view['sect_services']['materials'][0]
            q=Command(self.sid,before.generation,before.revision,str(uuid4()),'material_reserve',{'resource_id':row['resource_id'],'quantity':3})
            receipt=app.execute(q);after=app.query(self.sid)
            self.assertNotIn('food',after.domains['inventory']['holdings']);self.assertEqual(after.domains['inventory']['holdings']['meal_qingling_rice'],old_rice+7)
            self.assertEqual(holdings.stock_size(before.domains['inventory'],self.registry),holdings.stock_size(after.domains['inventory'],self.registry))
            self.assertEqual(app.execute(q),receipt);self.assertEqual(app.query(self.sid),after)
    def test_settlement_converts_once_without_time_jump(self):
        before=self.old_stock();rice=before.domains['inventory']['holdings']['meal_qingling_rice']
        q=SettlementRequest(self.sid,before.generation,before.revision,str(uuid4()),32)
        with SQLiteSave(self.path,allowed_root=self.root) as store:
            app=self.app(store);receipt=app.settle(q);after=app.query(self.sid)
            self.assertNotIn('food',after.domains['inventory']['holdings']);self.assertEqual(after.domains['inventory']['holdings']['meal_qingling_rice'],rice+7)
            self.assertEqual(after.time['sim_time_ms'],before.time['sim_time_ms']);self.assertEqual(app.settle(q),receipt)
    def test_old_daily_purchases_count_toward_rice_limit(self):
        state=self.read();part=thaw_json(state.domains['sect_management']);ledger=part.setdefault('commerce',{'day':market.day(state),'orders':{},'bids':{},'consignments':{},'sequence':0,'history':[]})
        ledger.update(day=market.day(state),purchases={'food':7,'meal_qingling_rice':2})
        state=replace(state,domains={**state.domains,'sect_management':part})
        self.assertEqual(market.stock_remaining(state,self.registry,'meal_qingling_rice'),21)
        with SQLiteSave(self.path,allowed_root=self.root) as store:self.app(store).foundation.validate_state(state)
    def test_invalid_command_rolls_back_conversion(self):
        before=self.old_stock();row=None
        with SQLiteSave(self.path,allowed_root=self.root) as store:
            app=self.app(store);row=app.view(self.sid)['sect_services']['market']['offers'][0]
            q=Command(self.sid,before.generation,before.revision,str(uuid4()),'market_buy',{'resource_id':row['resource_id'],'quantity':1,'market_day':row['market_day'],'price_milli':row['price_milli']+1})
            from src.core.validation import ValidationError
            with self.assertRaises(ValidationError):app.execute(q)
            self.assertEqual(app.query(self.sid),before)

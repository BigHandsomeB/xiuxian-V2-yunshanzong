"""Shipping registry and disposable SQLite exercise stock targets and saved-time events."""
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4
import unittest

from src.application.danding import initial_slice
from src.application.ecology import EcologyApplication
from src.application.market_restock import policy
from src.application.memory import Command
from src.application.settlement import SettlementRequest
from src.core.save.codec import StoredReceipt
from src.core.save.sqlite import SQLiteSave, V2_ROOT
from src.core.state.envelope import thaw_json
from src.core.time.model import Continuation
from src.core.validation import ValidationError
from src.data.content_loader import load_current
from src.data.economy.market import settings
from src.systems.sect import market
from src.systems.inventory import holdings
from src.application.sect import capacity_source
from tests.fixtures.time import ManualClock


class RestockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = load_current()

    def setUp(self):
        temp = TemporaryDirectory(dir=V2_ROOT/'tests');self.addCleanup(temp.cleanup)
        self.root = Path(temp.name);self.path = self.root/'test.sqlite3';self.clock = ManualClock()
        state = initial_slice(self.registry, last_settled_at_ms=self.clock.now_ms())
        self.sid = state.save_id
        disciples = thaw_json(state.domains['disciples']);disciples['assignments'] = {}
        auto = thaw_json(state.domains['automation']);auto['production'] = {}
        state = replace(state, domains={**state.domains, 'disciples': disciples,
                        'automation': auto, 'inventory': {'holdings': {'coins': 100000}}})
        with SQLiteSave.initialize(self.path, allowed_root=self.root) as store:
            EcologyApplication(store, self.registry, self.clock).create(state)
        self.rid = market.current_offers(self.read(), self.registry)[0]

    @property
    def bid(self):
        return next(bid for bid, row in self.read().domains['sect']['buildings'].items() if row['definition_id']=='trading')

    @contextmanager
    def app(self):
        with SQLiteSave(self.path, allowed_root=self.root) as store:
            yield EcologyApplication(store, self.registry, self.clock)

    def read(self):
        with self.app() as app:return app.query(self.sid)

    def view(self):
        with self.app() as app:return app.view(self.sid)

    def request(self, name, payload):
        state = self.read()
        return Command(self.sid, state.generation, state.revision, str(uuid4()), name, payload)

    def command(self, name, payload, request=None):
        with self.app() as app:return app.execute(request or self.request(name, payload))

    def fixture(self, change):
        with self.app() as app:
            with app.store.transaction():
                before = app.query(self.sid);after = replace(change(before), revision=before.revision+1)
                app.foundation.validate_state(after)
                app.store.commit(before, after, StoredReceipt(self.sid, before.generation, str(uuid4()), '0'*64, after.revision, 'command', {}))

    def settle(self, ms=0, max_events=1000, request=None):
        self.clock.advance(ms)
        for _ in range(100):
            state = self.read()
            q = request or SettlementRequest(self.sid, state.generation, state.revision, str(uuid4()), max_events,
                    Continuation.for_state(state) if state.time['pending'] else None)
            with self.app() as app:result = app.settle(q)
            request = None
            if not self.read().time['pending']:return result
        self.fail('bounded settlement failed to drain')

    def configure(self, target=10, rid=None):
        return self.command('market_restock_set', {'resource_id': rid or self.rid, 'target': target})

    def assign(self):
        self.command('work_assign', {'building_id': self.bid, 'count': 1})

    def test_old_save_reads_pure_and_no_policy_created(self):
        before = self.read();view = self.view()['sect_services']['restock']
        self.assertEqual(view['rows'], ());self.assertNotIn('restock', before.domains['sect_management'])
        self.assertEqual({r['resource_id'] for r in view['eligible']}, set(market.eligible(before, self.registry)))
        self.settle(1000);self.assertNotIn('restock', self.read().domains['sect_management'])
        self.assertEqual(before.domains['inventory'], self.read().domains['inventory'])

    def test_configure_requires_worker_then_fills_exact_gap_and_replays(self):
        request = self.request('market_restock_set', {'resource_id': self.rid, 'target': 10})
        receipt = self.command('', {}, request);self.settle(1000)
        self.assertNotIn(self.rid, self.read().domains['inventory']['holdings'])
        self.assertEqual(self.view()['sect_services']['restock']['rows'][0]['reason'], '等待分配万宝楼弟子')
        self.assign();before = self.read();self.settle()
        after = self.read();n = min(10, market.stock_remaining(before, self.registry, self.rid))
        self.assertEqual(after.domains['inventory']['holdings'][self.rid], n)
        cost = market.price(self.registry, self.sid, market.day(before), self.rid)['buy_price_milli']
        self.assertEqual(before.domains['inventory']['holdings']['coins']-after.domains['inventory']['holdings']['coins'], (n*cost+999)//1000)
        self.assertEqual(after.domains['sect_management']['commerce']['purchases'][self.rid], n)
        self.assertEqual(self.command('', {}, request), receipt);self.assertEqual(self.read(), after)
        self.settle();self.assertEqual(self.read().domains['inventory'], after.domains['inventory'])

    def test_consumption_replenishes_and_unassign_stops(self):
        self.rid = next(rid for rid in market.current_offers(self.read(), self.registry) if market.stock_remaining(self.read(), self.registry,rid)>=20)
        self.configure();self.assign();self.settle()
        def consume(s):
            stock = thaw_json(s.domains['inventory']);stock['holdings'][self.rid] -= 4
            return replace(s, domains={**s.domains, 'inventory': stock})
        self.fixture(consume);self.settle();self.assertEqual(self.read().domains['inventory']['holdings'][self.rid], 10)
        self.command('work_unassign', {'building_id': self.bid});self.fixture(consume);before = self.read()
        self.settle(120000);self.assertEqual(self.read().domains['inventory'], before.domains['inventory'])
        self.assertIsNone(policy(self.read())['wake'])

    def test_manual_and_automatic_share_limit(self):
        self.configure(10000);self.assign();self.settle();before = self.read()
        self.assertEqual(market.stock_remaining(before, self.registry, self.rid), 0)
        with self.assertRaises(ValidationError):
            self.command('market_buy', {'resource_id': self.rid, 'quantity': 1, 'market_day': market.day(before),
                    'price_milli': market.price(self.registry, self.sid, market.day(before), self.rid)['buy_price_milli']})
        self.assertEqual(before, self.read())

    def test_manual_purchase_counts_before_automatic_gap(self):
        self.rid = next(rid for rid in market.current_offers(self.read(), self.registry) if market.stock_remaining(self.read(), self.registry,rid)>=10)
        state = self.read();price = market.price(self.registry, self.sid, market.day(state), self.rid)['buy_price_milli']
        self.command('market_buy', {'resource_id':self.rid,'quantity':3,'market_day':market.day(state),'price_milli':price})
        self.configure();self.assign();self.settle()
        self.assertEqual(self.read().domains['inventory']['holdings'][self.rid], 10)
        self.assertEqual(policy(self.read())['log'][0]['quantity'], 7)

    def test_unlisted_material_waits_until_saved_day_boundary(self):
        self.rid = next(rid for rid in market.eligible(self.read(), self.registry) if rid not in market.current_offers(self.read(), self.registry))
        self.configure(1);self.assign();self.settle()
        self.assertEqual(self.view()['sect_services']['restock']['rows'][0]['reason'], '等待材料上架')
        state = self.read();start = market.day(state)
        target_day = next(day for day in range(start+1,start+1000) if self.rid in market.offers(self.registry,self.sid,day,market.eligible(state,self.registry)))
        self.settle(target_day*state.time['day_length_ms'], max_events=1)
        self.assertEqual(self.read().domains['inventory']['holdings'][self.rid], 1)
        self.assertEqual(policy(self.read())['log'][0]['sim_ms'], target_day*state.time['day_length_ms'])

    def test_partial_funds_and_full_warehouse(self):
        self.rid = next(rid for rid in market.current_offers(self.read(), self.registry) if market.stock_remaining(self.read(), self.registry,rid)>=20)
        price = market.price(self.registry,self.sid,market.day(self.read()),self.rid)['buy_price_milli']
        coins = (price*3+999)//1000
        self.fixture(lambda s:replace(s, domains={**s.domains,'inventory':{'holdings':{'coins':coins}}}))
        self.configure();self.assign();self.settle();state = self.read()
        self.assertEqual(state.domains['inventory']['holdings'][self.rid], coins*1000//price)
        self.assertEqual(self.view()['sect_services']['restock']['rows'][0]['reason'], '灵钱不足')
        def fill(s):
            stock = thaw_json(s.domains['inventory']);stock['holdings']['coins'] = 100000
            free = capacity_source(s,self.registry)['effective']-holdings.stock_size(stock,self.registry)
            stock['holdings']['stone'] = stock['holdings'].get('stone',0)+free
            return replace(s,domains={**s.domains,'inventory':stock})
        self.fixture(fill);before = self.read();self.settle(120000)
        self.assertEqual(before.domains['inventory'], self.read().domains['inventory'])

    def test_pause_configuration_resume_and_delete(self):
        self.configure();self.assign();self.command('world_pause', {});self.configure()
        before = self.read();self.view();self.assertEqual(self.read(), before)
        self.clock.advance(3600000)
        with self.assertRaises(ValidationError):self.settle()
        self.assertEqual(self.read(), before)
        self.command('world_resume', {});self.settle()
        self.assertGreater(self.read().domains['inventory']['holdings'].get(self.rid,0), 0)
        self.command('market_restock_delete', {'resource_id': self.rid})
        after = self.read();self.assertEqual(dict(policy(after)['targets']), {});self.assertIsNone(policy(after)['wake'])

    def test_rejects_locked_invalid_and_duplicate_rows_edit_in_place(self):
        locked = next(rid for rid in settings(self.registry)['items'] if rid not in market.eligible(self.read(),self.registry))
        for payload in [{'resource_id':locked,'target':1},{'resource_id':'coins','target':1}]+[
                {'resource_id':self.rid,'target':value} for value in [True,0,-1,10001,1.5,'3']]:
            before = self.read()
            with self.assertRaises(ValidationError):self.command('market_restock_set', payload)
            self.assertEqual(before,self.read())
        self.configure(10);self.configure(20)
        self.assertEqual(dict(policy(self.read())['targets']), {self.rid:20})

    def test_post_write_failure_rolls_back_all_purchase_state(self):
        self.configure();self.assign();before = self.read();commit = SQLiteSave.commit
        def fail(store,*args):
            commit(store,*args);raise RuntimeError('after SQL write')
        with patch.object(SQLiteSave,'commit',fail):
            with self.assertRaisesRegex(RuntimeError,'SQL'):self.settle()
        self.assertEqual(self.read(), before)
        self.settle();self.assertGreater(self.read().domains['inventory']['holdings'].get(self.rid,0),0)

    def test_settlement_receipt_replay_does_not_repurchase(self):
        self.configure();self.assign();state = self.read()
        q = SettlementRequest(self.sid,state.generation,state.revision,str(uuid4()),1000,None)
        with self.app() as app:first = app.settle(q)
        after = self.read()
        with self.app() as app:self.assertEqual(app.settle(q),first)
        self.assertEqual(self.read(),after)

    def test_hour_offline_matches_day_segments(self):
        for rid in market.eligible(self.read(),self.registry)[:6]:self.configure(30,rid)
        self.assign();start = self.read();other = self.root/'offline.sqlite3'
        with SQLiteSave.initialize(other,allowed_root=self.root) as store:
            EcologyApplication(store,self.registry,self.clock).create(start)
        online = self.path
        for _ in range(30):self.settle(120000)
        expected = self.read();self.path = other
        self.settle(max_events=1);actual = self.read();self.path = online
        self.assertEqual(actual.domains['inventory'],expected.domains['inventory'])
        self.assertEqual(actual.domains['sect_management'],expected.domains['sect_management'])
        self.assertEqual(actual.time['sim_time_ms'],expected.time['sim_time_ms'])
        self.assertLessEqual(len(policy(actual)['log']),20)

    def test_warehouse_partial_purchase_preserves_reserved_outputs(self):
        self.configure(10);self.assign()
        def fill(s):
            capacity=capacity_source(s,self.registry)['effective']
            return replace(s,domains={**s.domains,'inventory':{'holdings':{'coins':100000,'stone':capacity-7}}})
        self.fixture(fill)
        with patch('src.application.market_restock.reserved',return_value=5):
            self.settle()
        self.assertEqual(self.read().domains['inventory']['holdings'][self.rid],min(2,market.stock_total(self.registry,self.sid,0,self.rid)))

    def test_multiple_targets_have_stable_priority_and_no_extra_workers(self):
        ids=sorted(market.current_offers(self.read(),self.registry))[:2]
        for rid in reversed(ids):self.configure(10,rid)
        self.assign()
        price=market.price(self.registry,self.sid,0,ids[0])['buy_price_milli']
        self.fixture(lambda s:replace(s,domains={**s.domains,'inventory':{'holdings':{'coins':(price+999)//1000}}}))
        self.settle()
        self.assertEqual(self.read().domains['inventory']['holdings'].get(ids[0]),1)
        self.assertEqual(self.view()['sect_services']['restock']['workers'],1)


class RestockHTTPTests(unittest.TestCase):
    setUpClass=classmethod(RestockTests.setUpClass.__func__)
    bid=RestockTests.bid
    for method in ('app','read','view','request','command','fixture','settle','configure','assign'):
        locals()[method]=getattr(RestockTests,method)

    def setUp(self):
        from src.transport.danding import create_app
        from werkzeug.test import Client
        from werkzeug.wrappers import Response
        RestockTests.setUp(self)
        app=create_app(self.app,self.sid,lambda view:{},lambda _:None,
                'isolated-restock-test-token-123',secure=False,
                ui_root=Path('src/ui/pages/game').resolve(),cookie_path='/')
        app.testing=True;self.client=Client(app,Response)
        self.client.post('/login',data={'token':'isolated-restock-test-token-123'})

    def body(self,name,payload):
        state=self.read()
        return {'protocol_version':1,'save_id':self.sid,'generation':state.generation,
                'expected_revision':state.revision,'request_id':str(uuid4()),
                'command':{'name':name,'version':1,'payload':payload}}

    def post(self,body):
        return self.client.post('/api/command',json=body,
                headers={'X-CSRF-Token':self.client.get('/api/view').json['csrf']})

    def test_http_configure_workforce_purchase_and_replay(self):
        before=self.read();response=self.client.get('/api/view')
        self.assertEqual(response.status_code,200);self.assertEqual(before,self.read())
        body=self.body('market_restock_set',{'resource_id':self.rid,'target':10})
        first=self.post(body);self.assertEqual(first.status_code,200,first.json)
        self.assertEqual(self.post(body).json,first.json)
        self.assertEqual(self.post(self.body('work_assign',{'building_id':self.bid,'count':1})).status_code,200)
        self.settle();view=self.client.get('/api/view').json['view']
        self.assertGreater(view['sect_services']['restock']['rows'][0]['quantity'],0)
        self.assertEqual(self.post(self.body('market_restock_delete',{'resource_id':self.rid})).status_code,200)
        self.assertEqual(self.view()['sect_services']['restock']['rows'],())

    def test_http_invalid_locked_csrf_and_stale_are_atomic(self):
        before=self.read();body=self.body('market_restock_set',{'resource_id':self.rid,'target':True})
        self.assertEqual(self.post(body).status_code,422);self.assertEqual(self.read(),before)
        body=self.body('market_restock_set',{'resource_id':self.rid,'target':10})
        self.assertEqual(self.client.post('/api/command',json=body).status_code,403)
        self.assertEqual(self.read(),before)
        self.configure();after=self.read()
        self.assertEqual(self.post(body).status_code,409);self.assertEqual(self.read(),after)

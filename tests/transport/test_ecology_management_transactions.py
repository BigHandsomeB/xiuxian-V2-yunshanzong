"""Inherited management commands use exactly one write transaction in shipping Ecology."""
import unittest
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.test import Client
from werkzeug.wrappers import Response
from src.core.save.sqlite import SQLiteSave
from src.application.ecology import EcologyApplication
from src.transport.danding import create_app
from tests.systems import test_ecology as ecology_fixtures


class EcologyManagementTransactionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):ecology_fixtures.EcologyTests.setUpClass.__func__(cls)
    def setUp(self):
        ecology_fixtures.EcologyTests.setUp(self)
        @contextmanager
        def factory():
            with SQLiteSave(self.path,allowed_root=self.root) as store:yield EcologyApplication(store,self.registry,self.clock)
        self.factory=factory
        http=create_app(factory,self.sid,lambda view:{},lambda _:None,'isolated-transaction-test-token-123',secure=False,ui_root=Path('src/ui/pages/game').resolve(),cookie_path='/game/');http.testing=True
        self.client=Client(DispatcherMiddleware(lambda e,s:[],{'/game':http}),Response);self.client.post('/game/login',data={'token':'isolated-transaction-test-token-123'})
    def read(self):
        with self.factory() as app:return app.query(self.sid)
    def view(self):return self.client.get('/game/api/view').json
    def body(self,name,payload):
        v=self.view();return {'protocol_version':1,'save_id':self.sid,'generation':v['generation'],'expected_revision':v['revision'],'request_id':str(uuid4()),'command':{'name':name,'version':1,'payload':payload}}
    def post(self,body):return self.client.post('/game/api/command',json=body,headers={'X-CSRF-Token':self.view()['csrf']})
    def purchase(self):
        r=next(row for row in self.view()['view']['sect_services']['market']['offers'] if row['max_quantity']>0)
        return self.body('market_buy',{'resource_id':r['resource_id'],'quantity':1,'market_day':r['market_day'],'price_milli':r['price_milli']})
    def test_purchase_is_one_transaction_and_replay_does_not_double_charge(self):
        q=self.purchase();before=self.read();transactions=[];original=SQLiteSave.transaction
        @contextmanager
        def counted(store):
            transactions.append(store.path)
            with original(store):yield store
        with patch.object(SQLiteSave,'transaction',counted):response=self.post(q)
        self.assertEqual(response.status_code,200,response.json);self.assertEqual(len(transactions),1)
        after=self.read();p=q['command']['payload'];cost=(p['price_milli']+999)//1000
        self.assertEqual(after.domains['inventory']['holdings']['coins'],before.domains['inventory']['holdings']['coins']-cost)
        self.assertEqual(after.domains['inventory']['holdings'][p['resource_id']],before.domains['inventory']['holdings'].get(p['resource_id'],0)+1)
        self.assertEqual(after.domains['sect_management']['commerce']['purchases'][p['resource_id']],1)
        self.assertEqual(self.post(q).status_code,200);self.assertEqual(self.read(),after)
    def test_paused_shipping_gate_remains_and_executed_receipt_replays(self):
        q=self.purchase();self.assertEqual(self.post(q).status_code,200)
        self.assertEqual(self.post(self.body('world_pause',{})).status_code,200);paused=self.read()
        self.assertEqual(self.post(q).status_code,200);self.assertEqual(self.read(),paused)
        self.assertEqual(self.post(self.purchase()).status_code,422);self.assertEqual(self.read(),paused)
    def test_invalid_price_is_domain_error_without_persistence_failure(self):
        q=self.purchase();q['command']['payload']['price_milli']=1;before=self.read()
        self.assertEqual(self.post(q).status_code,422);self.assertEqual(self.read(),before)
    def test_other_inherited_command_uses_parent_transaction(self):
        row=self.view()['view']['sect_services']['materials'][0]
        q=self.body('material_reserve',{'resource_id':row['resource_id'],'quantity':3})
        self.assertEqual(self.post(q).status_code,200);after=self.read()
        self.assertEqual(after.domains['sect_management']['material_reserves'][row['resource_id']],3)
        self.assertEqual(self.post(q).status_code,200);self.assertEqual(self.read(),after)

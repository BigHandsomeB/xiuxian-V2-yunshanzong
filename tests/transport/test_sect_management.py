"""Real private HTTP lanes for management commands, CSRF, replay and pause."""
import unittest
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.test import Client
from werkzeug.wrappers import Response
from tests.systems import test_sect_management as fixtures
from src.core.save.sqlite import SQLiteSave
from src.transport.danding import create_app

class ManagementHTTPTests(unittest.TestCase):
 for name in ('app','read','q','cmd','execute'):locals()[name]=getattr(fixtures.ManagementTests,name)
 def setUp(self):
  fixtures.ManagementTests.setUp(self)
  @contextmanager
  def factory():
   with SQLiteSave(self.db,allowed_root=self.root) as store:yield self.app(store)
  http=create_app(factory,self.sid,lambda v:{},lambda _:None,'isolated-management-http-token-123',secure=False,ui_root=Path('src/ui/pages/game').resolve(),cookie_path='/game/');http.testing=True;self.client=Client(DispatcherMiddleware(lambda e,s:(s('404 Not Found',[]),[])[1],{'/game':http}),Response);self.client.post('/game/login',data={'token':'isolated-management-http-token-123'})
 def body(self,name,payload):
  v=self.client.get('/game/api/view').json;return {'protocol_version':1,'save_id':self.sid,'generation':v['generation'],'expected_revision':v['revision'],'request_id':str(uuid4()),'command':{'name':name,'version':1,'payload':payload}}
 def post(self,body):return self.client.post('/game/api/command',json=body,headers={'X-CSRF-Token':self.client.get('/game/api/view').json['csrf']})
 def test_real_recruit_read_and_replay(self):
  before=self.read();r=self.client.get('/game/api/view');self.assertEqual(r.status_code,200);self.assertIn('sect_services',r.json['view']);self.assertEqual(before,self.read());body=self.body('sect_recruit',{'group_id':next(iter(before.domains['disciples']['groups'])),'count':1});self.assertEqual(self.post(body).status_code,200);after=self.read();self.assertEqual(self.post(body).status_code,200);self.assertEqual(after,self.read())
 def test_paused_supply_rejected_safe_error_and_old_replay(self):
  body=self.body('sect_supply',{'enabled':True,'reserve':5});self.assertEqual(self.post(body).status_code,200);self.cmd('world_pause',{});before=self.read();self.assertEqual(self.post(body).status_code,200);self.assertEqual(before,self.read());r=self.post(self.body('sect_supply',{'enabled':False,'reserve':5}));self.assertEqual(r.status_code,422);self.assertIn('世界已暂停',r.json['error']);self.assertEqual(before,self.read())
 def test_csrf_and_upgrade_not_public_command(self):
  before=self.read();body=self.body('sect_supply',{'enabled':True,'reserve':5});self.assertEqual(self.client.post('/game/api/command',json=body).status_code,403);r=self.post(self.body('sect_management_content_upgrade',{}));self.assertIn(r.status_code,(400,422));self.assertEqual(before,self.read())

 def test_daily_market_public_lane_replay_and_pause(self):
  row=self.client.get('/game/api/view').json['view']['sect_services']['market']['offers'][0];payload={'resource_id':row['resource_id'],'quantity':2,'market_day':row['market_day'],'price_milli':row['price_milli']}
  body=self.body('market_buy',payload);self.assertEqual(self.post(body).status_code,200);after=self.read();self.assertEqual(self.post(body).status_code,200);self.assertEqual(after,self.read());self.cmd('world_pause',{});before=self.read();self.assertEqual(self.post(self.body('market_buy',payload)).status_code,422);self.assertEqual(before,self.read())
 def test_daily_market_forged_quote_and_legacy_global_buy_rejected(self):
  row=self.client.get('/game/api/view').json['view']['sect_services']['market']['offers'][0];before=self.read()
  bad={'resource_id':row['resource_id'],'quantity':1,'market_day':row['market_day'],'price_milli':1}
  self.assertEqual(self.post(self.body('market_buy',bad)).status_code,422);self.assertEqual(before,self.read())
  self.assertEqual(self.post(self.body('sect_stone_buy',{'resource_id':'spirit_stone_immortal','quantity':1})).status_code,422);self.assertEqual(before,self.read())

 def test_commerce_order_http_quote_and_replay(self):
  from dataclasses import replace
  r=self.client.get('/game/api/view').json['view']['sect_services']['orders'][0]
  fixtures.ManagementTests.fixture(self,lambda s:replace(s,domains={**s.domains,'inventory':{**s.domains['inventory'],'holdings':{**s.domains['inventory']['holdings'],r['resource_id']:r['quantity']+10}}}))
  p={'order_id':r['order_id'],'market_day':r['market_day'],'quote_id':r['quote_id']}
  before=self.read();self.assertEqual(self.post(self.body('market_order',{**p,'quote_id':'stale'})).status_code,422);self.assertEqual(before,self.read())
  body=self.body('market_order',p);self.assertEqual(self.post(body).status_code,200);after=self.read();self.assertEqual(self.post(body).status_code,200);self.assertEqual(after,self.read());self.assertEqual(self.post(self.body('market_order',p)).status_code,422)

 def test_commerce_auction_and_consignment_http_lanes(self):
  from dataclasses import replace
  from src.core.state.envelope import thaw_json
  from src.systems.sect import commerce
  def unlock(s):
   sect=thaw_json(s.domains['sect'])
   for row in sect['buildings'].values():row['level']=max(5,row['level'])
   inventory=thaw_json(s.domains['inventory']);inventory['holdings']['thorn_king_core']=5
   return replace(s,domains={**s.domains,'sect':sect,'inventory':inventory,'dungeon':{**s.domains['dungeon'],'cleared_floor':100}})
  fixtures.ManagementTests.fixture(self,unlock);r=commerce.auction_offers(self.read(),self.r)[0]
  body=self.body('market_bid',{'auction_id':r['auction_id'],'bid':r['npc_bid']+1});self.assertEqual(self.post(body).status_code,200);after=self.read();self.assertEqual(self.post(body).status_code,200);self.assertEqual(after,self.read())
  body=self.body('market_consign',{'resource_id':'thorn_king_core'});self.assertEqual(self.post(body).status_code,200);aid=next(iter(self.read().domains['sect_management']['commerce']['consignments']))
  fixtures.ManagementTests.fixture(self,lambda s:replace(s,time={**s.time,'sim_time_ms':r['end_ms']}))
  self.assertEqual(self.post(self.body('market_auction_claim',{'auction_id':r['auction_id']})).status_code,200)
  body=self.body('market_consignment_claim',{'consignment_id':aid});self.assertEqual(self.post(body).status_code,200);after=self.read();self.assertEqual(self.post(body).status_code,200);self.assertEqual(after,self.read())

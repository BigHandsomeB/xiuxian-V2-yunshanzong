"""Existing private HTTP protocol, CSRF, safe errors and genuine economy state."""
import unittest
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.test import Client
from werkzeug.wrappers import Response
from pathlib import Path
from contextlib import contextmanager
from uuid import uuid4
from tests.systems.test_economy import EconomyFixture
from src.application.economy import EconomyApplication
from src.core.save.sqlite import SQLiteSave
from src.transport.danding import create_app
from src.rendering.game import present,manifest
from src.rendering.game_runtime import GameRuntimeAssets

class EconomyHTTPTests(EconomyFixture,unittest.TestCase):
 def setUp(self):
  super().setUp();assets=GameRuntimeAssets(self.root/'assets');self.http=create_app(self.application,self.save,lambda v:present(v,assets),assets.file,'isolated-phase16-transport-token-123',secure=False,ui_root=Path('src/ui/pages/game').resolve(),cookie_path='/game/',asset_view=lambda:manifest(assets));self.http.testing=True;self.client=Client(DispatcherMiddleware(lambda e,s:(s('404 Not Found',[]),[])[1],{'/game':self.http}),Response);self.client.post('/game/login',data={'token':'isolated-phase16-transport-token-123'})
 def body(self,name,payload,request_id=None):
  v=self.client.get('/game/api/view').json;return {'protocol_version':1,'save_id':self.save,'generation':v['generation'],'expected_revision':v['revision'],'request_id':request_id or str(uuid4()),'command':{'name':name,'version':1,'payload':payload}}
 def post(self,body):return self.client.post('/game/api/command',json=body,headers={'X-CSRF-Token':self.client.get('/game/api/view').json['csrf']})
 def test_economy_view_and_existing_domains(self):
  r=self.client.get('/game/api/view');self.assertEqual(r.status_code,200);self.assertTrue({'economy','equipment','alchemy','cultivation','combat','world'}<=r.json['view'].keys());self.assertEqual(r.json['view']['equipment']['policy']['mode'],'OFF')
 def test_assignment_and_production_real_command(self):
  self.assertEqual(self.post(self.body('work_assign',{'building_id':self.building('garden'),'worker_id':self.group('ordinary_farm'),'count':1})).status_code,200);r=self.post(self.body('production_start',{'building_id':self.building('garden'),'recipe_id':'herb'}));self.assertEqual(r.status_code,200);self.assertEqual(self.state().domains['production']['jobs'][self.building('garden')]['status'],'WORKING')
 def test_duplicate_and_stale_policy_command(self):
  p={'building_id':self.building('mine'),'policy':{'enabled':True,'recipe_id':'ore','target':12,'reserves':{},'max_consumption':0}};body=self.body('automation_production',p);self.assertEqual(self.post(body).status_code,200);before=self.state();self.assertEqual(self.post(body).status_code,200);self.assertEqual(self.state(),before);body['request_id']=str(uuid4());self.assertEqual(self.post(body).status_code,409)
 def test_pause_error_safe_chinese(self):
  self.command('world_pause');r=self.post(self.body('production_start',{'building_id':self.building('garden'),'recipe_id':'herb'}));self.assertEqual(r.status_code,422);self.assertEqual(r.json['error'],'世界已暂停，请先继续运行')
 def test_invalid_equipment_and_no_external_grants(self):
  before=self.state()
  for name,p in [('equipment_sell',{'instance_id':'missing'}),('inventory_grant',{'amounts':{'coins':9999}}),('production_start',{'building_id':self.building('mine'),'recipe_id':'ore','workers':9})]:
   r=self.post(self.body(name,p));self.assertIn(r.status_code,(400,422));self.assertNotIn('Traceback',r.json['error'])
  self.assertEqual(self.state(),before)
 def test_csrf_rejected(self):
  body=self.body('automation_equipment',{'policy':dict(self.state().domains['automation']['equipment'])});self.assertEqual(self.client.post('/game/api/command',json=body).status_code,403)
 def test_policy_validation_and_catalog_no_gameplay(self):
  self.assertEqual(self.client.get('/game/api/assets').status_code,200);before=self.state();self.assertEqual(self.post(self.body('automation_equipment',{'policy':{'mode':'DROP'}})).status_code,422);self.assertEqual(self.state(),before)
 def test_root_static_and_unchanged_game_assets_routes(self):
  self.assertEqual(self.client.get('/game/').status_code,200)
  for name in ('screens/economy.js','screens/equipment.js','api-client.js'):
   response=self.client.get('/game/static/'+name);self.assertEqual(response.status_code,200);response.close()

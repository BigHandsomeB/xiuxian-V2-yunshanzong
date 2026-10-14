"""Real small HTTP requests process large inventories; auth/CSRF/CAS stay intact."""
import unittest
from contextlib import contextmanager
from src.application.sect_management import ManagementApplication
from src.core.save.sqlite import SQLiteSave
from src.transport.danding import create_app
from tests.systems import test_equipment_bulk as fixtures

class EquipmentBulkHTTPTests(unittest.TestCase):
 def setUp(self):
  f=fixtures.EquipmentBulkTests();f.setUp();f.seed(350,'thorn_fang_blade');self.addCleanup(f.doCleanups);self.f=f
  self.client=create_app(self.application,f.s.save_id,lambda v:{},lambda *args:None,'isolated-fixture-token-000000',secure=False,cookie_path='/').test_client()
  with self.client.session_transaction() as session:session['authenticated']=True;session['csrf']='fixture'
  q=f.command(f.s,'sell');self.body={'protocol_version':1,'save_id':q.save_id,'generation':q.generation,'expected_revision':q.expected_revision,'request_id':q.request_id,'command':{'name':q.name,'version':1,'payload':dict(q.payload)}}
 @contextmanager
 def application(self):
  with SQLiteSave(self.f.path,allowed_root=self.f.root) as store:yield ManagementApplication(store,self.f.registry,self.f.clock)
 def test_small_command_350_inventory_and_idempotent_http_replay(self):
  response=self.client.post('/api/command',json=self.body,headers={'X-CSRF-Token':'fixture'});self.assertEqual(response.status_code,200);self.assertEqual(response.json['receipt']['result']['count'],345)
  replay=self.client.post('/api/command',json=self.body,headers={'X-CSRF-Token':'fixture'});self.assertEqual(replay.json['receipt'],response.json['receipt'])
  with self.application() as game:self.assertEqual(len(game.query(self.f.s.save_id).domains['equipment']['instances']),5)
 def test_csrf_and_command_4k_limit_preserve_all(self):
  self.assertEqual(self.client.post('/api/command',json=self.body).status_code,403)
  self.assertEqual(self.client.post('/api/command',data=' '*4097,content_type='application/json',headers={'X-CSRF-Token':'fixture'}).status_code,413)
  with self.application() as game:self.assertEqual(len(game.query(self.f.s.save_id).domains['equipment']['instances']),350)
 def test_view_enables_bulk_salvage_and_refresh_preserves_protected_equipment(self):
  response=self.client.get('/api/view');self.assertEqual(response.status_code,200)
  preview=response.json['view']['equipment']['bulk'];self.assertTrue(preview['can_process']);self.assertEqual((preview['count'],preview['protected_count']),(345,5))
  self.body['command']['name']='equipment_salvage_all'
  self.body['command']['payload']={'selection_digest':preview['selection_digest']}
  result=self.client.post('/api/command',json=self.body,headers={'X-CSRF-Token':'fixture'})
  self.assertEqual(result.status_code,200,result.json);self.assertEqual(result.json['receipt']['result']['count'],345)
  refreshed=self.client.get('/api/view').json['view']['equipment'];self.assertEqual(len(refreshed['instances']),5);self.assertEqual(refreshed['bulk']['count'],0)
  self.assertTrue(result.json['receipt']['result']['amounts'])

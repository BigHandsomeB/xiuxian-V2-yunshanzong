import unittest
from pathlib import Path
from src.transport.danding import create_app
from src.rendering.game import present
from src.rendering.game_runtime import GameRuntimeAssets
from src.core.state.envelope import thaw_json
from tests.systems import test_cultivation as fixtures
from tests.transport.test_danding import TOKEN
class CultivationHTTPTests(unittest.TestCase):
 setUp_fixture=fixtures.CultivationTests.setUp
 tearDown=fixtures.CultivationTests.tearDown
 application=fixtures.CultivationTests.application
 state_now=fixtures.CultivationTests.state_now
 command=fixtures.CultivationTests.command
 execute=fixtures.CultivationTests.execute
 view=fixtures.CultivationTests.view
 train=fixtures.CultivationTests.train
 full=fixtures.CultivationTests.full
 start=fixtures.CultivationTests.start
 def setUp(self):
  self.setUp_fixture();self.assets=GameRuntimeAssets(self.root/'assets');self.web=create_app(self.application,self.save,lambda v:present(v,self.assets),self.assets.file,TOKEN,secure=False,ui_root=Path('src/ui/pages/game').resolve(),cookie_path='/game/');self.web.config['SESSION_COOKIE_PATH']='/';self.client=self.web.test_client();self.client.post('/login',data={'token':TOKEN});self.csrf=self.client.get('/api/view').json['csrf']
 def body(self,name,payload=None,**extra):
  q=self.command(name,payload,**extra);return {'protocol_version':1,'save_id':q.save_id,'generation':q.generation,'expected_revision':q.expected_revision,'request_id':q.request_id,'command':{'name':q.name,'version':1,'payload':thaw_json(q.payload)}}
 def post(self,q):return self.client.post('/api/command',json=q,headers={'X-CSRF-Token':self.csrf,'Origin':'http://localhost'})
 def test_view_exposes_real_growth_and_fallback(self):
  s=self.state_now();v=self.client.get('/api/view').json;self.assertEqual(v['view']['cultivation']['pill']['quantity'],26);self.assertTrue(v['presentation']['screens']['cultivation']['implemented']);self.assertEqual(self.state_now(),s)
 def test_use_command_and_inventory_query(self):
  self.assertEqual(self.post(self.body('cultivation_train')).status_code,200);v=self.client.get('/api/view').json['view'];self.assertEqual((v['cultivation']['progress'],v['holdings']['pill']['quantity']),(80,25))
 def test_breakthrough_and_delta(self):
  self.full();r=self.post(self.body('cultivation_breakthrough'));self.assertEqual(r.status_code,200);self.assertEqual(r.json['receipt']['result']['stats_after']['attack'],26);self.assertEqual(self.client.get('/api/view').json['view']['cultivation']['realm_name'],'筑基')
 def test_duplicate_train_and_breakthrough_receipts(self):
  q=self.body('cultivation_train');self.assertEqual(self.post(q).json,self.post(q).json)
  for _ in range(22):self.train()
  q=self.body('cultivation_breakthrough');self.assertEqual(self.post(q).json,self.post(q).json)
 def test_stale_revision_conflict(self):
  q=self.body('cultivation_train');old=self.body('cultivation_train');self.assertEqual(self.post(q).status_code,200);self.assertEqual(self.post(old).status_code,409)
 def test_active_battle_safe_chinese_reason(self):
  self.start();s=self.state_now()
  for name in ('cultivation_train','cultivation_breakthrough'):
   r=self.post(self.body(name));self.assertEqual(r.status_code,422);self.assertIn('当前战斗中',r.json['message']);self.assertNotIn('Traceback',str(r.json))
  self.assertEqual(self.state_now(),s)
 def test_invalid_payload_safe_rejection(self):
  r=self.post(self.body('cultivation_train',{'gain':9999}));self.assertEqual(r.status_code,422);self.assertIn('修炼请求无效',r.json['message'])
 def test_missing_material_reason_and_no_partial_mutation(self):
  self.full();self.execute(self.command('inventory_consume',{'amounts':{'coins':80}}));s=self.state_now();r=self.post(self.body('cultivation_breakthrough'));self.assertEqual(r.status_code,422);self.assertIn('当前不足',r.json['message']);self.assertEqual(self.state_now(),s)
 def test_auth_and_csrf_preserved(self):
  self.assertEqual(self.web.test_client().get('/api/view').status_code,401);self.assertEqual(self.client.post('/api/command',json=self.body('cultivation_train')).status_code,403)
if __name__=='__main__':unittest.main()

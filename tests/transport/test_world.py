import unittest
from contextlib import contextmanager
from src.application.world import WorldApplication
from tests.transport import test_cultivation as f
class WorldHTTPTests(unittest.TestCase):
 def setUp(self):
  from pathlib import Path
  from src.transport.danding import create_app
  from src.transport.combat import register
  from src.rendering.game import present
  from src.rendering.game_runtime import GameRuntimeAssets
  from tests.transport.test_danding import TOKEN
  self.setUp_fixture();self.assets=GameRuntimeAssets(self.root/'assets')
  self.web=create_app(self.application,self.save,lambda v:present(v,self.assets),self.assets.file,TOKEN,secure=False,ui_root=Path('src/ui/pages/game').resolve(),cookie_path='/game/')
  register(self.web,self.application,self.save);self.web.config['SESSION_COOKIE_PATH']='/'
  self.client=self.web.test_client();self.client.post('/login',data={'token':TOKEN});self.csrf=self.client.get('/api/view').json['csrf']
 setUp_fixture=f.CultivationHTTPTests.setUp_fixture
 tearDown=f.CultivationHTTPTests.tearDown
 state_now=f.CultivationHTTPTests.state_now
 command=f.CultivationHTTPTests.command
 execute=f.CultivationHTTPTests.execute
 body=f.CultivationHTTPTests.body
 post=f.CultivationHTTPTests.post
 start=f.CultivationHTTPTests.start
 @contextmanager
 def application(self):
  from src.core.save.sqlite import SQLiteSave
  with SQLiteSave(self.path,allowed_root=self.root) as s:yield WorldApplication(s,self.registry,self.clock)
 def test_world_view(self):self.assertFalse(self.client.get('/api/view').json['view']['world']['paused'])
 def test_pause_command(self):self.assertEqual(self.post(self.body('world_pause')).status_code,200);self.assertTrue(self.client.get('/api/view').json['view']['world']['paused'])
 def test_resume_command(self):self.post(self.body('world_pause'));self.assertEqual(self.post(self.body('world_resume')).status_code,200);self.assertFalse(self.client.get('/api/view').json['view']['world']['paused'])
 def test_replay_both(self):
  for name in ['world_pause','world_resume']:
   q=self.body(name);self.assertEqual(self.post(q).json,self.post(q).json)
 def test_paused_safe_chinese_error(self):
  self.post(self.body('world_pause'))
  for name in ['cultivation_train','cultivation_breakthrough','alchemy_start','combat_start']:
   r=self.post(self.body(name));self.assertEqual(r.status_code,422);self.assertEqual(r.json['message'],'世界已暂停，请先继续运行');self.assertEqual(r.json['error'],'世界已暂停，请先继续运行')
 def test_stale_pause(self):
  q=self.body('world_pause');self.post(self.body('cultivation_train'));self.assertEqual(self.post(q).status_code,409)
 def test_pause_does_not_mutate_hp(self):
  self.start();before=self.state_now().domains['combat'];self.post(self.body('world_pause'));self.assertEqual(self.state_now().domains['combat'],before)
 def test_no_csrf_pause(self):self.assertEqual(self.client.post('/api/command',json=self.body('world_pause')).status_code,403)
 def test_invalid_clock_payload(self):self.assertEqual(self.post(self.body('world_pause',{'elapsed':99999})).status_code,422)
 def test_combat_endpoint_matches_paused_aggregate_and_is_pure(self):
  self.start();self.post(self.body('world_pause'));before=self.state_now()
  full=self.client.get('/api/view').json['view']['combat'];single=self.client.get('/api/combat').json['combat']
  self.assertEqual(single,full);self.assertEqual(single['available_commands'],[]);self.assertEqual(self.state_now(),before)
  self.post(self.body('world_resume'));single=self.client.get('/api/combat').json['combat'];self.assertIn('combat_attack',single['available_commands'])
if __name__=='__main__':unittest.main()

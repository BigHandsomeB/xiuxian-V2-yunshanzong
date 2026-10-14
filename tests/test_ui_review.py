"""Review shares actual UI and synthetic exports; no private transport or writes."""
import unittest,tempfile,copy,json
from pathlib import Path
from io import BytesIO
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.test import Client
from werkzeug.wrappers import Response
from unittest.mock import patch
from src.transport.ui_review import create_review_app,load_bundle,CASES
from tools.playable.game import PROJECT
from tools.playable.build_ui_review import build
from src.core.save.sqlite import SQLiteSave

class ReviewTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  actual=SQLiteSave.__init__
  def guarded(store,path,*args,**kwargs):
   if not Path(path).resolve().is_relative_to(PROJECT/'.tmp'):raise AssertionError('preview touched private save')
   return actual(store,path,*args,**kwargs)
  with patch.object(SQLiteSave,'__init__',guarded):cls.bundle=build()
 def setUp(self):
  self.data=copy.deepcopy(self.bundle);self.files=[]
  def runtime(a,d):self.files.append((a,d));return BytesIO(b'synthetic-image')
  self.app=create_review_app(self.data,runtime,ui_root=PROJECT/'src/ui/pages/game',guide_root=PROJECT/'src/ui/pages/review',design_file=PROJECT/'docs/gameplay/current-game-overview.md')
  def absent(e,s):s('401 Unauthorized',[]);return [b'private']
  self.client=Client(DispatcherMiddleware(absent,{'/game/review':self.app}),Response)
 def test_navigation_and_actual_shared_files(self):
  guide=self.client.get('/game/review/');self.assertEqual(guide.status_code,200);self.assertIn('Boss战斗布局',guide.text)
  page=self.client.get('/game/review/preview');self.assertEqual(page.status_code,200);self.assertIn('data-ui-review="true"',page.text);self.assertIn('/game/review/static/game.js',page.text)
  for name in ['game.js','game.css','screens/battle.js','screens/inventory.js','review-client.js']:
   r=self.client.get('/game/review/static/'+name);self.assertEqual(r.status_code,200);self.assertEqual(r.data,(PROJECT/'src/ui/pages/game/static'/name).read_bytes());r.close()
 def test_four_declared_states(self):
  for case in CASES:
   r=self.client.get('/game/review/api/view?case='+case);self.assertEqual(r.status_code,200);self.assertTrue(r.json['review']['synthetic']);self.assertTrue(r.json['review']['read_only']);self.assertEqual(r.json['csrf'],'')
   if case!='production':self.assertEqual(r.json['view']['combat']['status'],'ACTIVE')
   else:self.assertEqual(r.json['view']['alchemy']['current']['status'],'WORKING')
  self.assertEqual(self.client.get('/game/review/api/view?case=private').status_code,404)
 def test_write_methods_fail_before_any_action(self):
  before=copy.deepcopy(self.data)
  for method in ['POST','PUT','PATCH','DELETE']:
   for path in ['api/command','api/settle','api/combat','api/view','preview','static/game.js']:
    self.assertEqual(self.client.open('/game/review/'+path,method=method,json={'command':'anything'}).status_code,405)
  self.assertEqual(before,self.data);self.assertFalse(self.files)
 def test_no_auth_bypass_or_private_routes(self):
  for path in ['api/command','api/settle','api/combat','login','save','source','../.game/save-id']:
   self.assertNotEqual(self.client.get('/game/review/'+path).status_code,200)
  self.assertEqual(self.client.get('/game/api/view').status_code,401)
  self.assertNotIn('Set-Cookie',self.client.get('/game/review/preview').headers)
 def test_asset_allowlist_and_headers(self):
  assets=self.data['views']['normal']['presentation']['system_icons'];row=next(v['asset'] for v in assets.values() if v['asset'])
  self.assertEqual(self.client.get(row['url']).status_code,200)
  self.assertEqual(self.client.get('/game/review/runtime/unknown.asset/'+'0'*64).status_code,404)
  self.assertEqual(len(self.files),1)
  r=self.client.get('/game/review/preview');self.assertEqual(r.headers['X-Robots-Tag'],'noindex, nofollow');self.assertIn("form-action 'none'",r.headers['Content-Security-Policy'])
 def test_no_sensitive_export_fields(self):
  source=json.dumps(self.data)
  for value in ['ASSET_MANAGER_TOKEN','/root/','.game/']:self.assertNotIn(value,source)
  r=self.client.get('/game/review/design.md');self.assertEqual(r.status_code,200);r.close()
 def test_missing_bundle_fails_closed_and_known_format(self):
  with tempfile.TemporaryDirectory(dir=PROJECT/'.tmp') as tmp:
   path=Path(tmp)/'bundle.json';self.assertIsNone(load_bundle(path));path.write_text('{}')
   self.assertIsNone(load_bundle(path))
  app=create_review_app(None,lambda *a:None,ui_root=PROJECT/'src/ui/pages/game',guide_root=PROJECT/'src/ui/pages/review',design_file=PROJECT/'docs/gameplay/current-game-overview.md')
  c=app.test_client();self.assertEqual(c.get('/').status_code,200);self.assertEqual(c.get('/preview').status_code,503);self.assertEqual(c.get('/api/view').status_code,503)
if __name__=='__main__':unittest.main()

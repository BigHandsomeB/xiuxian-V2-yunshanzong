"""Additive set membership preserves old assets and frozen sheets."""
import tempfile,unittest
from pathlib import Path
from tools.asset_manager.catalog import Catalog,PROJECT
from tools.asset_manager.model import AssetError
from tools.asset_manager.web import create_app

class AppendAssetTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(dir=PROJECT/'tests');self.addCleanup(self.temp.cleanup)
  self.c=Catalog(Path(self.temp.name)/'assets')
 def group(self):return self.c.create_named('resource_icon_v1','系统与页面','set',['暂停按钮'],'sheet')
 def test_preserves_members_and_frozen_sheet_and_creates_single_prompt(self):
  g=self.group();old=self.c.get('asset',g['asset_ids'][0]);p=self.c.prompt(g['template_id'],{},set_id=g['set_id']);manifest=self.c.path('manifest.json').read_bytes()
  a=self.c.append_set_asset(g['set_id'],' 开启按钮 ')
  expanded=self.c.get('set',g['set_id']);self.assertEqual(expanded['asset_ids'],[*g['asset_ids'],a['asset_id']]);self.assertEqual(a['name_zh'],'开启按钮');self.assertEqual(a['versions'],[])
  self.assertEqual(self.c.get('asset',old['asset_id']),old);self.assertEqual(self.c.get('prompt',p['prompt_id']),p);self.assertEqual(self.c.path('manifest.json').read_bytes(),manifest)
  solo=self.c.prompt(a['template_id'],{'family':a['family']},asset_id=a['asset_id'])['frozen_spec'];self.assertEqual(solo['asset_count'],1);self.assertEqual(solo['asset_order'],[a['asset_id']]);self.assertTrue(solo['transparent']);self.assertEqual(solo['runtime_profile'],p['frozen_spec']['runtime_profile'])
 def test_two_appends_use_latest_membership(self):
  g=self.group();a=self.c.append_set_asset(g['set_id'],'开启');b=self.c.append_set_asset(g['set_id'],'设置')
  self.assertEqual(self.c.get('set',g['set_id'])['asset_ids'],[*g['asset_ids'],a['asset_id'],b['asset_id']])
 def test_invalid_append_does_not_mutate(self):
  g=self.group();before=self.c.list('asset')
  for name in ['',None,' 暂停按钮 ', 'a'*161]:
   with self.assertRaises(AssetError):self.c.append_set_asset(g['set_id'],name)
  self.assertEqual(self.c.get('set',g['set_id']),g);self.assertEqual(self.c.list('asset'),before)
 def test_deprecated_set_rejects(self):
  g=self.group();g['status']='deprecated'
  with self.c.transaction() as conn:self.c.put('set',g['set_id'],g,conn)
  with self.assertRaises(AssetError):self.c.append_set_asset(g['set_id'],'开启')
 def test_effect_append_preserves_frame_defaults(self):
  g=self.c.create_named('effect_compact_v1','特效','set',['斩击'],'sheet',counts={'effect':4})
  a=self.c.append_set_asset(g['set_id'],'受击');self.assertEqual(a['generation_defaults']['counts'],g['generation_defaults']['counts']);self.assertEqual(a['state'],'effect')
 def test_http_auth_and_csrf_then_additive_success(self):
  g=self.group();app=create_app(self.c.root,'private-unit-test-token-123456');client=app.test_client();payload=dict(set_id=g['set_id'],name_zh='开启')
  self.assertEqual(client.post('/api/append-set-asset',json=payload).status_code,401)
  with client.session_transaction() as session:session['authenticated']=True;session['csrf']='unit-csrf'
  self.assertEqual(client.post('/api/append-set-asset',json=payload).status_code,403)
  response=client.post('/api/append-set-asset',json=payload,headers={'X-CSRF-Token':'unit-csrf'});self.assertEqual(response.status_code,200);self.assertEqual(response.json['set_id'],g['set_id'])

"""Boot/list projections must avoid historical payload; detail remains lossless."""
import copy, tempfile, unittest, io
from unittest.mock import patch
from PIL import Image
from pathlib import Path
from tools.asset_manager.catalog import PROJECT
from tools.asset_manager.web import create_app

class FastStateTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(dir=PROJECT/'tests');self.addCleanup(self.tmp.cleanup)
  self.app=create_app(Path(self.tmp.name)/'assets','isolated-private-token-long-enough');self.app.testing=True
  self.c=self.app.extensions['asset_catalog'];self.client=self.app.test_client()
  self.headers={'Authorization':'Bearer isolated-private-token-long-enough'}
  self.a=self.c.create_named('monster_static_v1','测试静态怪物',generation_scope='single_asset')
  self.p=self.c.prompt('monster_static_v1',{},asset_id=self.a['asset_id'])
 def get(self,url):return self.client.get(url,headers=self.headers)
 def test_boot_is_summary_not_history(self):
  full=self.get('/api/state');light=self.get('/api/state?compact=1');s=light.get_json()
  self.assertTrue(s.get('compact'))
  self.assertLess(len(light.data),len(full.data)*.7)
  self.assertEqual({a['asset_id'] for a in s['assets']},{a['asset_id'] for a in full.get_json()['assets']})
  self.assertNotIn('frozen_spec',s['prompts'][0]);self.assertNotIn('text',s['prompts'][0])
  for a in s['assets']:self.assertTrue(a['summary_only']);self.assertNotIn('size_provenance',a)
 def test_asset_and_prompt_details_preserve_original_history(self):
  out=io.BytesIO();Image.new('RGBA',(128,128),'green').save(out,format='PNG')
  source=self.c.upload('test.png',out.getvalue(),'monster_static_v1',prompt_id=self.p['prompt_id'])
  plan=self.c.plan(source['source_id'],mode='independent')
  self.c.import_sheet(plan,confirmed=True)
  original=copy.deepcopy(self.c.get('asset',self.a['asset_id']))
  self.assertEqual(len(original['versions']),1)
  summary=next(a for a in self.get('/api/state?compact=1').get_json()['assets'] if a['asset_id']==self.a['asset_id'])
  self.assertNotIn('frozen_spec',summary['versions'][0])
  self.assertEqual(summary['versions'][0]['files'],original['versions'][0]['files'])
  r=self.get('/api/asset-detail?asset_id='+self.a['asset_id']);self.assertEqual(r.status_code,200)
  a=r.get_json()['asset'];self.assertEqual(a['versions'],self.c.get('asset',self.a['asset_id'])['versions'])
  self.assertIn('size_provenance',a);self.assertEqual(a['art_status'],'draft');self.assertFalse(a['runtime_ready']);self.assertEqual(r.get_json()['prompts'][0],self.p)
  self.assertEqual(self.get('/api/prompt-detail?prompt_id='+self.p['prompt_id']).get_json(),self.p)
 def test_compact_search_and_auth(self):
  r=self.get('/api/search?compact=1&q=测试静态');self.assertEqual(len(r.get_json()['assets']),1)
  self.assertTrue(r.get_json()['assets'][0]['summary_only'])
  for route in ('state?compact=1','asset-detail?asset_id='+self.a['asset_id'],'prompt-detail?prompt_id='+self.p['prompt_id']):
   self.assertEqual(self.client.get('/api/'+route).status_code,401)
 def test_gets_do_not_change_registry(self):
  before={kind:copy.deepcopy(self.c.list(kind)) for kind in ('asset','set','source','prompt')}
  self.get('/api/state?compact=1');self.get('/api/asset-detail?asset_id='+self.a['asset_id'])
  self.assertEqual(before,{kind:self.c.list(kind) for kind in before})

 def test_source_details_retain_frozen_spec(self):
  out=io.BytesIO();Image.new('RGBA',(128,128),'green').save(out,format='PNG')
  source=self.c.upload('test.png',out.getvalue(),'monster_static_v1',prompt_id=self.p['prompt_id'])
  result=self.get('/api/source-detail?source_id='+source['source_id']).get_json()
  self.assertEqual(result['source']['frozen_spec'],source['frozen_spec'])
  self.assertEqual(result['prompt'],self.p)
  summary=self.get('/api/state?compact=1').get_json()['sources'][0]
  self.assertTrue(summary['summary_only']);self.assertNotIn('frozen_spec',summary)
  self.assertEqual(self.client.get('/api/source-detail?source_id='+source['source_id']).status_code,401)
 def test_compact_group_status_matches_full_and_uses_request_lookup(self):
  expected=[self.c.completeness(g['set_id']) for g in self.c.list('set')]
  with patch.object(self.c,'get',wraps=self.c.get) as get:
   result=self.get('/api/state?compact=1').get_json()
  self.assertEqual(result['sets'],expected)
  self.assertEqual(get.call_count,0)

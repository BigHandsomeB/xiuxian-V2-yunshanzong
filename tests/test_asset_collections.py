import unittest,tempfile,copy,io,json
from pathlib import Path
from PIL import Image,ImageDraw
from tools.asset_manager.catalog import Catalog,PROJECT
from tools.asset_manager import collections
from tools.asset_manager.model import AssetError
from tools.asset_manager.workflow import prepare,confirm
from tools.asset_manager.web import create_app

class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=PROJECT/'tests');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'assets';self.c=Catalog(self.root)
    def test_generic_mixed_groups_and_standalone(self):
        c=collections.create(self.c,'任意主题');cid=c['collection_id']
        for template,names in [('monster_static_v1',['小怪甲','小怪乙']),('equipment_icon_v1',['装备甲','装备乙']),('material_icon_v1',['材料甲'])]:
            g=self.c.create_named(template,template,generation_scope='asset_set',asset_names=names,collection_id=cid)
            self.assertEqual(g['collection_id'],cid)
            self.assertEqual({a['asset_id'] for a in self.c.search(collection_id=cid)}.intersection(g['asset_ids']),set(g['asset_ids']))
        g=self.c.create_named('character_compact_v1','人物动作',generation_scope='asset_set',collection_id=cid)
        self.assertEqual(g['collection_id'],cid)
        a=self.c.create_named('resource_icon_v1','独立素材',generation_scope='single_asset',collection_id=cid)
        self.assertEqual(a['collection_id'],cid)
        self.assertEqual(collections.rename(self.c,cid,'丹药与宗门')['collection_id'],cid)
        self.assertEqual(self.c.export_registry()['collections'][0]['name_zh'],'丹药与宗门')
        with self.assertRaises(AssetError):collections.remove_empty(self.c,cid)
    def test_existing_reorganization_preserves_assets_prompt_manifest(self):
        g=self.c.create_named('equipment_icon_v1','原装备组',generation_scope='asset_set',asset_names=['甲','乙'])
        p=self.c.prompt(g['template_id'],{},set_id=g['set_id']);assets=copy.deepcopy(self.c.list('asset'));manifest=self.c.path('manifest.json').read_bytes()
        one=collections.create(self.c,'副本集合')['collection_id'];two=collections.create(self.c,'装备集合')['collection_id']
        collections.assign(self.c,'set',g['set_id'],one);collections.assign(self.c,'set',g['set_id'],two)
        self.assertEqual(self.c.get('set',g['set_id'])['asset_ids'],g['asset_ids']);self.assertEqual(self.c.list('asset'),assets)
        self.assertEqual(self.c.get('prompt',p['prompt_id']),p);self.assertEqual(self.c.path('manifest.json').read_bytes(),manifest)
        self.assertFalse(self.c.search(collection_id=one));self.assertEqual(len(self.c.search(collection_id=two)),2)
        with self.assertRaises(AssetError):collections.assign(self.c,'asset',g['asset_ids'][0],one)
        collections.assign(self.c,'set',g['set_id']);collections.remove_empty(self.c,two)
        self.assertNotIn('collection_id',self.c.get('set',g['set_id']))
    def test_invalid_parent_atomic_and_detach_inherits_collection(self):
        count=len(self.c.list('asset'))
        with self.assertRaises(AssetError):self.c.create_named('resource_icon_v1','坏引用',collection_id='missing')
        self.assertEqual(len(self.c.list('asset')),count)
        cid=collections.create(self.c,'集合')['collection_id'];g=self.c.create_named('resource_icon_v1','组',generation_scope='asset_set',asset_names=['一','二'],collection_id=cid)
        from tools.asset_manager.lifecycle import detach
        with self.c.transaction() as conn:detach(self.c,g['asset_ids'][0],conn)
        a=self.c.get('asset',g['asset_ids'][0]);self.assertIsNone(a['set_id']);self.assertEqual(a['collection_id'],cid)
    def test_http_auth_csrf_and_roundtrip(self):
        app=create_app(self.root,'test-only-collection-token-32-characters');app.testing=True;client=app.test_client()
        self.assertEqual(client.post('/api/collections',json={'name_zh':'集合'}).status_code,401)
        client.post('/login',data={'token':'test-only-collection-token-32-characters'})
        with client.session_transaction() as s:csrf=s['csrf']
        self.assertEqual(client.post('/api/collections',json={'name_zh':'集合'}).status_code,403)
        response=client.post('/api/collections',json={'name_zh':'集合'},headers={'X-CSRF-Token':csrf});self.assertEqual(response.status_code,200)
        data=client.get('/api/state?compact=1').json;self.assertEqual(data['collections'][0]['collection_id'],response.json['collection_id'])
    def test_dungeon_sheet_true_alpha_native128_replay(self):
        names=['测试副本甲','测试副本乙','测试副本丙']
        g=self.c.create_named('dungeon_icon_v1','副本图标',generation_scope='asset_set',asset_names=names,source_container='sheet')
        p=self.c.prompt(g['template_id'],{},set_id=g['set_id']);spec=p['frozen_spec']
        self.assertEqual(spec['runtime_profile']['frame_size'],[128,128]);self.assertTrue(spec['transparent']);self.assertEqual(spec['frame_counts'],{'icon':1})
        self.assertEqual([v['name_zh'] for v in spec['cell_mapping']],names)
        self.assertIn('alpha=0',p['text']);self.assertIn('RGBA PNG',p['text']);self.assertIn('No full rectangular scenery background',p['text'])
        layout=spec['layout_spec'];w,h=spec['source_cell_size'];gap=spec['spacing'];image=Image.new('RGBA',(layout['columns']*w+(layout['columns']-1)*gap,layout['rows']*h+(layout['rows']-1)*gap))
        draw=ImageDraw.Draw(image)
        for i,cell in enumerate(spec['cell_mapping']):
            x=cell['column']*(w+gap)+16;y=cell['row']*(h+gap)+16
            draw.ellipse((x,y,x+127,y+127),fill=(40+i*20,90,130,255));draw.point((x+64,y+64),fill=(255,20,30,255))
        out=io.BytesIO();image.save(out,format='PNG');source=self.c.upload('test.png',out.getvalue(),g['template_id'],g['set_id'],p['prompt_id'])
        located=self.c.auto_locate(source['source_id']);self.assertEqual(located['status'],'PASS')
        preview=prepare(self.c,source_id=source['source_id'],regions=located['regions'],mode='auto');result=confirm(self.c,preview['preview_id'],True);self.assertEqual(result,confirm(self.c,preview['preview_id'],True))
        for aid in g['asset_ids']:
            v=self.c.get('asset',aid)['versions'][0];f=v['runtime']['files'][0]
            with Image.open(self.c.path(f['file'])) as im:self.assertEqual(im.size,(128,128));self.assertEqual(im.getextrema()[3][0],0);self.assertTrue(any(im.getpixel((x,y))==(255,20,30,255) for y in range(im.height) for x in range(im.width)))

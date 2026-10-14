"""Isolated static actor sheets: identity, auto crops, native clarity and legacy compatibility."""
import copy, io, json, tempfile, unittest
from pathlib import Path
from PIL import Image, ImageDraw
from tools.asset_manager.catalog import Catalog, PROJECT
from tools.asset_manager.images import profiled_runtime
from tools.asset_manager.model import AssetError
from tools.asset_manager.specs import freeze_spec
from tools.asset_manager.workflow import prepare, confirm

NAMES=['荆棘鼠','青苔野兔','枯枝螳螂','灰羽山鸦','石背蜥','毒须蜈蚣']

class StaticMonsterTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=PROJECT/'tests')
        self.addCleanup(self.temp.cleanup)
        self.c=Catalog(Path(self.temp.name)/'assets')

    def source(self,t='monster_static_v1',names=None):
        g=self.c.create_named(t,'副本怪物',asset_names=names or NAMES)
        p=self.c.prompt(t,{},set_id=g['set_id']);s=p['frozen_spec'];layout=s['layout_spec']
        cw,ch=s['source_cell_size'];gap=s['spacing'];n=s['subject_logic_size'][0]
        im=Image.new('RGBA',(layout['columns']*cw+(layout['columns']-1)*gap,layout['rows']*ch+(layout['rows']-1)*gap))
        draw=ImageDraw.Draw(im)
        for i,cell in enumerate(s['cell_mapping']):
            x=cell['column']*(cw+gap)+16;y=cell['row']*(ch+gap)+16
            draw.rectangle((x,y,x+n-1,y+n-1),fill=(50+i*20,110,170,255))
            # A native one-pixel detail must survive cropping/export without blur or half-size fitting.
            draw.point((x+5,y+5),fill=(255,30,10,255))
        out=io.BytesIO();im.save(out,format='PNG')
        src=self.c.upload('monsters.png',out.getvalue(),t,g['set_id'],p['prompt_id'])
        return g,p,src

    def test_default_collection_is_distinct_monsters_not_actions(self):
        g,p,_=self.source();s=p['frozen_spec']
        self.assertEqual(g['kind'],'static_collection');self.assertEqual(len(g['asset_ids']),6)
        self.assertEqual(s['sheet_semantics'],'independent_assets');self.assertEqual(s['frame_counts'],{'icon':1})
        self.assertEqual(s['action_count'],0);self.assertEqual(s['frame_count'],1)
        self.assertEqual([c['name_zh'] for c in s['cell_mapping']],NAMES)
        self.assertEqual(s['runtime_profile']['frame_size'],[128,128])

    def test_static_prompt_names_all_monsters_and_disallows_dynamic(self):
        g,p,_=self.source()
        for n in NAMES:self.assertIn(n,p['text'])
        self.assertIn('6 different independent game assets',p['text'])
        self.assertIn('one neutral pose',p['text'].lower())
        with self.assertRaises(AssetError):self.c.prompt(g['template_id'],{'mode':'dynamic'},set_id=g['set_id'])
        with self.assertRaises(AssetError):self.c.prompt(g['template_id'],{'counts':{'attack':3}},set_id=g['set_id'])

    def test_auto_slice_confirm_native128_and_replay(self):
        g,p,src=self.source();before=copy.deepcopy(self.c.get('prompt',p['prompt_id'])['frozen_spec'])
        located=self.c.auto_locate(src['source_id'])
        self.assertEqual(located['status'],'PASS');self.assertEqual(len(located['regions']),6)
        self.assertEqual([r['asset_id'] for r in located['regions']],g['asset_ids'])
        preview=prepare(self.c,source_id=src['source_id'],regions=located['regions'],mode='auto')
        self.assertTrue(all(i['valid'] for i in preview['items']))
        result=confirm(self.c,preview['preview_id'],True)
        self.assertEqual(sum(a['status']=='approved' for a in result['assets']),6)
        self.assertEqual(confirm(self.c,preview['preview_id'],True),result)
        manifest=json.loads(self.c.path('manifest.json').read_text())['assets']
        self.assertEqual(set(manifest),set(g['asset_ids']))
        for aid in g['asset_ids']:
            a=self.c.get('asset',aid);self.assertEqual(a['runtime_role'],'monster_image')
            self.assertEqual(len(a['versions']),1);files=a['versions'][0]['runtime']['files'];self.assertEqual(len(files),1)
            with Image.open(self.c.path(files[0]['file'])) as im:
                self.assertEqual(im.size,(128,128));self.assertEqual(im.getchannel('A').getbbox(),(0,0,128,128))
                self.assertEqual(im.getpixel((5,5)),(255,30,10,255))
        self.assertEqual(self.c.get('prompt',p['prompt_id'])['frozen_spec'],before)

    def test_boss_collection_exports256(self):
        g,p,src=self.source('boss_static_v1',['荆棘山魈王','赤铜镇矿傀'])
        r=self.c.auto_locate(src['source_id'])['regions']
        result=confirm(self.c,prepare(self.c,source_id=src['source_id'],regions=r,mode='auto')['preview_id'],True)
        self.assertEqual(sum(a['status']=='approved' for a in result['assets']),2)
        for aid in g['asset_ids']:
            a=self.c.get('asset',aid);self.assertEqual(a['runtime_role'],'boss_image')
            f=a['versions'][0]['runtime']['files'][0]
            with Image.open(self.c.path(f['file'])) as im:self.assertEqual(im.size,(256,256))

    def test_native_single_image_and_grid_crop_do_not_require_source_cell_size(self):
        s=freeze_spec(self.c.templates['monster_static_v1'])
        for canvas in (128,160):
            im=Image.new('RGBA',(canvas,canvas));offset=(canvas-128)//2
            ImageDraw.Draw(im).rectangle((offset,offset,offset+127,offset+127),fill='green')
            with Image.open(io.BytesIO(profiled_runtime(im,s))) as out:
                self.assertEqual(out.size,(128,128));self.assertEqual(out.getchannel('A').getbbox(),(0,0,128,128))

    def test_old_monster_and_boss_snapshots_still_have_original_actions(self):
        old=freeze_spec(self.c.templates['monster_compact_v1'])
        self.assertEqual(old['frame_counts'],{'idle':2,'attack':3,'hit':1,'death':3})
        self.assertEqual(old['runtime_profile']['frame_size'],[128,128])
        self.assertNotIn('trim_transparent',old['runtime_profile'])
        boss=freeze_spec(self.c.templates['boss_v1'])
        self.assertEqual(boss['sheet_semantics'],'action_frames')
        self.assertEqual(boss['runtime_profile']['frame_size'],[160,160])

    def test_missing_and_duplicate_names_rejected_without_assets(self):
        before=self.c.list('asset')
        for names in ([],['荆棘鼠','荆棘鼠']):
            with self.assertRaises(AssetError):self.c.create_named('monster_static_v1','怪物',asset_names=names)
        self.assertEqual(self.c.list('asset'),before)

if __name__=='__main__':unittest.main()

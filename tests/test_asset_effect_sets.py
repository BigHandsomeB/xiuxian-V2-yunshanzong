"""Named FX rows keep their own animation frames and frozen source identities."""
import copy,io,json,tempfile,unittest
from pathlib import Path
from PIL import Image,ImageDraw
from tools.asset_manager.catalog import Catalog,PROJECT
from tools.asset_manager.model import AssetError
from tools.asset_manager.sheets import regions
from tools.asset_manager.workflow import prepare,confirm

class EffectSetTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(dir=PROJECT/'tests');self.addCleanup(tmp.cleanup)
        self.c=Catalog(Path(tmp.name)/'assets')
    def group(self,names=None,frames=4):
        return self.c.create_named('effect_compact_v1','通用战斗特效','asset_set',names or ['剑气斩击','命中闪光','灵力施法'],source_container='sheet',counts={'effect':frames})
    def prompt(self,g):return self.c.prompt(g['template_id'],{'object':g['name_zh']},set_id=g['set_id'])
    def source(self,p):
        spec=p['frozen_spec'];rs=regions(spec);g=spec['grid_spec'];im=Image.new('RGBA',(g['columns']*128+(g['columns']-1)*32,g['rows']*128+(g['rows']-1)*32));d=ImageDraw.Draw(im)
        for r in rs:
            x,y,w,h=r['rect'];d.rectangle((x+50,y+50,x+77,y+77),fill=(60+r['row']*50,50+r['frame']*30,100,255))
        out=io.BytesIO();im.save(out,format='PNG');return self.c.upload('fx.png',out.getvalue(),p['template_id'],p['set_id'],p['prompt_id']),rs
    def test_preview_is_named_rows_not_static_assets_or_master(self):
        v=self.c.creation_preview('effect_compact_v1','特效','asset_set',['斩击','命中'],counts={'effect':4})
        self.assertTrue(v['named_collection']);self.assertFalse(v['static']);self.assertEqual((v['asset_count'],v['grid_rows'],v['grid_columns']),(2,2,4))
        g=self.group();self.assertEqual(g['kind'],'effect_collection');self.assertEqual(len(g['asset_ids']),3)
        self.assertEqual(self.c.completeness(g['set_id'])['total'],3)
        self.assertTrue(all(self.c.get('asset',a)['state']=='effect' for a in g['asset_ids']))
    def test_prompt_freezes_names_and_four_frames_for_every_effect(self):
        g=self.group();p=self.prompt(g);s=p['frozen_spec'];self.assertEqual(len(s['cell_mapping']),12);self.assertNotIn('asset_list',s)
        for i,aid in enumerate(g['asset_ids']):
            cells=[c for c in s['cell_mapping'] if c['asset_id']==aid]
            self.assertEqual([c['row'] for c in cells],[i]*4);self.assertEqual([c['frame'] for c in cells],[1,2,3,4])
        self.assertIn('Row 1: 剑气斩击, 4 frames',p['text']);self.assertIn('DIFFERENT named effect',p['text']);self.assertTrue(s['transparent'])
        aid=g['asset_ids'][0];single=self.c.specification(g['template_id'],{},asset_id=aid,set_id=g['set_id'])
        self.assertEqual(single['asset_ids'],[aid]);self.assertEqual(len(single['cell_mapping']),4)
    def test_grid_preview_and_confirmation_export_each_effect_own_frames(self):
        g=self.group();p=self.prompt(g);source,rs=self.source(p);preview=prepare(self.c,source_id=source['source_id'],regions=rs,mode='grid')
        self.assertEqual(len(preview['items']),3);self.assertTrue(all(i['valid'] for i in preview['items']),[i['issues'] for i in preview['items']])
        self.assertTrue(all(len(i['preview_files'])==4 for i in preview['items']))
        self.assertTrue(all(not self.c.get('asset',a)['versions'] for a in g['asset_ids']))
        result=confirm(self.c,preview['preview_id'],True);self.assertTrue(all(a['status']=='approved' for a in result['assets']),result)
        colors=[]
        for aid in g['asset_ids']:
            asset=self.c.get('asset',aid);files=asset['versions'][0]['runtime']['files'];self.assertEqual(len(files),4);self.assertEqual([f['frame'] for f in files],[1,2,3,4])
            with Image.open(self.c.path(files[0]['file'])) as im:colors.append(im.getpixel((64,64)))
        self.assertEqual(len(set(colors)),3)
    def test_advanced_import_and_frozen_history_survive_list_edit(self):
        g=self.group();p=self.prompt(g);source,rs=self.source(p);old=copy.deepcopy(p)
        plan=self.c.sheet_plan(source,p['frozen_spec'],self.c.source_image(source),rs,'grid',p['frozen_spec']['grid_spec']);self.c.import_sheet(plan,True)
        self.assertTrue(all(len(self.c.get('asset',a)['versions'][0]['files'])==4 for a in g['asset_ids']))
        edited=self.c.edit_static_set(g['set_id'],[{'asset_id':g['asset_ids'][1],'name_zh':'命中亮光'},{'name_zh':'火焰爆裂'}],'sheet')
        self.assertEqual(self.c.get('prompt',p['prompt_id']),old);self.assertEqual(self.c.completeness(g['set_id'])['total'],2)
        new=self.prompt(edited);self.assertEqual(new['frozen_spec']['frame_asset_list'][0]['name_zh'],'命中亮光');self.assertEqual(new['frozen_spec']['frame_counts'],{'effect':4})
        self.assertIsNone(self.c.get('asset',g['asset_ids'][0])['set_id'])
    def test_rejects_duplicate_names_wrong_container_and_too_many_cells(self):
        for names,container,frames in [(['斩击','斩击'],'sheet',2),(['斩击','命中'],'image_set',2),([str(i) for i in range(65)],'sheet',4)]:
            with self.assertRaises(AssetError):self.c.create_named('effect_compact_v1','特效','asset_set',names,source_container=container,counts={'effect':frames})
    def test_background_ground_contract_is_scene_only(self):
        p=self.c.prompt('battle_background_v1',{'object':'荆棘古道'});s=p['frozen_spec'];self.assertFalse(s['transparent']);self.assertEqual(s['source_container'],'single_image')
        for word in ['落脚','55%～85%','74%','640','No actors']:self.assertIn(word,p['text'])
        self.assertEqual(s['runtime_profile']['frame_size'],[640,360]);self.assertEqual(s['source_cell_size'],[640,360]);self.assertNotIn('必须真实透明',p['text']);self.assertNotIn('feet baseline inset 0',p['text'])
        self.assertNotIn('脚底基线在约70%',self.c.prompt('environment_scene_v1',{'object':'荆棘古道'})['text'])
        self.assertNotIn('脚底基线在约70%',self.prompt(self.group())['text'])

    def test_hd_background_confirm_exports_full_640x360_without_resizing_other_scenes(self):
        self.c.create_asset('scene.test','荆棘古道','battle_background_v1',state='scene')
        p=self.c.prompt('battle_background_v1',{'object':'荆棘古道'},asset_id='scene.test')
        im=Image.new('RGBA',(640,360),(60,90,30,255));out=io.BytesIO();im.save(out,format='PNG')
        source=self.c.upload('arena.png',out.getvalue(),'battle_background_v1',prompt_id=p['prompt_id'])
        preview=prepare(self.c,source_id=source['source_id'],regions=regions(p['frozen_spec']),mode='grid')
        result=confirm(self.c,preview['preview_id'],True);self.assertEqual(result['assets'][0]['status'],'approved')
        row=self.c.get('asset','scene.test')['versions'][0];f=row['runtime']['files'][0];self.assertEqual((f['width'],f['height']),(640,360))
        with Image.open(self.c.path(f['file'])) as image:self.assertEqual(image.size,(640,360))
        other=self.c.specification('environment_scene_v1',{'object':'远景'});self.assertEqual(other['runtime_profile']['frame_size'],[320,180])

"""Bounded geometric localization; immutable semantic mapping and crop/runtime regression."""
import copy,io,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image,ImageDraw
from tools.asset_manager.geometry import locate,overlaps,_padded_boxes
from tools.asset_manager.catalog import Catalog,PROJECT
from tools.asset_manager.model import AssetError,REVIEW
from tools.asset_manager.web import create_app

NAMES=['玄铁矿','赤铜矿','寒铁矿','灵晶矿','赤炎矿','星陨矿']
def sheet(size=(600,400),opaque=False):
    im=Image.new('RGBA',size,(245,245,245,255) if opaque else (0,0,0,0));d=ImageDraw.Draw(im)
    for row in range(2):
        for col in range(3):
            x=(35+190*col)*size[0]//600;y=(35+190*row)*size[1]//400
            d.rectangle((x,y,x+75*size[0]//600,y+85*size[1]//400),fill=(40+col*40,90+row*60,150,255))
    return im

class GeometryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=PROJECT/'tests');self.addCleanup(self.temp.cleanup)
        self.c=Catalog(Path(self.temp.name)/'assets');self.group=self.c.create_named('resource_icon_v1','矿石','set',NAMES,'sheet')
        self.prompt=self.c.prompt('resource_icon_v1',{},set_id=self.group['set_id']);self.spec=self.prompt['frozen_spec']
    def source(self,im=None):
        out=io.BytesIO();(im if im is not None else sheet()).save(out,format='PNG')
        return self.c.upload('sheet.png',out.getvalue(),'resource_icon_v1',self.group['set_id'],self.prompt['prompt_id'])
    def test_transparent_foreground_six_regions(self):
        r=locate(sheet(),self.spec);self.assertEqual(r['status'],'PASS');self.assertEqual(r['foreground_method'],'alpha');self.assertEqual(r['detected_count'],6)
    def test_two_by_three_row_major_from_frozen_cells(self):
        r=locate(sheet(),self.spec);self.assertEqual([a['asset_id'] for a in r['regions']],self.spec['asset_order'])
        self.assertEqual([(a['row'],a['column']) for a in r['regions']],[(0,0),(0,1),(0,2),(1,0),(1,1),(1,2)])
    def test_names_come_from_snapshot_not_pixels(self):
        other=copy.deepcopy(self.spec);other['cell_mapping'][0]['name_zh']='任意冻结名'
        self.assertEqual(locate(sheet(),other)['regions'][0]['name_zh'],'任意冻结名')
    def test_small_fragment_merges_to_nearest(self):
        im=sheet();ImageDraw.Draw(im).rectangle((115,85,122,93),fill='red');r=locate(im,self.spec)
        self.assertEqual(r['status'],'PASS');self.assertEqual(r['merged_fragment_count'],1);self.assertGreater(r['regions'][0]['rect'][0]+r['regions'][0]['rect'][2],122)
    def test_tiny_noise_ignored(self):
        im=sheet();im.putpixel((580,390),(255,0,0,255));self.assertEqual(locate(im,self.spec)['detected_count'],6)
    def test_near_transparent_noise_ignored(self):
        im=sheet();ImageDraw.Draw(im).rectangle((140,130,160,150),fill=(255,0,0,3));self.assertEqual(locate(im,self.spec)['status'],'PASS')
    def test_padding_surrounds_subject(self):
        r=locate(sheet(),self.spec)['regions'][0]['rect'];self.assertLess(r[0],35);self.assertLess(r[1],35);self.assertGreater(r[0]+r[2],110);self.assertGreater(r[1]+r[3],120)
    def test_padding_clamps_midpoint_and_source_edge(self):
        boxes=[[0,0,50,50],[52,0,102,50]];a,b=_padded_boxes(boxes,110,60)
        self.assertEqual(a[0],0);self.assertFalse(overlaps(a,b));self.assertLessEqual(a[0]+a[2],51);self.assertGreaterEqual(b[0],51)
    def test_thumbnail_coordinates_map_to_full_source(self):
        im=sheet((1800,1200));r=locate(im,self.spec)
        self.assertEqual(r['thumbnail_size'][0],512);a=r['regions'][0]['rect'];self.assertLess(a[0],105);self.assertGreater(a[0]+a[2],330);self.assertGreater(a[2],225)
    def test_uniform_opaque_background_fallback(self):
        r=locate(sheet(opaque=True),self.spec);self.assertEqual(r['status'],'NEEDS_REVIEW');self.assertEqual(r['foreground_method'],'edge_color');self.assertEqual(len(r['regions']),6)
    def test_complex_opaque_background_fails_without_guessing(self):
        im=sheet(opaque=True);d=ImageDraw.Draw(im);d.rectangle((0,0,599,15),fill='red')
        self.assertEqual(locate(im,self.spec)['status'],'FAILED')
    def test_fewer_components_fails_without_duplication(self):
        im=sheet();ImageDraw.Draw(im).rectangle((400,0,599,399),fill=(0,0,0,0));r=locate(im,self.spec)
        self.assertEqual(r['status'],'FAILED');self.assertEqual(r['regions'],[]);self.assertEqual(r['detected_count'],4)
    def test_seventh_comparable_object_not_merged(self):
        im=sheet();ImageDraw.Draw(im).rectangle((120,130,185,185),fill='red');r=locate(im,self.spec)
        self.assertEqual(r['status'],'FAILED');self.assertEqual(r['regions'],[])
    def test_distant_fragment_not_forced_into_expected_count(self):
        im=sheet();ImageDraw.Draw(im).rectangle((570,380,580,390),fill='red');self.assertEqual(locate(im,self.spec)['status'],'FAILED')
    def test_blank_image_fails(self):self.assertEqual(locate(Image.new('RGBA',(200,200)),self.spec)['status'],'FAILED')
    def test_abnormal_row_distribution_requires_review(self):
        im=Image.new('RGBA',(600,400));d=ImageDraw.Draw(im)
        for x,y in [(10,10),(160,80),(310,140),(10,250),(160,250),(310,250)]:d.rectangle((x,y,x+60,y+50),fill='red')
        self.assertEqual(locate(im,self.spec)['status'],'NEEDS_REVIEW')
    def test_query_does_not_alter_source_or_prompt(self):
        s=self.source();before=self.c.export_registry();self.c.auto_locate(s['source_id']);self.assertEqual(self.c.export_registry(),before);self.assertEqual(self.c.get('prompt',self.prompt['prompt_id']),self.prompt)
    def test_actual_region_mapping_persists_separate_from_snapshot(self):
        s=self.source();r=self.c.auto_locate(s['source_id']);plan=self.c.plan(s['source_id'],mode='auto',regions=r['regions'],detection=r);self.c.import_static_set(plan,True)
        reopened=Catalog(self.c.root);new=reopened.get('source',s['source_id']);self.assertEqual(new['frozen_spec'],s['frozen_spec']);self.assertEqual(new['source_region_mappings'][0]['regions'],plan['regions']);self.assertEqual(new['source_region_mappings'][0]['expected_layout'],dict(rows=2,columns=3));self.assertEqual(reopened.get('prompt',self.prompt['prompt_id']),self.prompt)
    def test_runtime_target_independent_of_detected_bbox(self):
        s=self.source(sheet((1800,1200)));r=self.c.auto_locate(s['source_id']);self.c.import_static_set(self.c.plan(s['source_id'],mode='auto',regions=r['regions']),True)
        for aid in self.group['asset_ids']:
            self.c.review(aid,1,'needs_review');self.c.review(aid,1,'approved',dict.fromkeys(REVIEW,True));self.c.select(aid,1);runtime=self.c.build(aid,1)
            self.assertEqual([runtime['files'][0]['width'],runtime['files'][0]['height']],self.spec['runtime_profile']['frame_size'])
            with Image.open(self.c.path(runtime['files'][0]['file'])) as im:self.assertIsNotNone(im.getbbox())
        self.assertEqual(len(self.c.publish()['assets']),6)
    def test_manual_fallback_retained(self):
        s=self.source();regions=locate(sheet(),self.spec)['regions'];plan=self.c.plan(s['source_id'],mode='manual',regions=regions);self.assertEqual(len(self.c.import_static_set(plan,True)),6)
    def test_overlapping_auto_regions_rejected(self):
        s=self.source();r=self.c.auto_locate(s['source_id']);r['regions'][1]['rect']=r['regions'][0]['rect']
        with self.assertRaises(AssetError):self.c.plan(s['source_id'],mode='auto',regions=r['regions'])
    def test_wrong_ids_rejected(self):
        s=self.source();r=self.c.auto_locate(s['source_id']);r['regions'][0]['asset_id']='icon.unknown'
        with self.assertRaises(AssetError):self.c.plan(s['source_id'],mode='auto',regions=r['regions'])
    def test_stale_detection_rejected(self):
        s=self.source();r=self.c.auto_locate(s['source_id']);r['source_sha256']='stale'
        with self.assertRaises(AssetError):self.c.plan(s['source_id'],mode='auto',regions=r['regions'],detection=r)
    def test_mapping_and_versions_roll_back_together(self):
        s=self.source();r=self.c.auto_locate(s['source_id']);plan=self.c.plan(s['source_id'],mode='auto',regions=r['regions']);original=self.c._import_version;calls=0
        def fail(*args):
            nonlocal calls
            calls+=1
            if calls==2:raise OSError('failure')
            return original(*args)
        with patch.object(self.c,'_import_version',side_effect=fail):
            with self.assertRaises(OSError):self.c.import_static_set(plan,True)
        self.assertNotIn('source_region_mappings',self.c.get('source',s['source_id']))
        self.assertTrue(all(not self.c.get('asset',aid)['versions'] for aid in self.group['asset_ids']))
    def test_authenticated_web_detection_and_anonymous_rejection(self):
        s=self.source();app=create_app(self.c.root,'x'*32);client=app.test_client()
        self.assertEqual(client.post('/api/auto-locate',json=dict(source_id=s['source_id'])).status_code,401)
        result=client.post('/api/auto-locate',json=dict(source_id=s['source_id']),headers={'Authorization':'Bearer '+'x'*32})
        self.assertEqual(result.status_code,200);self.assertEqual(result.json['detected_count'],6)
    def test_out_of_bounds_auto_plan_rejected(self):
        s=self.source();r=self.c.auto_locate(s['source_id']);r['regions'][0]['rect']=[-1,0,50,50]
        with self.assertRaises(AssetError):self.c.plan(s['source_id'],mode='auto',regions=r['regions'])

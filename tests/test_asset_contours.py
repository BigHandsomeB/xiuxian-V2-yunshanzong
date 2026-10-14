"""Layout-guided alpha suggestion remains explicit, bounded and semantically frozen."""
import copy,unittest
from PIL import Image,ImageDraw
from tools.asset_manager.contours import locate_contours
from tools.asset_manager.geometry import locate
from tools.asset_manager.selection import crop_region,validate,intersect
from tests import test_asset_geometry as fixture
sheet=fixture.sheet

class ContourTests(unittest.TestCase):
    setUp=fixture.GeometryTests.setUp
    source=fixture.GeometryTests.source
    def test_disconnected_pieces_grouped_without_changing_mapping(self):
        im=sheet();d=ImageDraw.Draw(im)
        for row in range(2):
            for col in range(3):d.rectangle((115+col*190,65+row*190,145+col*190,120+row*190),fill='red')
        self.assertEqual(locate(im,self.spec)['status'],'FAILED')
        before=copy.deepcopy(self.spec);r=locate_contours(im,self.spec)
        self.assertEqual(r['status'],'NEEDS_REVIEW');self.assertEqual(r['detected_count'],6)
        self.assertEqual(r['merged_fragment_count'],6);self.assertEqual(self.spec,before)
        self.assertEqual([v['asset_id'] for v in r['regions']],self.spec['asset_order'])
        for v in r['regions']:validate(v,im.width,im.height);self.assertLessEqual(len(v['polygon']),32)
        self.assertFalse(any(intersect(a,b,im.width,im.height) for i,a in enumerate(r['regions']) for b in r['regions'][i+1:]))
    def tight_sheet(self):
        im=Image.new('RGBA',(512,200));draw=ImageDraw.Draw(im)
        for col in range(3):
            x=35+col*170
            draw.polygon([(x,0),(x+100,0),(x+100,99),(x,90)],fill='red')
            draw.polygon([(x,94),(x+100,103),(x+100,199),(x,199)],fill='blue')
        return im
    def test_close_disjoint_silhouettes_reduce_padding_without_cutting(self):
        im=self.tight_sheet();before=im.tobytes();r=locate_contours(im,self.spec)
        self.assertEqual(r['status'],'NEEDS_REVIEW');self.assertEqual(len(r['regions']),6)
        self.assertEqual(r['contour_padding'],.5)
        self.assertFalse(any(intersect(a,b,im.width,im.height) for i,a in enumerate(r['regions']) for b in r['regions'][i+1:]))
        self.assertEqual(sum(sum(v>0 for v in crop_region(im,region).getchannel('A').get_flattened_data()) for region in r['regions']),sum(v>0 for v in im.getchannel('A').get_flattened_data()))
        self.assertEqual(im.tobytes(),before)
    def test_default_catalog_falls_back_to_reviewable_contours(self):
        im=self.tight_sheet();self.assertEqual(locate(im,self.spec)['status'],'FAILED')
        source=self.source(im);before=self.c.export_registry();r=self.c.auto_locate(source['source_id'])
        self.assertEqual(r['status'],'NEEDS_REVIEW');self.assertTrue(r['automatic_contour_fallback'])
        plan=self.c.plan(source['source_id'],mode='auto',regions=r['regions'],detection=r)
        self.assertEqual(len(plan['regions']),6);self.assertEqual(self.c.export_registry(),before)
    def test_close_sloping_edges_refine_without_losing_pixels(self):
        im=self.tight_sheet();draw=ImageDraw.Draw(im)
        im.paste((0,0,0,0),(0,0,512,200))
        for col in range(3):
            x=35+col*170
            draw.polygon([(x,0),(x+100,0),(x+100,99),(x,90)],fill='red')
            draw.polygon([(x,93),(x+100,102),(x+100,199),(x,199)],fill='blue')
        source=self.source(im);r=self.c.auto_locate(source['source_id'])
        self.assertEqual(r['status'],'NEEDS_REVIEW')
        self.assertTrue(r['contour_edge_detail'])
        self.assertEqual(len(r['regions']),6)
        for region in r['regions']:self.assertLessEqual(len(region['polygon']),128)
        self.assertFalse(any(intersect(a,b,im.width,im.height) for i,a in enumerate(r['regions']) for b in r['regions'][i+1:]))
        self.assertEqual(sum(sum(v>0 for v in crop_region(im,region).getchannel('A').get_flattened_data()) for region in r['regions']),sum(v>0 for v in im.getchannel('A').get_flattened_data()))
    def test_interlocking_concave_subjects_use_vertical_envelopes(self):
        im=Image.new('RGBA',(512,200));draw=ImageDraw.Draw(im)
        for col in range(3):
            x=35+col*170
            draw.rectangle((x,10,x+100,30),fill='red')
            draw.rectangle((x,10,x+20,90),fill='red')
            draw.rectangle((x+80,10,x+100,90),fill='red')
            draw.polygon([(x+50,80),(x+70,110),(x+100,110),(x+100,190),(x,190),(x,110),(x+30,110)],fill='blue')
        source=self.source(im);r=self.c.auto_locate(source['source_id'])
        self.assertEqual(r['status'],'NEEDS_REVIEW')
        self.assertEqual(r['contour_axis'],'x')
        self.assertEqual([v['asset_id'] for v in r['regions']],self.spec['asset_order'])
        for region in r['regions']:self.assertLessEqual(len(region['polygon']),128)
        self.assertFalse(any(intersect(a,b,im.width,im.height) for i,a in enumerate(r['regions']) for b in r['regions'][i+1:]))
        self.assertEqual(sum(sum(v>0 for v in crop_region(im,region).getchannel('A').get_flattened_data()) for region in r['regions']),sum(v>0 for v in im.getchannel('A').get_flattened_data()))
    def test_padding_only_overlap_retries_without_clipping_subjects(self):
        im=Image.new('RGBA',(512,200));draw=ImageDraw.Draw(im)
        for col in range(3):
            x=35+col*170
            draw.polygon([(x,0),(x+100,0),(x+100,94),(x,90)],fill='red')
            draw.polygon([(x,95),(x+100,99),(x+100,199),(x,199)],fill='blue')
        source=self.source(im);r=self.c.auto_locate(source['source_id'])
        self.assertEqual(r['status'],'NEEDS_REVIEW')
        self.assertEqual(r['contour_padding'],0)
        self.assertEqual(len(r['regions']),6)
        self.assertFalse(any(intersect(a,b,im.width,im.height) for i,a in enumerate(r['regions']) for b in r['regions'][i+1:]))
        self.assertEqual(sum(sum(v>0 for v in crop_region(im,region).getchannel('A').get_flattened_data()) for region in r['regions']),sum(v>0 for v in im.getchannel('A').get_flattened_data()))
    def test_blank_image_not_guessed(self):
        r=locate_contours(Image.new('RGBA',(600,400)),self.spec);self.assertEqual(r['status'],'FAILED');self.assertEqual(r['regions'],[])
    def test_missing_cell_not_filled_with_noise(self):
        im=sheet();ImageDraw.Draw(im).rectangle((400,0,599,399),fill=(0,0,0,0))
        self.assertEqual(locate_contours(im,self.spec)['status'],'FAILED')
    def test_seventh_comparable_separate_object_not_forced_into_six(self):
        im=sheet();ImageDraw.Draw(im).rectangle((120,130,185,185),fill='red')
        self.assertEqual(locate_contours(im,self.spec)['status'],'FAILED')
    def test_native_scale_crop_contains_subject_and_fragment(self):
        im=sheet((1800,1200));ImageDraw.Draw(im).rectangle((345,240,420,330),fill='red')
        r=locate_contours(im,self.spec);self.assertEqual(len(r['regions']),6)
        region=r['regions'][0];part=crop_region(im,region);x,y=region['rect'][:2]
        self.assertEqual(part.getpixel((400-x,270-y)),(255,0,0,255))
    def test_catalog_plan_and_preview_no_approval_or_source_mutation(self):
        from tools.asset_manager.workflow import prepare
        s=self.source();before=self.c.export_registry();result=self.c.auto_locate(s['source_id'],contours=True)
        self.assertEqual(self.c.export_registry(),before)
        p=self.c.plan(s['source_id'],mode='auto',regions=result['regions'],detection=result)
        preview=prepare(self.c,source_id=s['source_id'],mode='auto',regions=p['regions'],detection=result)
        self.assertTrue(all(v['valid'] for v in preview['items']))
        self.assertTrue(all(not self.c.get('asset',a)['versions'] for a in self.group['asset_ids']))
        self.assertEqual(self.c.get('source',s['source_id']),s)

    def test_low_alpha_textured_background_not_counted_as_subject(self):
        im=sheet(opaque=True)
        # Nonzero alpha across the entire backdrop reproduces the old >75% rejection.
        pixels=list(im.get_flattened_data())
        im.putdata([(r,g,b,20+(i%11)) if (r,g,b)==(245,245,245) else (r,g,b,a) for i,(r,g,b,a) in enumerate(pixels)])
        before=im.tobytes();r=locate_contours(im,self.spec)
        self.assertEqual(r['status'],'NEEDS_REVIEW');self.assertEqual(len(r['regions']),6)
        self.assertEqual(r['foreground_method'],'alpha_background')
        self.assertGreater(r['background_alpha_threshold'],16)
        self.assertEqual(im.tobytes(),before)
        self.assertIn('框内原背景仍保留',r['message'])
        for region in r['regions']:validate(region,im.width,im.height);self.assertLessEqual(len(region['polygon']),128)
    def test_dense_background_with_no_alpha_separation_not_forced(self):
        im=sheet(opaque=True);im.putalpha(150)
        r=locate_contours(im,self.spec)
        self.assertEqual(r['status'],'FAILED');self.assertEqual(r['regions'],[])
    def test_adaptive_alpha_preview_preserves_interior_light_art(self):
        from tools.asset_manager.workflow import prepare
        im=sheet(opaque=True);im.putalpha(im.getchannel('A').point(lambda v:24))
        d=ImageDraw.Draw(im)
        for row in range(2):
            for col in range(3):
                x=35+190*col;y=35+190*row
                d.rectangle((x,y,x+75,y+85),fill=(60,100,140,255));d.rectangle((x+20,y+20,x+30,y+30),fill=(250,250,250,255))
        s=self.source(im);r=self.c.auto_locate(s['source_id'],contours=True)
        self.assertEqual(r['status'],'NEEDS_REVIEW')
        p=prepare(self.c,source_id=s['source_id'],mode='auto',regions=r['regions'],detection=r)
        self.assertTrue(all(v['valid'] for v in p['items']))
        part=Image.open(self.c.path(p['items'][0]['preview_files'][0]['file'])).convert('RGBA');x,y=r['regions'][0]['rect'][:2]
        self.assertEqual(part.getpixel((60-x,60-y)),(250,250,250,255))

    def test_baked_checkerboard_is_only_localized_not_removed(self):
        im=sheet(opaque=True);pixels=list(im.get_flattened_data());im.putdata([(232,232,232,255) if (r,g,b)==(245,245,245) and (i%600//6+i//600//6)%2 else (r,g,b,a) for i,(r,g,b,a) in enumerate(pixels)])
        before=im.tobytes();r=locate_contours(im,self.spec)
        self.assertEqual(r['status'],'NEEDS_REVIEW');self.assertEqual(len(r['regions']),6)
        self.assertEqual(r['foreground_method'],'light_background');self.assertEqual(im.tobytes(),before)
        self.assertIn('框内棋盘格或底色仍保留',r['message'])
        part=crop_region(im,r['regions'][0]);self.assertTrue(any(p[:3]==(232,232,232) and p[3]==255 for p in part.get_flattened_data()))
    def test_complex_or_dark_opaque_background_stays_rejected(self):
        dark=Image.new('RGBA',(600,400),(60,70,80,255))
        complex_image=sheet(opaque=True);ImageDraw.Draw(complex_image).rectangle((0,0,599,20),fill='red')
        for im in (dark,complex_image):
            r=locate_contours(im,self.spec);self.assertEqual(r['status'],'FAILED');self.assertEqual(r['regions'],[])
    def test_small_fragment_in_unfilled_last_column_attaches_to_nearby_subject(self):
        group=self.c.create_named('resource_icon_v1','五矿石','set',fixture.NAMES[:5],'sheet')
        spec=self.c.prompt('resource_icon_v1',{},set_id=group['set_id'])['frozen_spec']
        im=sheet(opaque=True);d=ImageDraw.Draw(im);d.rectangle((400,200,599,399),fill=(245,245,245,255))
        d.rectangle((225,225,440,310),fill='green');d.rectangle((447,260,453,266),fill='green')
        r=locate_contours(im,spec);self.assertEqual(r['status'],'NEEDS_REVIEW');self.assertEqual(len(r['regions']),5)
        self.assertEqual([v['asset_id'] for v in r['regions']],spec['asset_order'])
        self.assertGreater(r['regions'][-1]['rect'][0]+r['regions'][-1]['rect'][2],453)

    def test_coarse_overlap_refines_without_clipping_separate_appendages(self):
        im=sheet();d=ImageDraw.Draw(im)
        d.rectangle((200,0,399,399),fill=(0,0,0,0))
        d.rectangle((225,20,300,152),fill='green');d.line((225,152,225,195),fill='green',width=3)
        d.rectangle((225,225,300,340),fill='blue');d.line((300,163,300,225),fill='blue',width=3)
        before=im.tobytes();r=locate_contours(im,self.spec)
        self.assertEqual(r['status'],'NEEDS_REVIEW');self.assertEqual(r['contour_band_count'],24)
        self.assertEqual(len(r['regions']),6);self.assertEqual(im.tobytes(),before)
        self.assertFalse(any(intersect(a,b,*im.size) for i,a in enumerate(r['regions']) for b in r['regions'][i+1:]))
        for i,point,color in [(1,(225,185),(0,128,0,255)),(4,(300,175),(0,0,255,255))]:
            region=r['regions'][i];part=crop_region(im,region);x,y=region['rect'][:2]
            self.assertEqual(part.getpixel((point[0]-x,point[1]-y)),color)

import unittest
from PIL import Image
from tools.asset_manager.selection import validate,crop_region,intersect
from tools.asset_manager.model import AssetError
class PolygonTests(unittest.TestCase):
 def test_bent_selection_removes_neighbor_and_preserves_native_pixels(self):
  im=Image.new('RGBA',(10,10),'red');r={'rect':[0,0,10,10],'polygon':[[0,0],[10,0],[10,4],[4,4],[4,10],[0,10]]}
  out=crop_region(im,r);self.assertEqual(out.getpixel((8,8))[3],0);self.assertEqual(out.getpixel((2,8)),(255,0,0,255))
 def test_overlapping_bounds_disjoint_masks_and_shared_edge(self):
  a={'rect':[0,0,10,10],'polygon':[[0,0],[10,0],[0,10]]};b={'rect':[0,0,10,10],'polygon':[[10,0],[10,10],[0,10]]}
  self.assertFalse(intersect(a,b,10,10));self.assertTrue(intersect(a,a,10,10))
 def test_bad_shapes_rejected(self):
  for points in ([[0,0],[10,10],[0,10],[10,0]],[[0,0],[0,0],[10,10]],[[0,0],[11,0],[0,10]],[[0,0],[5,0],[10,0]]):
   with self.assertRaises(AssetError):validate({'rect':[0,0,10,10],'polygon':points},10,10)
 def test_rectangle_history_unchanged(self):
  im=Image.new('RGBA',(10,10),'blue');self.assertEqual(crop_region(im,{'rect':[2,2,4,4]}).tobytes(),im.crop((2,2,6,6)).tobytes())

class PolygonWorkflowTests(unittest.TestCase):
    from tests.test_asset_quick_confirm import QuickConfirmTests
    setUp=QuickConfirmTests.setUp
    preview=QuickConfirmTests.preview

    def test_polygon_survives_preview_confirmation_and_export(self):
        import copy,io
        from tools.asset_manager.workflow import confirm
        regions=copy.deepcopy(self.r);r=regions[0];x,y,w,h=r['rect']
        r['polygon']=[[x,y],[x+w,y],[x+w,y+h//2],[x+w//2,y+h//2],[x+w//2,y+h],[x,y+h]]
        source_bytes=self.c.path(self.s['file']).read_bytes() if 'file' in self.s else None
        frozen=copy.deepcopy(self.s['frozen_spec'])
        p=self.preview(regions);self.assertTrue(p['items'][0]['valid'],p['items'][0]['issues'])
        part=Image.open(self.c.path(p['items'][0]['preview_files'][0]['file'])).convert('RGBA')
        self.assertEqual(part.getpixel((w-1,h-1))[3],0)
        confirm(self.c,p['preview_id'],True)
        v=self.c.get('asset',r['asset_id'])['versions'][0]
        self.assertEqual(v['plan']['regions'][0]['polygon'],r['polygon'])
        self.assertEqual(self.c.get('source',self.s['source_id'])['frozen_spec'],frozen)
        runtime=Image.open(self.c.path(v['runtime']['files'][0]['file'])).convert('RGBA')
        self.assertEqual(runtime.getpixel((runtime.width-1,runtime.height-1))[3],0)
        if source_bytes is not None:self.assertEqual(self.c.path(self.s['file']).read_bytes(),source_bytes)

    def test_invalid_polygon_only_blocks_its_own_item(self):
        import copy
        regions=copy.deepcopy(self.r);r=regions[0];x,y,w,h=r['rect']
        r['polygon']=[[x,y],[x+w,y+h],[x+w,y],[x,y+h]]
        p=self.preview(regions)
        self.assertFalse(p['items'][0]['valid'])
        self.assertTrue(all(i['valid'] for i in p['items'][1:]))

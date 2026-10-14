"""Dedicated UI component profiles use the shared named-sheet/confirmation workflow."""
import io,tempfile,unittest
from pathlib import Path
from PIL import Image,ImageDraw
from tools.asset_manager.catalog import Catalog,PROJECT
from tools.asset_manager.sheets import regions
from tools.asset_manager.workflow import prepare,confirm

class BattleUIComponentsTests(unittest.TestCase):
 def setUp(self):
  t=tempfile.TemporaryDirectory(dir=PROJECT/'tests');self.addCleanup(t.cleanup);self.c=Catalog(Path(t.name)/'assets')
 def group(self,family='panel',names=None):
  return self.c.create_named('battle_ui_component_v1','战斗组件','asset_set',names or ['通用墨玉面板','战利品面板'],family=family,source_container='sheet')
 def prompt(self,g):return self.c.prompt(g['template_id'],{'object':g['name_zh'],'family':g['family']},set_id=g['set_id'])
 def test_panel_default_is_96_and_insets_are_frozen(self):
  g=self.group();s=self.prompt(g)['frozen_spec'];self.assertEqual(s['runtime_role'],'ui_component');self.assertEqual(s['runtime_profile']['frame_size'],[96,96]);self.assertEqual(s['runtime_profile']['nine_slice_insets'],[24]*4);self.assertEqual(s['source_cell_size'],[128,128]);self.assertEqual(s['asset_count'],2);self.assertEqual(s['frame_counts'],{'icon':1});self.assertEqual(s['sheet_semantics'],'independent_assets')
 def test_each_family_exports_the_declared_component_size(self):
  for family,size in [('panel',[96,96]),('button',[192,64]),('bar',[192,32]),('badge',[64,64])]:
   with self.subTest(family=family):self.assertEqual(self.prompt(self.group(family,[family]))['frozen_spec']['runtime_profile']['frame_size'],size)
 def test_confirm_batch_preserves_corner_pixels_and_names(self):
  g=self.group();p=self.prompt(g);s=p['frozen_spec'];rs=regions(s);grid=s['grid_spec'];w=grid['columns']*128+(grid['columns']-1)*16;h=grid['rows']*128+(grid['rows']-1)*16;im=Image.new('RGBA',(w,h));draw=ImageDraw.Draw(im)
  for i,r in enumerate(rs):
   x,y,_,_=r['rect'];draw.rectangle((x+16,y+16,x+111,y+111),fill=(20+i*40,30,40,255));draw.rectangle((x+16,y+16,x+111,y+111),outline=(120,150,80,255),width=4)
  out=io.BytesIO();im.save(out,format='PNG');source=self.c.upload('ui.png',out.getvalue(),g['template_id'],g['set_id'],p['prompt_id']);preview=prepare(self.c,source_id=source['source_id'],regions=rs,mode='grid');result=confirm(self.c,preview['preview_id'],True);self.assertTrue(all(a['status']=='approved' for a in result['assets']))
  for i,aid in enumerate(g['asset_ids']):
   a=self.c.get('asset',aid);self.assertEqual(a['name_zh'],s['asset_list'][i]['name_zh']);f=a['versions'][0]['runtime']['files'][0]
   with Image.open(self.c.path(f['file'])) as image:self.assertEqual(image.size,(96,96));self.assertEqual(image.getpixel((0,0)),(120,150,80,255));self.assertEqual(image.getpixel((48,48)),(20+i*40,30,40,255))
 def test_ui_prompt_allows_actual_component_borders_but_no_showcase(self):
  p=self.prompt(self.group());text=p['text'];self.assertIn('Requested component borders and fills are allowed',text);self.assertNotIn('No labels, numbering, borders,',text);self.assertIn('genuine alpha',text);self.assertIn('corner safety padding',text);self.assertIn('Reject and regenerate opaque backdrop',text);self.assertIn('not nine separate pictures',text);self.assertIn('NOT animation',text)
 def test_old_ui_profile_remains_small_and_frozen(self):
  s=self.c.specification('ui_state_v1');self.assertEqual(s['runtime_profile']['frame_size'],[24,24]);nine=self.c.specification('ui_state_v1',{'family':'nine_slice'});self.assertEqual(len(nine['cell_mapping']),9)

 def test_six_health_states_have_locked_complete_frames(self):
  names=self.c.templates["battle_ui_component_v1"]["families"]["bar_states"]["suggested_asset_names"];self.assertEqual(len(names),6);p=self.prompt(self.group("bar_states",names));s=p["frozen_spec"];self.assertEqual(s["asset_count"],6);self.assertEqual(s["runtime_profile"]["frame_size"],[192,32]);self.assertEqual(s["frame_counts"],{"icon":1});self.assertIn("same 192x32 viewport",p["text"]);self.assertIn("empty means no fill",p["text"])

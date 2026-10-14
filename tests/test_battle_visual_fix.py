"""Regression of actual background stacking, authored-facing and opaque checker Runtime rendering."""
import hashlib,io,json,re,unittest
from pathlib import Path
from PIL import Image,ImageDraw
from src.rendering.game_runtime import GameRuntimeAssets
from src.rendering.backdrop import matte
from tools.asset_manager.specs import export_spec
ROOT=Path(__file__).resolve().parents[1]
class VisualFixTests(unittest.TestCase):
 def test_background_image_above_positioned_fallback(self):
  css=(ROOT/'src/ui/pages/game/static/battle/battle.css').read_text();rule=re.search(r'(?:\.battle-scene )?\.battle-background\s*\{([^}]+)',css).group(1);self.assertIn('position:absolute',rule);self.assertIn('z-index:1',rule)
 def test_actual_rat_transparency_and_approved_original_preserved(self):
  assets=GameRuntimeAssets(ROOT/'assets');s=assets.sprite('monster.static.a160fd327595d',role='enemy');self.assertEqual(s['authoredFacing'],'left');url=s['actions']['idle']['frames'][0]['url'];data=assets.file('monster.static.a160fd327595d',url.rsplit('/',1)[1]);self.assertIsInstance(data,io.BytesIO);raw=data.getvalue();self.assertEqual(hashlib.sha256(raw).hexdigest(),url.rsplit('/',1)[1]);image=Image.open(io.BytesIO(raw));self.assertEqual(image.getpixel((13,27))[3],0)
  original=assets.frames('monster.static.a160fd327595d')[0][1];self.assertEqual(hashlib.sha256(original['path'].read_bytes()).hexdigest(),original['digest']);self.assertEqual(Image.open(original['path']).convert('RGBA').getpixel((13,27))[3],255)
 def test_neutral_subject_highlights_are_not_globally_keyed(self):
  im=Image.new('RGBA',(40,40),(225,225,225,255));d=ImageDraw.Draw(im);d.rectangle((8,8,32,32),fill=(40,30,10,255));d.rectangle((10,10,30,30),fill=(255,255,255,255));clean,n=matte(im);self.assertGreater(n,0);self.assertEqual(clean.getpixel((20,20))[3],255);self.assertEqual(clean.getpixel((0,0))[3],0)
 def test_transparent_boss_is_not_rekeyed(self):
  im=Image.new('RGBA',(40,40),(0,0,0,0));ImageDraw.Draw(im).ellipse((10,8,30,32),fill='white');clean,n=matte(im);self.assertEqual(n,0);self.assertEqual(im.tobytes(),clean.tobytes())
 def test_hero_192x256_all_actions_high_resolution_and_common_anchor(self):
  assets=GameRuntimeAssets(ROOT/'assets');anchors=[]
  for action in ('idle','attack','cast','hit','death'):
   s=assets.sprite('character.af8b2d2ce9282.'+action,role='player');self.assertEqual((s['width'],s['height']),(192,256));anchors.append(s['anchor'])
   f=assets.frames('character.af8b2d2ce9282.'+action)[0][1]
   with Image.open(f['path']) as im:
    box=im.getchannel('A').getbbox();self.assertGreater(box[2]-box[0],80)
  self.assertTrue(all(a=={'x':96,'y':232} for a in anchors))
 def test_character_export_policy_does_not_override_other_templates(self):
  templates=json.loads((ROOT/'assets/templates/templates.json').read_text())['templates'];t=next(x for x in templates if x['template_id']=='character_compact_v1')
  from tools.asset_manager.model import AssetError
  with self.assertRaises(AssetError):export_spec(t,{'runtime_role':'item_icon','output_mode':'icon'},'player_combat_profile')

 def test_derived_runtime_http_serves_png_and_rejects_unknown_digest(self):
  from src.transport.danding import create_app
  from uuid import uuid4
  assets=GameRuntimeAssets(ROOT/'assets');sprite=assets.sprite('monster.static.a160fd327595d',role='enemy');url=sprite['actions']['idle']['frames'][0]['url'].removeprefix('/game')
  http=create_app(lambda:None,str(uuid4()),lambda _:None,assets.file,'visual-fixture-only-token',secure=False,cookie_path='/');client=http.test_client();client.post('/login',data={'token':'visual-fixture-only-token'})
  response=client.get(url);self.assertEqual(response.status_code,200);self.assertEqual(response.mimetype,'image/png');self.assertEqual(hashlib.sha256(response.data).hexdigest(),url.rsplit('/',1)[1]);self.assertEqual(client.get(url.rsplit('/',1)[0]+'/'+'0'*64).status_code,404)

 def test_actual_attack_icon_matte_served_without_rewriting_approved_image(self):
  assets=GameRuntimeAssets(ROOT/'assets');aid='icon.resource.a2f9fea1475e0';original=assets.resolve(aid);before=original['path'].read_bytes();public=assets.icon(aid);self.assertNotEqual(public['digest'],original['digest']);data=assets.file(aid,public['digest']);self.assertIsInstance(data,io.BytesIO);self.assertEqual(hashlib.sha256(data.getvalue()).hexdigest(),public['digest']);im=Image.open(data).convert('RGBA');raw=Image.open(io.BytesIO(before)).convert('RGBA');self.assertGreater(im.getchannel('A').histogram()[0],raw.getchannel('A').histogram()[0]);self.assertEqual(original['path'].read_bytes(),before);self.assertIsNone(assets.file(aid,'0'*64))

 def test_scene_alpha_padding_is_only_readonly_display_metadata(self):
  assets=GameRuntimeAssets(ROOT/'assets');aid='scene.environment.af52d052e0c12.scene';original=assets.resolve(aid);before=original['path'].read_bytes();row=assets.icon(aid);self.assertEqual(row['content_box'],(21,11,299,168));self.assertEqual(row['digest'],original['digest']);self.assertEqual(original['path'].read_bytes(),before)

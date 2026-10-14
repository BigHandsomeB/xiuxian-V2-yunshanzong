import hashlib,io,unittest,tempfile
from pathlib import Path
from PIL import Image
from src.rendering.game_runtime import GameRuntimeAssets,ui_render
from src.rendering.game import _battle,bindings
from src.transport.danding import create_app
ROOT=Path(__file__).resolve().parents[1]
class BattleUISkinTests(unittest.TestCase):
 def test_all_nine_ui_bindings_are_guarded_readonly_runtime(self):
  assets=GameRuntimeAssets(ROOT/'assets');ui=_battle(assets,assets.snapshot())['ui'];self.assertEqual(len(ui),15)
  for role,row in ui.items():
   if role.startswith('health_'):continue
   with self.subTest(role=role):
    self.assertFalse(row['fallback']);aid=row['asset_id'];original=assets.resolve(aid);before=original['path'].read_bytes();public=row['asset'];key=public['url'].rsplit('/',1)[1];blob=assets.file(aid,key);self.assertIsInstance(blob,io.BytesIO);im=Image.open(blob);self.assertEqual(im.size,(public['width'],public['height']));self.assertEqual(hashlib.sha256(blob.getvalue()).hexdigest(),key);self.assertEqual(original['path'].read_bytes(),before)
 def test_button_checker_removed_and_nine_slice_insets_fit(self):
  assets=GameRuntimeAssets(ROOT/'assets')
  for role in ['primary','secondary']:
   aid=bindings()['battle_ui'][role];original=assets.resolve(aid);public=assets.icon(aid);raw=Image.open(original['path']).convert('RGBA');blob=assets.file(aid,public['digest']);im=Image.open(blob).convert('RGBA');self.assertLess(sum(im.getchannel('A').histogram()[200:]),sum(raw.getchannel('A').histogram()[200:]));t,r,b,l=public['nine_slice_insets'];self.assertLess(l+r,im.width);self.assertLess(t+b,im.height)
 def test_missing_ui_retains_honest_fallback(self):
  with tempfile.TemporaryDirectory() as p:
   ui=_battle(GameRuntimeAssets(p),{})['ui'];self.assertEqual(len(ui),15);self.assertTrue(all(row['fallback'] and row['asset'] is None for row in ui.values()))
 def test_normalized_ui_http_png_and_bad_digest(self):
  assets=GameRuntimeAssets(ROOT/'assets');aid=bindings()['battle_ui']['primary'];public=assets.icon(aid);app=create_app(lambda:None,'skin-test',lambda _:None,assets.file,'battle-ui-skin-test-fixture-only-token',secure=False,cookie_path='/');client=app.test_client();client.post('/login',data={'token':'battle-ui-skin-test-fixture-only-token'});path=public['url'].removeprefix('/play');r=client.get(path);self.assertEqual(r.status_code,200);self.assertEqual(r.mimetype,'image/png');self.assertEqual(hashlib.sha256(r.data).hexdigest(),public['digest']);self.assertEqual(client.get('/runtime/'+aid+'/'+'0'*64).status_code,404)

"""Real bound profession/function icons must not display their baked neutral backdrop."""
import hashlib,io,json,unittest
from pathlib import Path
from PIL import Image
from src.rendering.game_runtime import GameRuntimeAssets
from src.rendering.backdrop import matte
ROOT=Path(__file__).resolve().parents[1]
ROLES=['train','breakthrough','basic_attack','claim','map','tower','dungeon','boss','exploration','event','battle_log','technique','portrait_player','portrait_farm','portrait_cook','portrait_gather','portrait_alchemy','portrait_build']
class UsedIconTransparencyTests(unittest.TestCase):
 def test_bound_icons_have_transparent_backdrop_and_preserve_artwork(self):
  assets=GameRuntimeAssets(ROOT/'assets');bindings=json.loads((ROOT/'src/rendering/game-assets.json').read_text())['system_icons'];manifest=(ROOT/'assets/manifest.json').read_bytes()
  for role in ROLES:
   with self.subTest(role=role):
    aid=bindings[role];raw=assets.resolve(aid);before=raw['path'].read_bytes();source=Image.open(io.BytesIO(before)).convert('RGBA');expected,count=matte(source);self.assertGreater(count,0)
    public=assets.icon(aid);output=assets.file(aid,public['digest']);data=output.read() if hasattr(output,'read') else output.read_bytes();actual=Image.open(io.BytesIO(data)).convert('RGBA');self.assertEqual(actual.size,source.size)
    removed=[i for i,(old,new) in enumerate(zip(source.get_flattened_data(),expected.get_flattened_data())) if old[3]>0 and new[3]==0];self.assertTrue(all(list(actual.get_flattened_data())[i][3]==0 for i in removed),'Baked backdrop still opaque')
    self.assertTrue(all(a==o for a,o,e in zip(actual.get_flattened_data(),source.get_flattened_data(),expected.get_flattened_data()) if e[3]>0),'Subject pixels changed')
    self.assertEqual(hashlib.sha256(data).hexdigest(),public['digest']);self.assertEqual(raw['path'].read_bytes(),before);self.assertIsNone(assets.file(aid,'0'*64))
  self.assertEqual((ROOT/'assets/manifest.json').read_bytes(),manifest)
 def test_unaffected_life_stat_is_not_reprocessed(self):
  assets=GameRuntimeAssets(ROOT/'assets');bindings=json.loads((ROOT/'src/rendering/game-assets.json').read_text())['system_icons'];aid=bindings['hp'];self.assertEqual(assets.icon(aid)['digest'],assets.resolve(aid)['digest'])

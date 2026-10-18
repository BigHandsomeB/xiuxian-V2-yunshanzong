"""Published independent frames can enter the battle renderer without Source paths."""
import hashlib,json,tempfile,unittest
from pathlib import Path
from src.rendering.game_runtime import GameRuntimeAssets

class GameRuntimeTests(unittest.TestCase):
    def test_real_manifest_frames_anchor_action_and_digest_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'runtime').mkdir();files=[]
            for i in (1,2):
                content=f'published-frame-{i}'.encode();path=root/f'runtime/f{i}.png';path.write_bytes(content)
                files.append({'file':f'runtime/f{i}.png','width':128,'height':128,'sha256':hashlib.sha256(content).hexdigest(),'action':'idle','frame':i})
            row={'version':1,'files':files,'anchor':{'type':'bottom_center','baseline_from_bottom':24}}
            (root/'manifest.json').write_text(json.dumps({'schema_version':1,'assets':{'character.test':row}}))
            assets=GameRuntimeAssets(root);self.assertIsNone(assets.resolve('character.test'))
            sprite=assets.sprite('character.test');self.assertEqual(sprite['anchor'],{'x':64,'y':104})
            self.assertEqual(sprite['actions']['idle']['frameCount'],2)
            self.assertEqual(sprite['actions']['idle']['frames'][0]['x'],0)
            self.assertTrue(sprite['actions']['idle']['frames'][0]['url'].startswith('/game/runtime/'))
            for frame in files:self.assertIsNotNone(assets.file('character.test',frame['sha256']))
            self.assertIsNone(assets.file('character.test','0'*64))
            (root/'runtime/f1.png').write_bytes(b'corrupted');self.assertIsNone(assets.file('character.test',files[0]['sha256']))
            row['anchor']=None;(root/'manifest.json').write_text(json.dumps({'schema_version':1,'assets':{'character.test':row}}));self.assertIsNone(assets.sprite('character.test'))
            row['anchor']={'type':'bottom_center','baseline_from_bottom':24}
            files[0]['file']='../source.png';(root/'manifest.json').write_text(json.dumps({'schema_version':1,'assets':{'character.test':row}}))
            self.assertIsNone(assets.sprite('character.test'))


class RuntimeObservationTests(unittest.TestCase):
    def test_removed_runtime_is_rechecked_on_next_response(self):
        from src.rendering.assets import observation
        from src.rendering.game import _icon, projection
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'runtime').mkdir()
            path=root/'runtime/icon.png';content=b'approved';path.write_bytes(content)
            snapshot={'icon.test':{'version':'v1','files':[{'file':'runtime/icon.png','width':1,'height':1,'sha256':hashlib.sha256(content).hexdigest()}]}}
            assets=GameRuntimeAssets(root)
            @projection
            def render():
                first=_icon('icon.test',assets,snapshot)
                first['fallback']=True  # One widget cannot change another widget's result.
                return _icon('icon.test',assets,snapshot)
            self.assertFalse(render()['fallback'])
            path.unlink()
            self.assertTrue(render()['fallback'])

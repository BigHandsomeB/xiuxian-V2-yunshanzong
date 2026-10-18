"""Only static artwork is reused; configuration and battle identities invalidate it."""
import copy,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from src.rendering.desktop_artwork import DesktopArtwork

class DesktopArtworkTests(unittest.TestCase):
    def test_dynamic_facts_reuse_artwork_and_enemy_refreshes_battle_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest=Path(tmp)/'manifest.json';manifest.write_text('{}')
            cache=DesktopArtwork(SimpleNamespace(root=Path(tmp)));cache.paths=(manifest,)
            view={'holdings':{'wood':1},'buildings':{},'equipment':{'instances':[]},'techniques':{'catalog':[]},'combat':{'player':{'asset_id':'player'},'enemy':{'asset_id':'enemy'},'encounter':{'background_asset_id':'scene'}}}
            with patch('src.rendering.desktop_artwork.present',return_value={'icons':{},'battle':{'assets':{'enemy':'old'}}}) as full,patch('src.rendering.desktop_artwork.battle_artwork',return_value={'enemy':'new'}) as battle:
                original=cache(view);changed=copy.deepcopy(view);changed['holdings']['wood']=999;changed['combat']['player']['hp']=1
                self.assertIs(cache(changed),original);self.assertEqual(full.call_count,1)
                changed['combat']['enemy']['asset_id']='new'
                fresh=cache(changed);self.assertEqual(full.call_count,1);battle.assert_called_once()
                self.assertEqual(fresh['battle']['assets'],{'enemy':'new'});self.assertEqual(original['battle']['assets'],{'enemy':'old'})
                manifest.write_text('{"changed":true}');cache(changed);self.assertEqual(full.call_count,2)
                cache.invalidate();cache(changed);self.assertEqual(full.call_count,3)

    def test_restart_cache_corruption_and_explicit_reload(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);manifest=root/'manifest.json';manifest.write_text('{}')
            path=root/'artwork.json';assets=SimpleNamespace(root=root)
            view={'holdings':{},'buildings':{},'equipment':{'instances':[]},'techniques':{'catalog':[]}}
            artwork={'schema_version':1,'mode':'icon','icons':{},'system_icons':{},'resource_overview':[],
                     'equipment_icons':{},'technique_icons':{},'building_icons':{},'screens':{},'battle':{'assets':{}}}
            def new():
                cache=DesktopArtwork(assets,path);cache.paths=(manifest,);return cache
            with patch('src.rendering.desktop_artwork.present',return_value=artwork) as full:
                self.assertEqual(new()(view),artwork);self.assertEqual(full.call_count,1)
                self.assertEqual(new()(view),artwork);self.assertEqual(full.call_count,1)
                self.assertNotIn('view',json.loads(json.loads(path.read_text())['body'])['projection'])
                cache=new();cache.invalidate();cache(view);self.assertEqual(full.call_count,2)
                record=json.loads(path.read_text());record['sha256']='bad';path.write_text(json.dumps(record))
                new()(view);self.assertEqual(full.call_count,3)
                manifest.write_text('{"new":1}');new()(view);self.assertEqual(full.call_count,4)
                path.write_text('not JSON');new()(view);self.assertEqual(full.call_count,5)

    def test_cache_write_failure_does_not_block_game(self):
        with tempfile.TemporaryDirectory() as tmp:
            assets=SimpleNamespace(root=Path(tmp));cache=DesktopArtwork(assets,Path(tmp)/'missing/artwork.json')
            view={'holdings':{},'buildings':{}}
            with patch('src.rendering.desktop_artwork.present',return_value={'icons':{}}):
                self.assertEqual(cache(view),{'icons':{}})

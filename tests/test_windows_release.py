"""Windows exports contain public files only; frozen maker launches the same executable."""
import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from tools.release.build_windows import ROOT,public_files


class WindowsReleaseTests(unittest.TestCase):
    def test_export_excludes_saves_credentials_maker_history_and_intermediates(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.tmp') as folder:
            root=Path(folder)
            files=['README.md','.gitignore','.env','src/game.py','tools/entry.py','tests/test_public.py',
                   'assets/manifest.json','assets/runtime/icon/a.png','assets/templates/templates.json',
                   'assets/registry/asset-registry.json','assets/registry/published-catalog.json',
                   'assets/registry/catalog.sqlite3','assets/registry/gameplay-notes.json',
                   'assets/source/private.png','assets/master/private.png','assets/components/private.png',
                   '.game/danding.sqlite3','.asset-manager/Cookies','tools/.env','src/__pycache__/game.pyc']
            for name in files:
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'fixture')
            result={p.relative_to(root).as_posix() for p in public_files(root)}
            self.assertEqual(result,set(files[:2]+files[3:11]))
    def test_frozen_maker_launches_same_executable_with_fixed_argument(self):
        from tools.asset_manager.launch import launch
        with patch('sys.frozen',True,create=True),patch('sys.executable','C:/fixture/YunshanZong.exe'),patch('tools.asset_manager.launch.subprocess.Popen') as process:
            launch();self.assertEqual(process.call_args.args[0],['C:/fixture/YunshanZong.exe','--asset-manager'])
            self.assertNotIn('shell',process.call_args.kwargs)

"""Storage projection uses isolated files; never changes real artwork."""
import json, os, tempfile, unittest
from pathlib import Path
from tools.asset_manager.storage import usage
from tools.asset_manager.catalog import PROJECT
from tools.asset_manager.web import create_app

class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=PROJECT/'tests');self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.root=self.base/'assets';self.root.mkdir()
    def put(self,name,data):
        p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data);return p
    def test_totals_include_actual_files_and_old_builds(self):
        self.put('source/files/a.png',b'x'*1200);self.put('runtime/id/v1/old.png',b'y'*30);self.put('runtime/id/v1/current.png',b'y'*90);self.put('registry/catalog.db',b'm'*20);self.put('manifest.json',b'{}')
        data=usage(self.root);groups={g['category']:g for g in data['categories']}
        self.assertEqual((data['file_count'],data['size_bytes']),(5,1342));self.assertEqual(groups['runtime']['file_count'],2);self.assertEqual(groups['metadata']['size_bytes'],22);self.assertEqual(data['allocated_bytes'],sum(g['allocated_bytes'] for g in data['categories']));self.assertFalse(data['partial']);self.assertGreater(data['volume']['total_bytes'],0)
    def test_empty_workspace_valid(self):
        d=usage(self.root);self.assertEqual(d['file_count'],0);self.assertEqual(d['size_bytes'],0);self.assertFalse(d['partial'])
    def test_symlink_files_and_directories_not_followed(self):
        external=self.base/'outside';external.mkdir();(external/'large.bin').write_bytes(b'x'*5000)
        (self.root/'escape').symlink_to(external,target_is_directory=True);(self.root/'escape.bin').symlink_to(external/'large.bin')
        d=usage(self.root);self.assertEqual(d['file_count'],0);self.assertEqual(d['skipped_links_or_special'],2)
    def test_hardlinks_not_double_counted(self):
        p=self.put('source/files/a.png',b'x'*100);os.link(p,self.root/'source/files/b.png');d=usage(self.root);self.assertEqual(d['size_bytes'],100);self.assertEqual(d['file_count'],1);self.assertEqual(d['duplicate_links'],1)
    def test_sparse_size_is_separate_from_disk_allocation(self):
        p=self.put('source/sparse.png',b'')
        with p.open('wb') as f:f.truncate(2*1024*1024)
        d=usage(self.root);self.assertEqual(d['size_bytes'],2*1024*1024);self.assertLess(d['allocated_bytes'],d['size_bytes'])
    def test_scan_limit_reports_partial(self):
        self.put('one',b'1');self.put('two',b'2');d=usage(self.root,max_entries=1);self.assertTrue(d['partial']);self.assertEqual(d['file_count'],1)
    def test_authenticated_read_only_endpoint(self):
        app=create_app(self.root,'x'*32);c=app.test_client();self.assertEqual(c.get('/api/storage').status_code,401)
        files={p.relative_to(self.root):p.read_bytes() for p in self.root.rglob('*') if p.is_file()};r=c.get('/api/storage?path=/etc',headers={'Authorization':'Bearer '+'x'*32});self.assertEqual(r.status_code,200);self.assertIn('allocated_bytes',r.get_json());self.assertEqual(files,{p.relative_to(self.root):p.read_bytes() for p in self.root.rglob('*') if p.is_file()});self.assertIn('data-page="storage"',c.get('/',headers={'Authorization':'Bearer '+'x'*32}).get_data(as_text=True))

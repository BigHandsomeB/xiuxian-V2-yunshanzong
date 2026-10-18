"""Source byte retirement preserves provenance, crops and published game outputs."""
import json
import unittest
from unittest.mock import patch
from tests import test_asset_quick_confirm as fixtures
from tools.asset_manager.workflow import confirm, prepare
from tools.asset_manager.model import AssetError


class SourceCleanupTests(unittest.TestCase):
    setUp = fixtures.QuickConfirmTests.setUp
    preview = fixtures.QuickConfirmTests.preview

    def test_published_sheet_removes_original_and_keeps_rebuild_and_replay(self):
        preview = self.preview()
        result = confirm(self.c, preview['preview_id'], True)
        source = self.c.get('source', self.s['source_id'])
        self.assertTrue(source['file_deleted_at'])
        self.assertFalse(self.c.path(source['file']).exists())
        self.assertEqual(source['sha256'], self.s['sha256'])
        self.assertTrue(result['manifest_updated'])
        self.assertEqual(confirm(self.c, preview['preview_id'], True), result)
        aid = self.g['asset_ids'][0]
        self.c.build(aid, 1)
        retry = prepare(self.c, targets=[dict(asset_id=aid, version=1)])
        self.assertTrue(retry['items'][0]['valid'])
        confirm(self.c, retry['preview_id'], True)
        with self.assertRaisesRegex(AssetError, '原图已清理'):
            self.c.source_image(source)
        self.assertEqual(self.c.clean_source_files()['deleted'], 0)

    def test_partial_batch_keeps_original(self):
        preview = self.preview()
        confirm(self.c, preview['preview_id'], True, [self.g['asset_ids'][-1]])
        self.assertTrue(self.c.path(self.s['file']).exists())

    def test_publish_failure_keeps_original_until_retry(self):
        preview = self.preview()
        atomic = self.c.atomic
        def fail(path, data):
            if path == 'manifest.json':
                raise OSError('disk full')
            return atomic(path, data)
        with patch.object(self.c, 'atomic', side_effect=fail):
            result = confirm(self.c, preview['preview_id'], True)
        self.assertFalse(result['manifest_updated'])
        self.assertTrue(self.c.path(self.s['file']).exists())
        self.assertTrue(confirm(self.c, preview['preview_id'], True)['manifest_updated'])
        self.assertFalse(self.c.path(self.s['file']).exists())

    def test_explicit_existing_cleanup_preserves_metadata_and_blocks_recrop(self):
        before = json.loads(self.c.path('manifest.json').read_text())
        result = self.c.clean_source_files(all_originals=True)
        self.assertEqual(result['deleted'], 1)
        self.assertGreater(result['bytes_freed'], 0)
        self.assertEqual(result['errors'], [])
        self.assertEqual(json.loads(self.c.path('manifest.json').read_text()), before)
        self.assertEqual(self.c.get('source', self.s['source_id'])['original_name'], 'sheet.png')
        with self.assertRaisesRegex(AssetError, '原图已清理'):
            self.preview()

    def test_corrupt_output_keeps_original(self):
        with patch.object(self.c, 'clean_source_files'):
            confirm(self.c, self.preview()['preview_id'], True)
        aid = self.g['asset_ids'][0]
        runtime = self.c.get('asset', aid)['versions'][0]['runtime']['files'][0]
        self.c.path(runtime['file']).write_bytes(b'broken')
        result = self.c.clean_source_files()
        self.assertEqual(result['deleted'], 0)
        self.assertEqual(len(result['errors']), 1)
        self.assertTrue(self.c.path(self.s['file']).exists())

    def test_pending_preview_keeps_original_until_confirmation(self):
        pending = self.preview()
        with patch.object(self.c, 'clean_source_files'):
            confirm(self.c, self.preview()['preview_id'], True)
        self.assertEqual(self.c.clean_source_files()['deleted'], 0)
        self.assertTrue(self.c.path(self.s['file']).exists())
        with self.c.transaction() as conn:
            saved = self.c.get('preview', pending['preview_id'], conn)
            saved['expires_at'] = '2000-01-01T00:00:00+00:00'
            self.c.put('preview', saved['preview_id'], saved, conn)
        self.assertEqual(self.c.clean_source_files()['deleted'], 1)

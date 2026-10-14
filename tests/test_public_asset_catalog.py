"""Public-only catalogue works without the private production database."""
import json
import tempfile
import unittest
from pathlib import Path
from src.data.public_asset_catalog import read_catalog
from src.rendering.asset_catalog import metadata
from src.application.catalog_notes import CatalogNotes


class PublicCatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'registry').mkdir()
        self.snapshot = {'icon.resource.example': {'version': 1}}
        self.group = {'set_id': 'asset_set.example', 'name': '公开素材', 'category': 'other',
                      'grade': None, 'items': [{'asset_id': 'icon.resource.example',
                                              'name': '灵草', 'category': 'resource', 'version': 1}]}
        self.path = self.root / 'registry/published-catalog.json'
        self.path.write_text(json.dumps({'schema_version': 1, 'groups': [self.group]}))
        (self.root / 'manifest.json').write_text(json.dumps({'schema_version': 1, 'assets': self.snapshot}))

    def test_catalog_without_database(self):
        result = metadata(self.root, self.snapshot)
        self.assertTrue(result['available'])
        self.assertEqual(result['groups'][0]['items'][0]['name'], '灵草')
        self.assertFalse((self.root / 'registry/catalog.sqlite3').exists())

    def test_name_editor_without_database(self):
        notes = CatalogNotes(self.root, lambda: set(self.snapshot))
        self.assertEqual(notes.name('icon.resource.example'), '灵草')
        self.assertEqual(notes.name('unknown'), 'unknown')

    def test_old_version_and_unpublished_items_are_hidden(self):
        self.assertEqual(read_catalog(self.root, {'icon.resource.example': {'version': 2}})['groups'], [])
        self.assertEqual(read_catalog(self.root, {})['groups'], [])

    def test_corrupt_index_is_optional(self):
        self.path.write_text('not json')
        self.assertEqual(metadata(self.root, self.snapshot), {'available': False, 'groups': []})

    def test_symlink_index_is_rejected(self):
        copy = self.root / 'copy.json'
        self.path.rename(copy)
        self.path.symlink_to(copy)
        self.assertFalse(read_catalog(self.root, self.snapshot)['available'])

    def test_outputs_do_not_mutate_future_queries(self):
        first = metadata(self.root, self.snapshot)
        first['groups'][0]['items'][0]['name'] = 'changed'
        self.assertEqual(metadata(self.root, self.snapshot)['groups'][0]['items'][0]['name'], '灵草')

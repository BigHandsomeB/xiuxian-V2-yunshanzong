"""Backup CAS and corruption checks, isolated from the live save."""
import copy
from pathlib import Path
import sqlite3
import tempfile
import unittest
from uuid import uuid4

from src.core.save.backup import BackupStore, BackupConflict, validate_save
from src.core.save.codec import CorruptSaveError
from src.core.save.sqlite import V2_ROOT
from src.core.validation import ValidationError
from tests.fixtures.persistence import state


def snapshot(raw, previous=None, version=None):
    return {'formatVersion': 1, 'saveId': raw['save_id'], 'version': version or (previous['version'] + 1 if previous else 1),
            'updatedAt': 1000, 'commitId': str(uuid4()), 'ancestors': [previous['commitId'], *previous['ancestors']] if previous else [],
            'source': 'server', 'state': copy.deepcopy(raw)}


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=V2_ROOT/'tests')
        self.root = Path(self.tmp.name)
        self.path = self.root/'backup.sqlite3'
        self.store = BackupStore(self.path, self.root)
        self.raw = state().to_dict()
        self.save = self.raw['save_id']
        self.first = snapshot(self.raw)

    def tearDown(self):
        self.tmp.cleanup()

    def test_read_does_not_initialize_or_write(self):
        self.assertIsNone(self.store.read(self.save))
        self.assertFalse(self.path.exists())

    def test_roundtrip_private_file_and_exact_retry(self):
        self.store.put(self.save, self.first, 0)
        self.assertEqual(self.store.read(self.save), self.first)
        self.assertEqual(self.store.put(self.save, self.first, 0), self.first)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_stale_base_does_not_replace_current(self):
        self.store.put(self.save, self.first, 0)
        second = snapshot(self.raw, self.first)
        with self.assertRaises(BackupConflict) as conflict:
            self.store.put(self.save, second, 0)
        self.assertEqual(conflict.exception.current_version, 1)
        self.assertEqual(self.store.read(self.save), self.first)

    def test_rejected_first_put_leaves_readable_empty_store(self):
        with self.assertRaises(BackupConflict) as conflict:
            self.store.put(self.save, self.first, 9)
        self.assertEqual(conflict.exception.current_version, 0)
        self.assertIsNone(self.store.read(self.save))
        self.store.put(self.save, self.first, 0)
        self.assertEqual(self.store.read(self.save), self.first)

    def test_same_version_distinct_devices_are_conflict(self):
        self.store.put(self.save, self.first, 0)
        branch = snapshot(self.raw)
        branch['state']['domains']['fixture']['count'] = 17
        with self.assertRaises(BackupConflict):
            self.store.put(self.save, branch, 1)
        self.assertEqual(self.store.read(self.save), self.first)

    def test_higher_version_distinct_branch_is_conflict(self):
        self.store.put(self.save, self.first, 0)
        branch = snapshot(self.raw, version=9)
        with self.assertRaises(BackupConflict):
            self.store.put(self.save, branch, 1)
        self.assertEqual(self.store.read(self.save), self.first)

    def test_explicit_descendant_and_previous_retained(self):
        self.store.put(self.save, self.first, 0)
        next_save = snapshot(self.raw, self.first)
        self.store.put(self.save, next_save, 1)
        with sqlite3.connect(self.path) as db:
            previous = db.execute('SELECT previous_body FROM backups').fetchone()[0]
        self.assertIn(self.first['commitId'], previous)

    def test_invalid_or_private_payload_rejected_before_creation(self):
        for key in ('csrf', 'session', 'xianxia-game-pending-v1'):
            bad = copy.deepcopy(self.first)
            bad['state']['domains']['fixture'][key] = 'private'
            with self.assertRaises(ValidationError):
                self.store.put(self.save, bad, 0)
        self.assertFalse(self.path.exists())

    def test_future_schema_identity_and_noninteger_versions_rejected(self):
        for key, value in [('formatVersion', 2), ('version', True), ('version', 2**53), ('ancestors', [{}]), ('saveId', str(uuid4()))]:
            bad = {**self.first, key: value}
            with self.assertRaises(ValidationError):
                validate_save(bad, self.save)

    def test_checksum_corruption_is_not_silent_empty_save(self):
        self.store.put(self.save, self.first, 0)
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE backups SET body='{}'")
        with self.assertRaises(CorruptSaveError):
            self.store.read(self.save)

    def test_concurrent_connections_only_one_cas_wins(self):
        from concurrent.futures import ThreadPoolExecutor
        contenders = [snapshot(self.raw), snapshot(self.raw)]
        def put(value):
            try:
                BackupStore(self.path, self.root).put(self.save, value, 0)
                return True
            except BackupConflict:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sum(pool.map(put, contenders)), 1)

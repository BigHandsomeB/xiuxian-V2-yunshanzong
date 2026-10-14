"""Independent backup snapshots with CAS; never opens the gameplay database."""
import os
import sqlite3

from src.core.save.codec import canonical, parse, sha, CorruptSaveError, PersistenceError
from src.core.save.sqlite import database_path
from src.core.state.envelope import StateEnvelope
from src.core.validation import ValidationError, uuid4_id

MAX_SAVE_BYTES = 2 * 1024 * 1024
MAX_VERSION = 2**53 - 1
SAVE_FIELDS = {'formatVersion', 'saveId', 'version', 'updatedAt', 'commitId', 'ancestors', 'source', 'state'}
PRIVATE_FIELDS = {'csrf', 'session', 'xianxia-game-pending-v1', '__proto__', 'prototype', 'constructor'}


class BackupConflict(Exception):
    def __init__(self, version):
        self.current_version = version


def validate_save(value, save_id):
    """Validate the transport-free envelope. Domain validation belongs to Application."""
    if type(value) is not dict or set(value) != SAVE_FIELDS:
        raise ValidationError('invalid backup fields')
    if type(value['formatVersion']) is not int or value['formatVersion'] != 1:
        raise ValidationError('unsupported backup format')
    if value['saveId'] != save_id or value['source'] not in ('server', 'import'):
        raise ValidationError('backup identity/source mismatch')
    uuid4_id(save_id, 'backup saveId')
    uuid4_id(value['commitId'], 'backup commitId')
    for key in ('version', 'updatedAt'):
        if type(value[key]) is not int or not (1 if key == 'version' else 0) <= value[key] <= MAX_VERSION:
            raise ValidationError('invalid backup number')
    ancestors = value['ancestors']
    if type(ancestors) is not list or len(ancestors) > 128 or any(type(a) is not str for a in ancestors) or len(set(ancestors)) != len(ancestors):
        raise ValidationError('invalid backup ancestry')
    for ancestor in ancestors:
        uuid4_id(ancestor, 'backup ancestor')
        if ancestor == value['commitId']:
            raise ValidationError('cyclic backup ancestry')
    def check(item, depth=0):
        if depth > 64:
            raise ValidationError('backup nesting too deep')
        if type(item) is dict:
            if PRIVATE_FIELDS.intersection(item):
                raise ValidationError('private request data is not a save')
            for part in item.values():
                check(part, depth + 1)
        elif type(item) is list:
            for part in item:
                check(part, depth + 1)
    check(value)
    state = StateEnvelope.from_dict(value['state'])
    if state.save_id != save_id or state.save_schema_version != 1:
        raise ValidationError('backup state identity/schema mismatch')
    if len(canonical(value).encode()) > MAX_SAVE_BYTES:
        raise ValidationError('backup too large')
    return state


class BackupStore:
    def __init__(self, path, root):
        self.path = database_path(path, root)

    def _row(self, row):
        if row is None:
            return None
        body, digest = row
        if sha(body) != digest:
            raise CorruptSaveError('backup checksum mismatch')
        try:
            value = parse(body)
            validate_save(value, value.get('saveId') if type(value) is dict else None)
            return value
        except (ValidationError, TypeError, ValueError) as exc:
            raise CorruptSaveError('invalid backup snapshot') from exc

    def read(self, save_id):
        if not self.path.exists():
            return None
        try:
            with sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True, timeout=2) as db:
                return self._row(db.execute('SELECT body,digest FROM backups WHERE save_id=?', (save_id,)).fetchone())
        except sqlite3.Error as exc:
            raise PersistenceError('backup unavailable') from exc

    def put(self, save_id, value, base_version):
        validate_save(value, save_id)
        if type(base_version) is not int or not 0 <= base_version <= MAX_VERSION:
            raise ValidationError('invalid baseVersion')
        body = canonical(value)
        try:
            # Initialize this separate store only on an explicit PUT, with private permissions.
            descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            os.close(descriptor)
            with sqlite3.connect(self.path, timeout=2, isolation_level=None) as db:
                db.execute('PRAGMA synchronous=FULL')
                db.execute('CREATE TABLE IF NOT EXISTS backups (save_id TEXT PRIMARY KEY, body TEXT NOT NULL, digest TEXT NOT NULL, previous_body TEXT)')
                db.execute('BEGIN IMMEDIATE')
                current = self._row(db.execute('SELECT body,digest FROM backups WHERE save_id=?', (save_id,)).fetchone())
                version = current['version'] if current else 0
                # A lost response can retry the exact current commit without a second write.
                if current and current['commitId'] == value['commitId'] and canonical(current) == body:
                    db.execute('COMMIT')
                    return current
                if base_version != version or value['version'] <= version or (current and current['commitId'] not in value['ancestors']):
                    raise BackupConflict(version)
                db.execute('INSERT INTO backups VALUES (?,?,?,?) ON CONFLICT(save_id) DO UPDATE SET body=excluded.body,digest=excluded.digest,previous_body=excluded.previous_body',
                           (save_id, body, sha(body), canonical(current) if current else None))
                db.execute('COMMIT')
                return value
        except (sqlite3.Error, OSError) as exc:
            raise PersistenceError('backup unavailable') from exc

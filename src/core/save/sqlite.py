"""@module core/save/sqlite
@purpose Explicit isolated SQLite adapter: atomic snapshots/receipts, bounded recovery.
@depends core/save/codec, core/state, core/validation, standard library
@usedBy application/persistent, tests/core/test_persistence
@see ./INDEX.md
"""
from contextlib import contextmanager
from dataclasses import dataclass, replace
import os
from pathlib import Path
import sqlite3
import stat
from urllib.parse import quote

from src.core.save.codec import (CorruptSaveError, PersistenceError, StoredReceipt,
                                 decode_state, encode_state, wall_claim)
from src.core.validation import ConflictError, ValidationError, integer, uuid4_id
from src.core.save.recovery import row_fingerprint

DB_LAYOUT_VERSION = 2
V2_ROOT = Path(__file__).resolve().parents[3]
V1_ROOT = (V2_ROOT.parent / 'legacy-reference').resolve()
COLUMNS = 'save_id,generation,revision,save_schema_version,data_schema_version,content_version,body,digest,continuation,wall_claim_ms,wall_claim_digest'
SCHEMA = (
    'CREATE TABLE current ('
    'save_id TEXT PRIMARY KEY, generation INTEGER NOT NULL, revision INTEGER NOT NULL,'
    'save_schema_version INTEGER NOT NULL, data_schema_version INTEGER NOT NULL,'
    'content_version TEXT NOT NULL, body TEXT NOT NULL, digest TEXT NOT NULL, continuation TEXT,'
    'wall_claim_ms INTEGER NOT NULL, wall_claim_digest TEXT NOT NULL)',
    'CREATE TABLE previous AS SELECT * FROM current WHERE 0',
    'CREATE UNIQUE INDEX previous_save ON previous(save_id)',
    'CREATE TABLE receipts (save_id TEXT NOT NULL, generation INTEGER NOT NULL,'
    'request_id TEXT NOT NULL, intent TEXT NOT NULL, committed_revision INTEGER NOT NULL,'
    'body TEXT NOT NULL, digest TEXT NOT NULL, PRIMARY KEY(save_id,generation,request_id),'
    'FOREIGN KEY(save_id) REFERENCES current(save_id))',
)


def database_path(path, allowed_root):
    """Real path containment plus symlink/hardlink checks, including SQLite sidecars.

    A tool-level guard, not a barrier against hostile concurrent filesystem changes.
    Caller supplies an existing trusted directory, never cwd or a player path.
    """
    path, root = Path(path), Path(allowed_root)
    if not path.is_absolute() or not root.is_absolute():
        raise ValidationError('database path and allowed_root must be absolute')
    root = root.resolve()
    resolved = path.resolve()
    if (not root.is_dir() or not root.is_relative_to(V2_ROOT) or root == V2_ROOT or
        not resolved.is_relative_to(root) or resolved.is_relative_to(V1_ROOT) or
        resolved.suffix not in ('.db', '.sqlite', '.sqlite3')):
        raise ValidationError('database outside explicit V2 write boundary')
    for candidate in (path, *(Path(str(path) + suffix) for suffix in ('-journal', '-wal', '-shm'))):
        if candidate.is_symlink():
            raise ValidationError('database/sidecar symlinks are forbidden')
        actual = candidate.resolve()
        if not actual.is_relative_to(root) or actual.is_relative_to(V1_ROOT):
            raise ValidationError('database/sidecar escapes write boundary')
        if candidate.exists():
            info = candidate.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValidationError('database/sidecar must be single-link regular file')
    return resolved


@dataclass(frozen=True, slots=True)
class LoadResult:
    status: str
    current: object = None
    recovery: object = None
    error: str | None = None


class SQLiteSave:
    """Own one explicitly opened connection; close() or context manager releases it.

    Application owns the transaction scope. This adapter never advances a Domain.
    Initialization is separate; reads never create/upgrade/repair a database.
    """
    def __init__(self, path, *, allowed_root):
        self.path = database_path(path, allowed_root)
        self.allowed_root = Path(allowed_root).resolve()
        self._connection = None
        self._writing = False
        if not self.path.is_file():
            raise PersistenceError('database is not initialized')
        info = self.path.stat()
        self._file_identity = (info.st_dev, info.st_ino)
        with self.path.open('rb') as source:
            header = source.read(20)
        if len(header) >= 20 and header[:16] == b'SQLite format 3\x00' and header[18:20] != b'\x01\x01':
            raise PersistenceError('only DELETE journal databases are supported')
        try:
            connection = sqlite3.connect('file:' + quote(str(self.path), safe='/') + '?mode=rw',
                                         uri=True, isolation_level=None, timeout=2.0)
            self._connection = connection
            connection.execute('PRAGMA foreign_keys=ON')
            connection.execute('PRAGMA synchronous=FULL')
            if connection.execute('PRAGMA journal_mode').fetchone()[0].lower() != 'delete':
                raise PersistenceError('only DELETE journal is supported in layout 2')
            self.check_layout()
        except (sqlite3.Error, PersistenceError) as exc:
            self.close()
            raise PersistenceError('cannot open supported V2 database') from exc

    @classmethod
    def initialize(cls, path, *, allowed_root):
        path = database_path(path, allowed_root)
        # Exclusive creation: an existing unknown file is never truncated.
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        connection = None
        try:
            connection = sqlite3.connect(str(path), isolation_level=None)
            connection.execute('PRAGMA journal_mode=DELETE')
            connection.execute('PRAGMA synchronous=FULL')
            connection.execute('BEGIN IMMEDIATE')
            for statement in SCHEMA:
                connection.execute(statement)
            connection.execute(f'PRAGMA user_version={DB_LAYOUT_VERSION}')
            connection.execute('COMMIT')
        except Exception:
            if connection is not None and connection.in_transaction:
                connection.execute('ROLLBACK')
            raise
        finally:
            if connection is not None:
                connection.close()
        return cls(path, allowed_root=allowed_root)

    def check_layout(self):
        """Explicit layout compatibility boundary; no implicit migration history."""
        self._ready()
        if self._connection.execute('PRAGMA user_version').fetchone()[0] != DB_LAYOUT_VERSION:
            raise PersistenceError('unsupported DB layout version')
        expected = {'current', 'previous', 'receipts'}
        tables = {row[0] for row in self._connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if tables != expected:
            raise PersistenceError('invalid DB layout tables')
        for table, columns in (('current', COLUMNS.split(',')), ('previous', COLUMNS.split(',')),
                               ('receipts', ['save_id', 'generation', 'request_id', 'intent',
                                             'committed_revision', 'body', 'digest'])):
            actual = [row[1] for row in self._connection.execute(f'PRAGMA table_info({table})')]
            if actual != columns:
                raise PersistenceError('invalid DB layout columns')

    def close(self):
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        self._writing = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _ready(self):
        if self._connection is None:
            raise PersistenceError('database connection is closed')
        database_path(self.path, self.allowed_root)
        if not self.path.is_file():
            raise PersistenceError('database path disappeared')
        info = self.path.stat()
        if (info.st_dev, info.st_ino) != self._file_identity:
            raise PersistenceError('database file was replaced; reopen explicitly')

    @contextmanager
    def transaction(self):
        self._ready()
        if self._connection.in_transaction:
            raise PersistenceError('nested transactions are forbidden')
        try:
            self._connection.execute('BEGIN IMMEDIATE')
            self._writing = True
            yield self
            self._ready()
            self._connection.execute('COMMIT')
        except Exception as exc:
            if self._connection.in_transaction:
                self._connection.execute('ROLLBACK')
            if isinstance(exc, sqlite3.Error):
                raise PersistenceError('SQLite transaction failed') from exc
            raise
        finally:
            self._writing = False

    def _write_required(self):
        self._ready()
        if not self._writing:
            raise PersistenceError('explicit write transaction required')

    def inspect(self, save_id, *, include_recovery=True):
        self._ready()
        uuid4_id(save_id, 'save_id')
        own_read = not self._connection.in_transaction
        try:
            if own_read:
                self._connection.execute('BEGIN')
            current = self._connection.execute(f'SELECT {COLUMNS} FROM current WHERE save_id=?', (save_id,)).fetchone()
            previous = (self._connection.execute(f'SELECT {COLUMNS} FROM previous WHERE save_id=?', (save_id,)).fetchone()
                        if include_recovery else None)
            if current is None:
                return LoadResult('NO_SAVE')
            recovery = None
            if previous is not None:
                try:
                    recovery = decode_state(previous)
                except CorruptSaveError:
                    pass  # Invalid previous is never offered as recovery material.
            try:
                return LoadResult('CURRENT_VALID', decode_state(current), recovery)
            except CorruptSaveError as exc:
                return LoadResult('CURRENT_INVALID_RECOVERY_AVAILABLE' if recovery is not None else
                                  'CURRENT_INVALID_NO_RECOVERY', recovery=recovery, error=str(exc))
        except sqlite3.Error as exc:
            raise PersistenceError('SQLite read failed') from exc
        finally:
            if own_read and self._connection.in_transaction:
                self._connection.execute('ROLLBACK')  # Read-only transaction; no database write.

    def receipt(self, save_id, generation, request_id):
        self._ready()
        row = self._connection.execute('SELECT save_id,generation,request_id,intent,committed_revision,body,digest '
                                       'FROM receipts WHERE save_id=? AND generation=? AND request_id=?',
                                       (save_id, generation, request_id)).fetchone()
        return None if row is None else StoredReceipt.from_row(row)

    def create(self, state):
        self._write_required()
        if self._connection.execute('SELECT 1 FROM current WHERE save_id=?', (state.save_id,)).fetchone():
            raise ConflictError('save already exists')
        self._connection.execute(f'INSERT INTO current ({COLUMNS}) VALUES ({",".join("?" for _ in range(11))})', encode_state(state))

    def commit(self, expected, candidate, receipt):
        self._write_required()
        actual = self.inspect(expected.save_id, include_recovery=False)
        if actual.status != 'CURRENT_VALID':
            raise CorruptSaveError('cannot mutate an invalid or missing save')
        if actual.current != expected:
            raise ConflictError('committed state changed before write')
        if (candidate.save_id, candidate.generation) != (expected.save_id, expected.generation):
            raise ConflictError('ordinary save cannot change save_id/generation')
        changed = replace(candidate, revision=expected.revision) != expected
        if candidate.revision != expected.revision + int(changed):
            raise ConflictError('candidate revision violates commit contract')
        if (receipt.save_id, receipt.generation, receipt.committed_revision) != (
            candidate.save_id, candidate.generation, candidate.revision
        ):
            raise ConflictError('receipt and candidate disagree')
        values = encode_state(candidate)
        self._connection.execute('UPDATE current SET generation=?,revision=?,save_schema_version=?,data_schema_version=?,'
                                 'content_version=?,body=?,digest=?,continuation=?,wall_claim_ms=?,wall_claim_digest=? WHERE save_id=?', values[1:] + values[:1])
        self._insert_receipt(receipt)

    def _insert_receipt(self, receipt):
        """Single SQL seam, overridden only by isolated failure-injection tests."""
        self._connection.execute('INSERT INTO receipts VALUES (?,?,?,?,?,?,?)', receipt.row())

    def checkpoint(self, save_id):
        self._write_required()
        result = self.inspect(save_id)
        if result.status != 'CURRENT_VALID':
            raise CorruptSaveError('checkpoint requires a valid current save')
        self._connection.execute('DELETE FROM previous WHERE save_id=?', (save_id,))
        self._connection.execute(f'INSERT INTO previous SELECT {COLUMNS} FROM current WHERE save_id=?', (save_id,))

    def recovery_rows(self, save_id):
        """Consistent raw material for explicit lifecycle CAS; not a State Query."""
        self._ready()
        uuid4_id(save_id, 'save_id')
        own_read = not self._connection.in_transaction
        try:
            if own_read:
                self._connection.execute('BEGIN')
            return tuple(self._connection.execute(f'SELECT {COLUMNS} FROM {table} WHERE save_id=?',
                                                   (save_id,)).fetchone()
                         for table in ('current', 'previous'))
        except sqlite3.Error as exc:
            raise PersistenceError('cannot inspect recovery material') from exc
        finally:
            if own_read and self._connection.in_transaction:
                self._connection.execute('ROLLBACK')

    def highest_generation(self, save_id):
        """A valid current lineage header is required, even if its JSON is corrupt."""
        self._ready()
        current, previous = self.recovery_rows(save_id)
        if current is None:
            raise ConflictError('missing current save')
        generations = [current[1]]
        if previous is not None:
            generations.append(previous[1])
        receipt_generation = self._connection.execute('SELECT MAX(generation) FROM receipts WHERE save_id=?',
                                                     (save_id,)).fetchone()[0]
        if receipt_generation is not None:
            generations.append(receipt_generation)
        for value in generations:
            integer(value, 'durable lineage generation', 1)
        maximum = max(generations)
        if maximum >= 2**63 - 1:
            raise ConflictError('SQLite generation range exhausted')
        return maximum

    def replace_from_recovery(self, request, candidate, receipt):
        self._write_required()
        self.check_layout()
        current, previous = self.recovery_rows(request.save_id)
        if (row_fingerprint(current), row_fingerprint(previous)) != (
            request.current_fingerprint, request.source_fingerprint
        ):
            raise ConflictError('recovery observations changed before replace')
        if current is None or previous is None or current[1] != request.expected_generation:
            raise ConflictError('recovery source/lineage no longer matches')
        source = decode_state(previous)
        if (candidate.save_id != request.save_id or source.save_id != request.save_id or
            candidate.generation != self.highest_generation(request.save_id) + 1 or
            candidate.revision != 0 or candidate.domains != source.domains or
            candidate.identity != source.identity or
            (candidate.save_schema_version, candidate.data_schema_version, candidate.content_version) !=
            (source.save_schema_version, source.data_schema_version, source.content_version) or
            candidate.time['sim_time_ms'] != source.time['sim_time_ms'] or
            candidate.time['day_length_ms'] != source.time['day_length_ms'] or
            candidate.time['pending'] is not None or
            candidate.time['last_settled_at_ms'] < max(source.time['last_settled_at_ms'], wall_claim(current))):
            raise ConflictError('candidate violates recovery contract')
        if (receipt.save_id, receipt.generation, receipt.request_id, receipt.kind, receipt.committed_revision) != (
            candidate.save_id, candidate.generation, request.request_id, 'recovery', 0
        ):
            raise ConflictError('recovery receipt and State disagree')
        values = encode_state(candidate)
        self._connection.execute('UPDATE current SET generation=?,revision=?,save_schema_version=?,data_schema_version=?,'
                                 'content_version=?,body=?,digest=?,continuation=?,wall_claim_ms=?,wall_claim_digest=? WHERE save_id=?', values[1:] + values[:1])
        # Consume the source; never promote corrupt Current into Previous.
        self._connection.execute('DELETE FROM previous WHERE save_id=?', (request.save_id,))
        self._connection.execute('DELETE FROM receipts WHERE save_id=? AND generation<>?',
                                 (request.save_id, candidate.generation))
        self._insert_receipt(receipt)


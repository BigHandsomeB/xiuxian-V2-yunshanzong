"""Isolated V2 SQLite contract/restart/corruption tests. No V1 DB or real Save."""
from dataclasses import asdict, replace
from pathlib import Path
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from uuid import uuid4

from src.application.memory import Command
from src.core.save.codec import (CorruptSaveError, PersistenceError, StoredReceipt,
                                 canonical, encode_state, sha)
from src.core.save.sqlite import DB_LAYOUT_VERSION, SQLiteSave, V2_ROOT, database_path
from src.core.state.envelope import StateEnvelope
from src.core.time.config import OFFLINE_CAP_MS
from src.core.time.model import Continuation
from src.core.validation import ConflictError, NotFoundError, ValidationError
from tests.fixtures.persistence import application, state
from tests.fixtures.time import ManualClock, application as memory_application, simulation_content


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        root = V2_ROOT / '.tmp'
        if root.is_symlink() or not root.resolve().is_relative_to(V2_ROOT):
            raise RuntimeError('TEST temporary root must remain inside V2')
        root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='phase6-', dir=root)
        self.root = Path(self.temp.name)
        self.path = self.root / 'test.sqlite3'
        self.store = SQLiteSave.initialize(self.path, allowed_root=self.root)
        self.clock = ManualClock()
        self.app = application(self.store, self.clock)
        self.initial = state()
        self.app.create(self.initial)
        self.save_id = self.initial.save_id

    def tearDown(self):
        self.store.close()
        directory = self.root
        self.temp.cleanup()
        self.assertFalse(directory.exists())

    def query(self):
        return self.app.query(self.save_id)

    def command(self, *, request_id=None, **updates):
        snapshot = self.query()
        args = dict(save_id=self.save_id, generation=snapshot.generation,
                    expected_revision=snapshot.revision, request_id=request_id or str(uuid4()),
                    name='test_increment', payload={'amount': 1})
        args.update(updates)
        return Command(**args)

    def request(self, *, budget=100, continuation=None, **updates):
        from src.application.settlement import SettlementRequest
        snapshot = self.query()
        args = dict(save_id=self.save_id, generation=snapshot.generation,
                    expected_revision=snapshot.revision, request_id=str(uuid4()),
                    max_events=budget, continuation=continuation)
        args.update(updates)
        return SettlementRequest(**args)

    def restart(self):
        self.store.close()
        self.store = SQLiteSave(self.path, allowed_root=self.root)
        self.clock = ManualClock(self.clock.value)
        self.app = application(self.store, self.clock)

    def schedule(self, schedule):
        self.initial = state(schedule)
        self.app.create(self.initial)
        self.save_id = self.initial.save_id

    def corrupt(self, transform=None, *, raw=None):
        with sqlite3.connect(self.path) as connection:
            body = connection.execute('SELECT body FROM current WHERE save_id=?', (self.save_id,)).fetchone()[0]
            if transform is not None:
                value = json.loads(body)
                transform(value)
                body = canonical(value)
            else:
                body = raw
            connection.execute('UPDATE current SET body=?,digest=? WHERE save_id=?', (body, sha(body), self.save_id))

    def test_initialize_and_layout_version(self):
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], DB_LAYOUT_VERSION)
            self.assertEqual(db.execute('PRAGMA journal_mode').fetchone()[0], 'delete')
        empty = self.root / 'empty.db'
        with SQLiteSave.initialize(empty, allowed_root=self.root) as store:
            self.assertEqual(store.inspect(str(uuid4())).status, 'NO_SAVE')

    def test_initialize_existing_never_overwrites(self):
        before = self.path.read_bytes()
        with self.assertRaises(FileExistsError):
            SQLiteSave.initialize(self.path, allowed_root=self.root)
        self.assertEqual(self.path.read_bytes(), before)

    def test_open_missing_never_creates(self):
        path = self.root / 'missing.db'
        with self.assertRaises(PersistenceError):
            SQLiteSave(path, allowed_root=self.root)
        self.assertFalse(path.exists())

    def test_open_unsupported_layout(self):
        self.store.close()
        with sqlite3.connect(self.path) as db:
            db.execute('PRAGMA user_version=999')
        with self.assertRaises(PersistenceError):
            SQLiteSave(self.path, allowed_root=self.root)

    def test_invalid_layout_tables(self):
        self.store.close()
        with sqlite3.connect(self.path) as db:
            db.execute('DROP TABLE receipts')
        with self.assertRaises(PersistenceError):
            SQLiteSave(self.path, allowed_root=self.root)

    def test_round_trip_all_envelope_fields(self):
        self.restart()
        self.assertEqual(self.query().to_dict(), self.initial.to_dict())
        self.assertIsNot(self.query(), self.initial)

    def test_generation_revision_preserved(self):
        self.app.execute(self.command())
        expected = self.query()
        self.restart()
        self.assertEqual((self.query().generation, self.query().revision), (expected.generation, 1))

    def test_save_only_definition_references(self):
        with sqlite3.connect(self.path) as db:
            body = db.execute('SELECT body FROM current WHERE save_id=?', (self.save_id,)).fetchone()[0]
        self.assertIn('test_entry', body)
        self.assertNotIn('display_name', body)
        self.assertNotIn('definitions', body)

    def test_display_name_change_does_not_break_reference(self):
        from tests.fixtures.foundation import PACKAGE
        from src.data.registry import DefinitionRegistry
        from src.application.persistent import PersistentApplication
        from tests.fixtures.persistence import references
        package = json.loads(json.dumps(PACKAGE))
        package['definitions'][0]['display_name'] = 'TEST renamed display'
        registry = DefinitionRegistry.from_json(json.dumps(package))
        app = PersistentApplication(self.store, registry, {}, references=references)
        self.assertEqual(app.query(self.save_id).save_id, self.save_id)

    def test_unknown_definition_on_load(self):
        self.corrupt(lambda value: value['domains']['fixture']['definition_refs'][0].update(machine_id='test_unknown'))
        self.assertEqual(self.app.inspect(self.save_id).status, 'CURRENT_INVALID_NO_RECOVERY')
        with self.assertRaises(CorruptSaveError):
            self.query()

    def test_unknown_definition_creation_rejected(self):
        raw = state().to_dict()
        raw['domains']['fixture']['definition_refs'][0]['machine_id'] = 'test_unknown'
        with self.assertRaises(NotFoundError):
            self.app.create(StateEnvelope.from_dict(raw))
        self.assertEqual(self.store.inspect(raw['save_id']).status, 'NO_SAVE')

    def test_query_is_read_only_and_does_not_claim_clock(self):
        self.clock.advance(1000)
        before = self.path.read_bytes()
        for _ in range(3):
            self.assertEqual(self.query(), self.initial)
        self.assertEqual(self.clock.reads, 0)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertIsNone(self.store.receipt(self.save_id, 1, str(uuid4())))

    def test_command_atomic_state_and_receipt(self):
        command = self.command()
        receipt = self.app.execute(command)
        self.assertEqual(self.query().domains['fixture']['value'], 1)
        saved = self.store.receipt(self.save_id, 1, command.request_id)
        self.assertEqual(saved.committed_revision, receipt.committed_revision)
        self.assertEqual(saved.intent, command.digest())

    def test_failure_after_state_write_rolls_back_and_not_visible(self):
        command = self.command()
        before = self.query()
        observer = SQLiteSave(self.path, allowed_root=self.root)
        observations = []
        class FailingStore(SQLiteSave):
            def _insert_receipt(adapter, record):
                observations.append(application(observer).query(self.save_id))
                raise RuntimeError('TEST injected failure after State SQL')
        self.store.close()
        self.store = FailingStore(self.path, allowed_root=self.root)
        self.app = application(self.store, self.clock)
        try:
            with self.assertRaises(RuntimeError):
                self.app.execute(command)
            self.assertEqual(observations, [before])
            self.assertEqual(self.query(), before)
            self.assertIsNone(self.store.receipt(self.save_id, 1, command.request_id))
        finally:
            observer.close()
        self.restart()
        self.app.execute(command)
        self.assertEqual(self.query().revision, 1)

    def test_sql_error_rolls_back(self):
        command = self.command()
        before = self.query()
        class FailingStore(SQLiteSave):
            def _insert_receipt(adapter, record):
                raise sqlite3.IntegrityError('TEST receipt failure')
        self.store.close()
        self.store = FailingStore(self.path, allowed_root=self.root)
        self.app = application(self.store)
        with self.assertRaises(PersistenceError):
            self.app.execute(command)
        self.assertEqual(self.query(), before)

    def test_failed_domain_candidate_not_saved(self):
        before = self.query()
        command = self.command(payload={'amount': 1, 'reject': True})
        with self.assertRaises(ValidationError):
            self.app.execute(command)
        self.assertEqual(self.query(), before)
        self.assertIsNone(self.store.receipt(self.save_id, 1, command.request_id))

    def test_noop_receipt_persists_without_revision_increment(self):
        command = self.command(name='test_noop', payload={})
        self.app.execute(command)
        self.restart()
        self.assertEqual(self.app.execute(command).committed_revision, 0)
        self.assertEqual(self.query().revision, 0)

    def test_command_replay_after_restart_before_revision_check(self):
        command = self.command()
        receipt = self.app.execute(command)
        self.app.execute(self.command())
        self.restart()
        self.assertEqual(self.app.execute(command), receipt)
        self.assertEqual(self.query().revision, 2)
        self.assertEqual(self.query().domains['fixture']['value'], 2)

    def test_different_intent_after_restart_conflicts(self):
        command = self.command()
        self.app.execute(command)
        self.restart()
        with self.assertRaises(ConflictError):
            self.app.execute(replace(command, payload={'amount': 2}))
        self.assertEqual(self.query().revision, 1)

    def test_stale_revision_rejected_two_connections(self):
        stale = self.command()
        with SQLiteSave(self.path, allowed_root=self.root) as other:
            application(other).execute(self.command())
        with self.assertRaises(ConflictError):
            self.app.execute(stale)
        self.assertEqual(self.query().revision, 1)

    def test_stale_generation_request_rejected(self):
        with self.assertRaises(ConflictError):
            self.app.execute(self.command(generation=2))
        self.assertEqual(self.query().revision, 0)

    def test_stale_generation_adapter_candidate_rejected(self):
        old = replace(self.initial, generation=2)
        candidate = old.with_domain('fixture', {**old.domains['fixture'], 'value': 1})
        receipt = StoredReceipt(old.save_id, 2, str(uuid4()), '0' * 64, 1, 'command', None)
        with self.assertRaises(ConflictError), self.store.transaction():
            self.store.commit(old, candidate, receipt)
        self.assertEqual(self.query(), self.initial)

    def test_stale_candidate_adapter_rejected(self):
        old = self.query()
        self.app.execute(self.command())
        candidate = old.with_domain('fixture', {**old.domains['fixture'], 'value': 2})
        receipt = StoredReceipt(old.save_id, 1, str(uuid4()), '0' * 64, 1, 'command', None)
        with self.assertRaises(ConflictError), self.store.transaction():
            self.store.commit(old, candidate, receipt)
        self.assertEqual(self.query().domains['fixture']['value'], 1)

    def test_pending_and_continuation_round_trip(self):
        self.schedule([(10, 0, 'TEST a'), (20, 0, 'TEST b')])
        self.clock.advance(100)
        request = self.request(budget=1)
        receipt = self.app.settle(request)
        expected = self.query()
        self.assertEqual(receipt.result.status, 'PENDING')
        self.restart()
        loaded = self.query()
        self.assertEqual(loaded.to_dict(), expected.to_dict())
        self.assertEqual(Continuation.for_state(loaded), receipt.result.continuation)
        self.assertEqual(self.app.settle(request), receipt)
        self.assertEqual(self.clock.reads, 0)

    def test_restart_resume_equals_full(self):
        self.schedule([(10, 0, 'TEST a'), (20, 0, 'TEST b'), (20, 1, 'TEST c')])
        full_clock = ManualClock(1100)
        full = memory_application(initial_state=self.initial, clock=full_clock)
        from tests.fixtures.time import request
        full.settle(request(full))
        self.app.execute(self.command(name='test_noop', payload={}))
        self.clock.advance(100)
        self.app.settle(self.request(budget=1))
        self.restart()
        while self.query().time['pending'] is not None:
            continuation = Continuation.for_state(self.query())
            self.app.settle(self.request(budget=1, continuation=continuation))
            self.restart()
        self.assertEqual(simulation_content(self.query()), simulation_content(full.query()))
        self.assertEqual(self.query().domains['fixture']['event_trace'], ('TEST a', 'TEST b', 'TEST c'))

    def test_restart_uses_actual_new_process(self):
        self.schedule([(10, 0, 'TEST a'), (20, 0, 'TEST b')])
        self.clock.advance(100)
        self.app.execute(self.command())
        self.app.settle(self.request(budget=1))
        self.store.close()
        program = """import sys
from pathlib import Path
from src.core.save.sqlite import SQLiteSave
from src.core.time.model import Continuation
from src.application.settlement import SettlementRequest
from tests.fixtures.persistence import application
from uuid import uuid4
with SQLiteSave(Path(sys.argv[1]), allowed_root=Path(sys.argv[2])) as store:
    app=application(store)
    state=app.query(sys.argv[3])
    assert state.time['pending'] is not None
    receipt=app.settle(SettlementRequest(state.save_id,state.generation,state.revision,str(uuid4()),100,Continuation.for_state(state)))
    assert receipt.result.status=='COMPLETE'
    assert app.query(state.save_id).domains['fixture']['value']==3
"""
        run = subprocess.run([sys.executable, '-B', '-c', program, str(self.path), str(self.root), self.save_id],
                             cwd=V2_ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.restart()
        self.assertIsNone(self.query().time['pending'])

    def test_stale_continuation_after_restart_rejected(self):
        self.schedule([(10, 0, 'TEST a'), (20, 0, 'TEST b')])
        self.clock.advance(100)
        self.app.settle(self.request(budget=1))
        self.restart()
        continuation = replace(Continuation.for_state(self.query()), revision=0)
        with self.assertRaises(ConflictError):
            self.app.settle(self.request(continuation=continuation))

    def test_wrong_generation_continuation_after_restart(self):
        self.schedule([(10, 0, 'TEST a'), (20, 0, 'TEST b')])
        self.clock.advance(100)
        self.app.settle(self.request(budget=1))
        self.restart()
        continuation = replace(Continuation.for_state(self.query()), generation=2)
        with self.assertRaises(ConflictError):
            self.app.settle(self.request(continuation=continuation))

    def test_offline_cap_and_frozen_excess_survive_restart(self):
        self.clock.advance(100 * 3600 * 1000)
        result = self.app.settle(self.request()).result
        self.assertEqual(result.accepted_ms, OFFLINE_CAP_MS)
        self.assertEqual(result.discarded_ms, 100 * 3600 * 1000 - OFFLINE_CAP_MS)
        watermark = self.clock.value
        self.restart()
        self.assertEqual(self.query().time['last_settled_at_ms'], watermark)
        self.assertEqual(self.query().time['sim_time_ms'], OFFLINE_CAP_MS)
        self.assertEqual(self.app.settle(self.request()).result.accepted_ms, 0)
        self.assertEqual(self.query().time['sim_time_ms'], OFFLINE_CAP_MS)

    def test_cap_pending_resume_after_restart(self):
        self.schedule([(10, 0, 'TEST a'), (20, 0, 'TEST b'), (OFFLINE_CAP_MS + 1, 0, 'TEST frozen')])
        self.clock.advance(100 * 3600 * 1000)
        self.app.settle(self.request(budget=1))
        self.restart()
        result = self.app.settle(self.request(continuation=Continuation.for_state(self.query()))).result
        self.assertEqual(result.status, 'COMPLETE')
        self.assertEqual(self.query().domains['fixture']['event_trace'], ('TEST a', 'TEST b'))
        self.restart()
        self.app.settle(self.request())
        self.assertEqual(self.query().domains['fixture']['event_trace'], ('TEST a', 'TEST b'))

    def test_pending_blocks_command_after_restart(self):
        self.schedule([(10, 0, 'TEST a'), (20, 0, 'TEST b')])
        self.clock.advance(100)
        self.app.settle(self.request(budget=1))
        self.restart()
        with self.assertRaises(ConflictError):
            self.app.execute(self.command())

    def test_recovery_available_current_not_overwritten(self):
        self.app.checkpoint(self.save_id)
        previous = self.query()
        self.app.execute(self.command())
        self.corrupt(raw='{broken')
        before = self.path.read_bytes()
        result = self.app.inspect(self.save_id)
        self.assertEqual(result.status, 'CURRENT_INVALID_RECOVERY_AVAILABLE')
        self.assertEqual(result.recovery, previous)
        self.assertIsNone(result.current)
        self.assertEqual(self.path.read_bytes(), before)
        self.restart()
        self.assertEqual(self.app.inspect(self.save_id).recovery, previous)
        with self.assertRaises(CorruptSaveError):
            self.query()

    def test_checkpoint_bounded_and_explicit(self):
        self.app.checkpoint(self.save_id)
        self.app.execute(self.command())
        self.assertEqual(self.app.inspect(self.save_id).recovery.revision, 0)
        self.app.checkpoint(self.save_id)
        self.app.execute(self.command())
        self.assertEqual(self.app.inspect(self.save_id).recovery.revision, 1)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM previous WHERE save_id=?', (self.save_id,)).fetchone()[0], 1)

    def test_invalid_previous_not_offered(self):
        self.app.checkpoint(self.save_id)
        with sqlite3.connect(self.path) as db:
            db.execute('UPDATE previous SET digest=? WHERE save_id=?', ('wrong', self.save_id))
        self.corrupt(raw='{}')
        self.assertEqual(self.app.inspect(self.save_id).status, 'CURRENT_INVALID_NO_RECOVERY')

    def test_invalid_current_cannot_be_checkpointed(self):
        self.app.checkpoint(self.save_id)
        self.corrupt(raw='{}')
        with self.assertRaises(CorruptSaveError):
            self.app.checkpoint(self.save_id)
        self.assertEqual(self.app.inspect(self.save_id).recovery, self.initial)

    def test_malformed_json_rejected(self):
        self.corrupt(raw='{bad')
        self.assertEqual(self.app.inspect(self.save_id).status, 'CURRENT_INVALID_NO_RECOVERY')

    def test_unsupported_save_schema_rejected(self):
        self.corrupt(lambda value: value.update(save_schema_version=999))
        with self.assertRaises(CorruptSaveError):
            self.query()

    def test_missing_required_metadata_rejected(self):
        self.corrupt(lambda value: value.pop('save_id'))
        with self.assertRaises(CorruptSaveError):
            self.query()

    def test_invalid_generation_and_revision_rejected(self):
        for field, bad in [('generation', 0), ('revision', -1), ('generation', True)]:
            with self.subTest(field=field, value=bad):
                raw = self.initial.to_dict()
                raw[field] = bad
                self.corrupt(raw=canonical(raw))
                with self.assertRaises(CorruptSaveError):
                    self.query()

    def test_metadata_disagreement_rejected(self):
        with sqlite3.connect(self.path) as db:
            db.execute('UPDATE current SET revision=10 WHERE save_id=?', (self.save_id,))
        with self.assertRaises(CorruptSaveError):
            self.query()

    def test_checksum_corruption_rejected(self):
        with sqlite3.connect(self.path) as db:
            db.execute('UPDATE current SET digest=? WHERE save_id=?', ('bad', self.save_id))
        with self.assertRaises(CorruptSaveError):
            self.query()

    def test_duplicate_json_keys_rejected(self):
        body = canonical(self.initial.to_dict())
        self.corrupt(raw=body[:-1] + ',"revision":0}')
        with self.assertRaises(CorruptSaveError):
            self.query()

    def test_nonfinite_json_rejected(self):
        body = canonical(self.initial.to_dict()).replace('"value":0', '"value":NaN')
        self.corrupt(raw=body)
        with self.assertRaises(CorruptSaveError):
            self.query()

    def test_unknown_fields_rejected(self):
        self.corrupt(lambda value: value.update(test_unknown=True))
        with self.assertRaises(CorruptSaveError):
            self.query()

    def test_content_version_mismatch_rejected(self):
        self.corrupt(lambda value: value.update(content_version='test_unknown_v2'))
        with self.assertRaises(CorruptSaveError):
            self.query()

    def test_invalid_pending_cursor_rejected(self):
        self.schedule([(10, 0, 'TEST a'), (20, 0, 'TEST b')])
        self.clock.advance(100)
        self.app.settle(self.request(budget=1))
        raw = self.query().to_dict()
        raw['time']['pending']['accrued_to_ms'] += 1
        candidate = StateEnvelope.from_dict(raw)
        values = encode_state(candidate)
        with sqlite3.connect(self.path) as db:
            db.execute('UPDATE current SET body=?,digest=?,continuation=? WHERE save_id=?', (values[6], values[7], values[8], self.save_id))
        with self.assertRaises(CorruptSaveError):
            self.query()

    def test_corrupt_continuation_fingerprint_rejected(self):
        self.schedule([(10, 0, 'TEST a'), (20, 0, 'TEST b')])
        self.clock.advance(100)
        self.app.settle(self.request(budget=1))
        with sqlite3.connect(self.path) as db:
            cont = asdict(Continuation.for_state(self.query()))
            cont['state_fingerprint'] = '0' * 64
            db.execute('UPDATE current SET continuation=? WHERE save_id=?', (canonical(cont), self.save_id))
        with self.assertRaises(CorruptSaveError):
            self.query()

    def test_corrupt_receipt_replay_is_detected(self):
        command = self.command()
        self.app.execute(command)
        with sqlite3.connect(self.path) as db:
            db.execute('UPDATE receipts SET digest=? WHERE request_id=?', ('wrong', command.request_id))
        self.restart()
        with self.assertRaises(CorruptSaveError):
            self.app.execute(command)
        self.assertEqual(self.query().revision, 1)

    def test_no_save_is_not_corruption(self):
        save = str(uuid4())
        self.assertEqual(self.app.inspect(save).status, 'NO_SAVE')
        with self.assertRaises(NotFoundError):
            self.app.query(save)

    def test_connection_close_and_context_lifecycle(self):
        self.store.close()
        self.store.close()
        with self.assertRaises(PersistenceError):
            self.store.inspect(self.save_id)
        with SQLiteSave(self.path, allowed_root=self.root) as reopened:
            self.assertEqual(reopened.inspect(self.save_id).status, 'CURRENT_VALID')
        with self.assertRaises(PersistenceError):
            reopened.inspect(self.save_id)

    def test_explicit_transaction_required(self):
        with self.assertRaises(PersistenceError):
            self.store.create(state())
        with self.store.transaction():
            with self.assertRaises(PersistenceError):
                with self.store.transaction():
                    pass

    def test_relative_path_and_outside_root_rejected(self):
        for path in (Path('test.db'), V2_ROOT.parent / 'legacy-reference' / 'TEST_NEVER_CREATE.db', self.root.parent / 'outside.db'):
            with self.subTest(path=path), self.assertRaises(ValidationError):
                database_path(path, self.root)

    def test_symlink_escape_rejected(self):
        link = self.root / 'escape'
        link.symlink_to(V2_ROOT.parent / 'legacy-reference', target_is_directory=True)
        with self.assertRaises(ValidationError):
            database_path(link / 'TEST_NEVER_CREATE.db', self.root)

    def test_database_symlink_and_hardlink_rejected(self):
        symlink = self.root / 'link.db'
        symlink.symlink_to(self.path)
        with self.assertRaises(ValidationError):
            database_path(symlink, self.root)
        hardlink = self.root / 'hard.db'
        os.link(self.path, hardlink)
        try:
            with self.assertRaises(ValidationError):
                database_path(self.path, self.root)
        finally:
            hardlink.unlink()

    def test_sidecar_symlink_rejected_before_write(self):
        sidecar = Path(str(self.path) + '-journal')
        target = self.root / 'TEST_do_not_change.txt'
        target.write_text('TEST protected')
        sidecar.symlink_to(target)
        try:
            with self.assertRaises(ValidationError):
                self.app.execute(self.command())
            self.assertEqual(target.read_text(), 'TEST protected')
        finally:
            sidecar.unlink()

    def test_receipt_metadata_checksum_detects_corruption(self):
        command = self.command()
        self.app.execute(command)
        with sqlite3.connect(self.path) as db:
            db.execute('UPDATE receipts SET committed_revision=0 WHERE request_id=?', (command.request_id,))
        with self.assertRaises(CorruptSaveError):
            self.app.execute(command)
        self.assertEqual(self.query().revision, 1)

    def test_old_generation_replay_rejected_after_new_generation(self):
        command = self.command()
        self.app.execute(command)
        # Isolated fixture represents a future explicit replacement; no production restore.
        newer = replace(self.query(), generation=2, revision=0)
        values = encode_state(newer)
        with sqlite3.connect(self.path) as db:
            db.execute('UPDATE current SET generation=?,revision=?,body=?,digest=? WHERE save_id=?',
                       (2, 0, values[6], values[7], self.save_id))
        self.restart()
        with self.assertRaises(ConflictError):
            self.app.execute(command)
        self.assertEqual(self.query().generation, 2)
        self.assertEqual(self.query().revision, 0)

    def test_invalid_reference_candidate_rolls_back(self):
        from src.application.memory import CommandSpec
        from src.application.persistent import PersistentApplication
        from tests.fixtures.foundation import registry
        from tests.fixtures.persistence import references
        def transition(partition, payload):
            partition['definition_refs'][0]['machine_id'] = 'test_unknown'
        app = PersistentApplication(self.store, registry(), {'test_bad_ref': CommandSpec('fixture', transition)},
                                    references=references)
        command = replace(self.command(), name='test_bad_ref')
        with self.assertRaises(NotFoundError):
            app.execute(command)
        self.assertEqual(self.query(), self.initial)
        self.assertIsNone(self.store.receipt(self.save_id, 1, command.request_id))

    def test_invalid_recovery_reference_not_offered(self):
        self.app.checkpoint(self.save_id)
        raw = self.initial.to_dict()
        raw['domains']['fixture']['definition_refs'][0]['machine_id'] = 'test_unknown'
        body = canonical(raw)
        with sqlite3.connect(self.path) as db:
            db.execute('UPDATE previous SET body=?,digest=? WHERE save_id=?', (body, sha(body), self.save_id))
        self.corrupt(raw='{}')
        self.assertEqual(self.app.inspect(self.save_id).status, 'CURRENT_INVALID_NO_RECOVERY')

    def test_settlement_failure_before_commit_does_not_persist(self):
        self.schedule([(10, 0, 'TEST bad', {'reject': True})])
        self.clock.advance(100)
        before = self.query()
        request = self.request()
        with self.assertRaises(ValidationError):
            self.app.settle(request)
        self.restart()
        self.assertEqual(self.query(), before)
        self.assertIsNone(self.store.receipt(self.save_id, 1, request.request_id))

    def test_missing_continuation_rejected_on_load(self):
        self.schedule([(10, 0, 'TEST a'), (20, 0, 'TEST b')])
        self.clock.advance(100)
        self.app.settle(self.request(budget=1))
        with sqlite3.connect(self.path) as db:
            db.execute('UPDATE current SET continuation=NULL WHERE save_id=?', (self.save_id,))
        with self.assertRaises(CorruptSaveError):
            self.query()

    def test_fake_revision_only_candidate_rejected(self):
        candidate = replace(self.initial, revision=1)
        record = StoredReceipt(candidate.save_id, 1, str(uuid4()), '0' * 64, 1, 'command', None)
        with self.assertRaises(ConflictError), self.store.transaction():
            self.store.commit(self.initial, candidate, record)
        self.assertEqual(self.query().revision, 0)

    def test_nontext_snapshot_rejected_as_corruption(self):
        self.app.checkpoint(self.save_id)
        with sqlite3.connect(self.path) as db:
            db.execute('UPDATE previous SET body=? WHERE save_id=?', (sqlite3.Binary(b'not text'), self.save_id))
        self.corrupt(raw='{}')
        self.assertEqual(self.app.inspect(self.save_id).status, 'CURRENT_INVALID_NO_RECOVERY')

    def test_wal_database_rejected_before_open(self):
        self.store.close()
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('PRAGMA journal_mode=WAL').fetchone()[0], 'wal')
        for suffix in ('-wal', '-shm'):
            self.assertFalse(Path(str(self.path) + suffix).exists())
        with self.assertRaises(PersistenceError):
            SQLiteSave(self.path, allowed_root=self.root)
        for suffix in ('-wal', '-shm'):
            self.assertFalse(Path(str(self.path) + suffix).exists())

    def test_replaced_database_path_rejected(self):
        displaced = self.root / 'old.sqlite3'
        self.path.rename(displaced)
        self.path.write_bytes(displaced.read_bytes())
        with self.assertRaises(PersistenceError):
            self.query()

    def test_test_artifacts_are_cleaned(self):
        for suffix in ('-wal', '-shm', '-journal'):
            self.assertFalse(Path(str(self.path) + suffix).exists())
        self.assertTrue(self.path.is_relative_to(V2_ROOT / '.tmp'))

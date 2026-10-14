"""TEST ONLY explicit recovery, lineage, rollback and true restart; V2 temp SQLite."""
from dataclasses import asdict, replace
from pathlib import Path
import json
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from uuid import uuid4

from src.application.memory import Command
from src.application.recovery import RecoveryApplication
from src.application.settlement import SettlementRequest
from src.core.save.codec import (CorruptSaveError, PersistenceError, canonical, sha)
from src.core.save.recovery import RecoveryRequest, RecoveryResult
from src.core.save.sqlite import SQLiteSave, V2_ROOT
from src.core.time.config import OFFLINE_CAP_MS
from src.core.time.model import Continuation
from src.core.validation import ConflictError, ValidationError
from tests.fixtures.persistence import application, state
from tests.fixtures.time import ManualClock


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        root = V2_ROOT / '.tmp'
        if root.is_symlink() or not root.resolve().is_relative_to(V2_ROOT):
            raise RuntimeError('TEST temporary root outside V2')
        root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='phase7-', dir=root)
        self.root = Path(self.temp.name)
        self.path = self.root / 'test.sqlite3'
        self.store = SQLiteSave.initialize(self.path, allowed_root=self.root)
        self.clock = ManualClock()
        self.app = application(self.store, self.clock)
        self.recovery = RecoveryApplication(self.app, self.clock)
        self.initial = state()
        self.save_id = self.initial.save_id
        self.app.create(self.initial)
        self.app.checkpoint(self.save_id)
        self.app.execute(self.command())

    def tearDown(self):
        self.store.close()
        directory = self.root
        self.temp.cleanup()
        self.assertFalse(directory.exists())

    def query(self):
        return self.app.query(self.save_id)

    def command(self, **updates):
        snapshot = self.query()
        args = dict(save_id=self.save_id, generation=snapshot.generation,
                    expected_revision=snapshot.revision, request_id=str(uuid4()),
                    name='test_increment', payload={'amount': 1})
        args.update(updates)
        return Command(**args)

    def settlement(self, *, budget=100, continuation=None, **updates):
        snapshot = self.query()
        args = dict(save_id=self.save_id, generation=snapshot.generation,
                    expected_revision=snapshot.revision, request_id=str(uuid4()),
                    max_events=budget, continuation=continuation)
        args.update(updates)
        return SettlementRequest(**args)

    def request(self, observation=None, **updates):
        observation = observation or self.recovery.inspect(self.save_id)
        self.assertEqual(observation.status, 'READY')
        args = dict(save_id=self.save_id, expected_generation=observation.current_generation,
                    current_fingerprint=observation.current_fingerprint,
                    source_fingerprint=observation.source_fingerprint,
                    request_id=str(uuid4()), reason='TEST explicit recovery')
        args.update(updates)
        return RecoveryRequest(**args)

    def schedule(self, rows):
        self.initial = state(rows)
        self.save_id = self.initial.save_id
        self.app.create(self.initial)
        self.app.checkpoint(self.save_id)

    def restart(self):
        self.store.close()
        self.store = SQLiteSave(self.path, allowed_root=self.root)
        self.clock = ManualClock(self.clock.value)
        self.app = application(self.store, self.clock)
        self.recovery = RecoveryApplication(self.app, self.clock)

    def dump(self):
        with sqlite3.connect(self.path) as db:
            return tuple(tuple(db.execute(f'SELECT * FROM {table} ORDER BY 1,2,3'))
                         for table in ('current', 'previous', 'receipts'))

    def corrupt(self, table='current', *, transform=None, raw='{TEST broken', checksum=True):
        with sqlite3.connect(self.path) as db:
            if transform is not None:
                value = json.loads(db.execute(f'SELECT body FROM {table} WHERE save_id=?', (self.save_id,)).fetchone()[0])
                transform(value)
                raw = canonical(value)
            db.execute(f'UPDATE {table} SET body=?,digest=? WHERE save_id=?',
                       (raw, sha(raw) if checksum else '0' * 64, self.save_id))

    def assert_failure_atomic(self, request, status):
        before = self.dump()
        result = self.recovery.recover(request)
        self.assertEqual(result.status, status)
        self.assertEqual(self.dump(), before)
        return result

    def test_inspect_valid_candidate_is_read_only(self):
        before = self.dump()
        observation = self.recovery.inspect(self.save_id)
        self.assertEqual(observation.status, 'READY')
        self.assertEqual((observation.source_generation, observation.source_revision), (1, 0))
        self.assertEqual(len(observation.source_fingerprint), 64)
        self.assertEqual(self.dump(), before)
        self.assertEqual(self.clock.reads, 0)

    def test_load_and_restart_never_automatically_recover(self):
        self.corrupt()
        before = self.dump()
        self.restart()
        self.assertEqual(self.app.inspect(self.save_id).status, 'CURRENT_INVALID_RECOVERY_AVAILABLE')
        with self.assertRaises(CorruptSaveError):
            self.query()
        self.assertEqual(self.recovery.inspect(self.save_id).status, 'READY')
        self.assertEqual(self.dump(), before)

    def test_explicit_corrupt_current_recovery(self):
        self.corrupt()
        result = self.recovery.recover(self.request())
        snapshot = self.query()
        self.assertEqual(result.status, 'SUCCESS')
        self.assertEqual(snapshot.save_id, self.initial.save_id)
        self.assertEqual((snapshot.generation, snapshot.revision), (2, 0))
        self.assertEqual(snapshot.domains, self.initial.domains)
        self.assertEqual(snapshot.identity, self.initial.identity)
        self.assertTrue(result.reason.startswith('CURRENT_INVALID:'))

    def test_valid_current_progress_rollback_is_explicit(self):
        result = self.recovery.recover(self.request())
        self.assertEqual(result.status, 'SUCCESS')
        self.assertEqual(self.query().domains['fixture']['value'], 0)
        self.assertTrue(result.reason.startswith('EXPLICIT_PROGRESS_ROLLBACK:'))

    def test_revision_resets_per_generation_then_advances(self):
        self.app.execute(self.command())
        self.assertEqual(self.query().revision, 2)
        self.recovery.recover(self.request())
        self.assertEqual(self.query().revision, 0)
        self.app.execute(self.command())
        self.assertEqual(self.query().revision, 1)

    def test_invalid_source_json_revalidated_during_execution(self):
        request = self.request()
        self.corrupt('previous')
        self.assert_failure_atomic(request, 'RECOVERY_CANDIDATE_INVALID')

    def test_source_checksum_failure_rejected(self):
        request = self.request()
        self.corrupt('previous', raw=canonical(self.initial.to_dict()), checksum=False)
        self.assert_failure_atomic(request, 'RECOVERY_CANDIDATE_INVALID')

    def test_source_schema_failure_rejected(self):
        request = self.request()
        self.corrupt('previous', transform=lambda value: value.update(save_schema_version=999))
        self.assert_failure_atomic(request, 'RECOVERY_CANDIDATE_INVALID')

    def test_source_unknown_definition_rejected(self):
        request = self.request()
        self.corrupt('previous', transform=lambda value: value['domains']['fixture']['definition_refs'][0].update(machine_id='test_unknown'))
        self.assert_failure_atomic(request, 'RECOVERY_CANDIDATE_INVALID')

    def test_source_save_identity_mismatch_rejected(self):
        request = self.request()
        self.corrupt('previous', transform=lambda value: value.update(save_id=str(uuid4())))
        self.assert_failure_atomic(request, 'RECOVERY_CANDIDATE_INVALID')

    def test_changed_valid_source_returns_conflict(self):
        request = self.request()
        self.corrupt('previous', transform=lambda value: value['domains']['fixture'].update(value=100))
        self.assert_failure_atomic(request, 'CONFLICT')

    def test_stale_generation_observation_returns_conflict(self):
        request = replace(self.request(), expected_generation=2)
        self.assert_failure_atomic(request, 'CONFLICT')

    def test_corrupt_lineage_header_is_not_guessed(self):
        request = self.request()
        with sqlite3.connect(self.path) as db:
            db.execute('UPDATE current SET generation=0 WHERE save_id=?', (self.save_id,))
        self.assert_failure_atomic(request, 'CONFLICT')
        self.assertEqual(self.recovery.inspect(self.save_id).status, 'CONFLICT')

    def test_generation_overflow_is_safe_conflict(self):
        request = self.request()
        with sqlite3.connect(self.path) as db:
            db.execute('UPDATE current SET generation=? WHERE save_id=?', (2**63-1, self.save_id))
        observation = self.recovery.inspect(self.save_id)
        request = self.request(observation)
        self.assert_failure_atomic(request, 'CONFLICT')

    def test_highest_retained_generation_not_reused(self):
        # Old scope receipt retained in this isolated fixture; new epoch must exceed it.
        command = self.command()
        self.app.execute(command)
        with sqlite3.connect(self.path) as db:
            db.execute('UPDATE receipts SET generation=8 WHERE request_id=?', (command.request_id,))
        result = self.recovery.recover(self.request())
        self.assertEqual(result.new_generation, 9)
        self.assertEqual(self.query().generation, 9)

    def test_unsupported_layout_recovery_rejected_atomically(self):
        request = self.request()
        with sqlite3.connect(self.path) as db:
            db.execute('PRAGMA user_version=999')
        before = self.dump()
        with self.assertRaises(PersistenceError):
            self.recovery.recover(request)
        self.assertEqual(self.dump(), before)

    def test_layout_one_requires_explicit_future_upgrade(self):
        self.store.close()
        with sqlite3.connect(self.path) as db:
            db.execute('PRAGMA user_version=1')
        with self.assertRaises(PersistenceError):
            SQLiteSave(self.path, allowed_root=self.root)

    def test_transaction_failure_after_replace_rolls_back_all_tables(self):
        self.schedule([(10, 0, 'TEST a'), (20, 0, 'TEST b')])
        self.clock.advance(100)
        self.app.settle(self.settlement(budget=1))
        request = self.request()
        before = self.dump()
        class FailingStore(SQLiteSave):
            def _insert_receipt(adapter, receipt):
                if receipt.kind == 'recovery':
                    raise RuntimeError('TEST failure after Current/Previous/Receipt cleanup SQL')
                super()._insert_receipt(receipt)
        self.store.close()
        self.store = FailingStore(self.path, allowed_root=self.root)
        self.app = application(self.store, self.clock)
        self.recovery = RecoveryApplication(self.app, self.clock)
        with self.assertRaises(RuntimeError):
            self.recovery.recover(request)
        self.assertEqual(self.dump(), before)
        self.restart()
        self.assertEqual(self.query().generation, 1)
        self.assertIsNotNone(self.query().time['pending'])
        self.assertEqual(self.recovery.recover(request).status, 'SUCCESS')

    def test_sql_failure_at_receipt_rolls_back(self):
        request = self.request()
        before = self.dump()
        class FailingStore(SQLiteSave):
            def _insert_receipt(adapter, receipt):
                raise sqlite3.IntegrityError('TEST SQL failure')
        self.store.close()
        self.store = FailingStore(self.path, allowed_root=self.root)
        self.recovery = RecoveryApplication(application(self.store, self.clock), self.clock)
        with self.assertRaises(PersistenceError):
            self.recovery.recover(request)
        self.assertEqual(self.dump(), before)

    def test_invalid_new_generation_candidate_rolls_back(self):
        from src.application.persistent import PersistentApplication
        from tests.fixtures.persistence import references
        from tests.fixtures.foundation import registry
        def validation(snapshot):
            if snapshot.generation > 1:
                raise ValidationError('TEST invalid rollover candidate')
            return references(snapshot)
        app = PersistentApplication(self.store, registry(), {}, references=validation)
        self.recovery = RecoveryApplication(app, self.clock)
        self.assert_failure_atomic(self.request(), 'RECOVERY_CANDIDATE_INVALID')

    def test_current_pending_is_not_copied_into_recovered_state(self):
        self.schedule([(10, 0, 'TEST a'), (20, 0, 'TEST b')])
        self.clock.advance(100)
        self.app.settle(self.settlement(budget=1))
        self.assertIsNotNone(self.query().time['pending'])
        self.recovery.recover(self.request())
        self.assertIsNone(self.query().time['pending'])
        self.assertEqual(self.query().time['sim_time_ms'], 0)

    def test_valid_source_pending_is_cleared_but_frontier_preserved(self):
        self.schedule([(10, 0, 'TEST a'), (20, 0, 'TEST b'), (30, 0, 'TEST c')])
        self.clock.advance(100)
        first = self.app.settle(self.settlement(budget=1))
        self.app.checkpoint(self.save_id)
        source = self.query()
        self.app.settle(self.settlement(budget=1, continuation=first.result.continuation))
        self.recovery.recover(self.request())
        self.restart()
        self.assertEqual(self.query().time['sim_time_ms'], source.time['sim_time_ms'])
        self.assertEqual(self.query().domains, source.domains)
        self.assertIsNone(self.query().time['pending'])
        self.assertEqual(self.app.settle(self.settlement()).result.accepted_ms, 0)
        self.clock.advance(10)
        result = self.app.settle(self.settlement())
        self.assertEqual(result.result.processed_work, 1)
        self.assertEqual(self.query().domains['fixture']['event_trace'], ('TEST a', 'TEST b'))

    def test_invalid_source_pending_is_rejected_not_sanitized(self):
        self.schedule([(10, 0, 'TEST a'), (20, 0, 'TEST b')])
        self.clock.advance(100)
        self.app.settle(self.settlement(budget=1))
        self.app.checkpoint(self.save_id)
        request = self.request()
        self.corrupt('previous', transform=lambda value: value['time']['pending'].update(target_sim_ms=999))
        self.assert_failure_atomic(request, 'RECOVERY_CANDIDATE_INVALID')

    def test_old_generation_command_rejected_and_new_works(self):
        old = self.command()
        self.app.execute(old)
        self.recovery.recover(self.request())
        before = self.query()
        with self.assertRaises(ConflictError):
            self.app.execute(old)
        self.assertEqual(self.query(), before)
        self.app.execute(self.command())
        self.assertEqual(self.query().domains['fixture']['value'], 1)

    def test_old_generation_settlement_rejected(self):
        old = self.settlement()
        self.recovery.recover(self.request())
        before = self.query()
        with self.assertRaises(ConflictError):
            self.app.settle(old)
        self.assertEqual(self.query(), before)

    def test_old_continuation_with_new_request_rejected(self):
        self.schedule([(10, 0, 'TEST a'), (20, 0, 'TEST b')])
        self.clock.advance(100)
        old = self.app.settle(self.settlement(budget=1)).result.continuation
        self.recovery.recover(self.request())
        with self.assertRaises(ConflictError):
            self.app.settle(self.settlement(continuation=old))
        self.assertIsNone(self.query().time['pending'])

    def test_new_generation_can_use_old_command_request_uuid(self):
        old = self.command()
        self.app.execute(old)
        self.recovery.recover(self.request())
        new = self.command(request_id=old.request_id)
        self.app.execute(new)
        self.assertEqual(self.query().domains['fixture']['value'], 1)
        self.assertEqual(self.query().revision, 1)

    def test_receipts_pruned_only_for_target_save_and_old_generations(self):
        another = state()
        self.app.create(another)
        other_command = Command(another.save_id, 1, 0, str(uuid4()), 'test_increment', {'amount': 1})
        self.app.execute(other_command)
        request = self.request()
        result = self.recovery.recover(request)
        self.assertIsNone(self.store.receipt(self.save_id, 1, other_command.request_id))
        with sqlite3.connect(self.path) as db:
            scopes = list(db.execute('SELECT generation,request_id FROM receipts WHERE save_id=?', (self.save_id,)))
        self.assertEqual(scopes, [(2, request.request_id)])
        self.assertIsNotNone(self.store.receipt(another.save_id, 1, other_command.request_id))
        self.assertEqual(result.new_generation, 2)

    def test_recovery_success_replay_after_restart_never_rolls_again(self):
        request = self.request()
        result = self.recovery.recover(request)
        self.restart()
        self.assertEqual(self.recovery.recover(request), result)
        self.app.execute(self.command())
        self.assertEqual(self.recovery.recover(request), result)
        self.assertEqual((self.query().generation, self.query().revision), (2, 1))

    def test_recovery_request_id_different_intent_conflicts(self):
        request = self.request()
        self.recovery.recover(request)
        self.assert_failure_atomic(replace(request, reason='TEST changed reason'), 'CONFLICT')

    def test_recovery_uuid_is_not_gameplay_receipt(self):
        request = self.request()
        self.recovery.recover(request)
        with self.assertRaises(ConflictError):
            self.app.execute(self.command(request_id=request.request_id))
        self.assertEqual(self.query().revision, 0)

    def test_same_candidate_new_request_cannot_repeat_recovery(self):
        request = self.request()
        self.recovery.recover(request)
        self.assert_failure_atomic(replace(request, request_id=str(uuid4())), 'CONFLICT')
        self.assertEqual(self.recovery.inspect(self.save_id).status, 'NO_RECOVERY_AVAILABLE')
        self.assertEqual(self.query().generation, 2)

    def test_recovery_loses_race_to_new_normal_write(self):
        request = self.request()
        with SQLiteSave(self.path, allowed_root=self.root) as other:
            application(other).execute(self.command())
        self.assert_failure_atomic(request, 'CONFLICT')
        self.assertEqual(self.query().revision, 2)
        self.assertEqual(self.query().generation, 1)

    def test_true_concurrent_connections_only_one_rollover(self):
        observed = self.recovery.inspect(self.save_id)
        requests = [self.request(observed), self.request(observed)]
        barrier = threading.Barrier(2)
        results, errors = [], []
        def attempt(request):
            try:
                with SQLiteSave(self.path, allowed_root=self.root) as store:
                    clock = ManualClock(1000)
                    lifecycle = RecoveryApplication(application(store, clock), clock)
                    barrier.wait(timeout=5)
                    results.append(lifecycle.recover(request).status)
            except Exception as exc:
                errors.append(repr(exc))
        workers = [threading.Thread(target=attempt, args=(request,)) for request in requests]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=7)
        self.assertFalse(any(worker.is_alive() for worker in workers))
        self.assertEqual(errors, [])
        self.assertEqual(sorted(results), ['CONFLICT', 'SUCCESS'])
        self.assertEqual(self.query().generation, 2)

    def test_wall_claim_reanchors_without_old_elapsed_reward(self):
        self.clock.advance(10_000)
        self.app.settle(self.settlement())
        now = self.clock.value
        self.recovery.recover(self.request())
        self.assertEqual(self.query().time['last_settled_at_ms'], now)
        self.assertEqual(self.query().time['sim_time_ms'], self.initial.time['sim_time_ms'])
        result = self.app.settle(self.settlement()).result
        self.assertEqual(result.accepted_ms, 0)
        self.assertEqual(self.query().domains['fixture']['elapsed_ms'], 0)
        self.clock.advance(20)
        self.app.settle(self.settlement())
        self.assertEqual(self.query().domains['fixture']['elapsed_ms'], 20)

    def test_100h_offline_cannot_be_reclaimed_through_recovery(self):
        self.clock.advance(100 * 3600 * 1000)
        self.assertEqual(self.app.settle(self.settlement()).result.accepted_ms, OFFLINE_CAP_MS)
        self.recovery.recover(self.request())
        self.restart()
        self.assertEqual(self.app.settle(self.settlement()).result.accepted_ms, 0)
        self.assertEqual(self.query().time['sim_time_ms'], 0)

    def test_claim_witness_protects_corrupt_current_during_clock_rollback(self):
        self.clock.advance(10_000)
        self.app.settle(self.settlement())
        old_claim = self.clock.value
        self.corrupt()
        self.clock.value = 900
        result = self.recovery.recover(self.request())
        self.assertEqual(result.wall_anchor_ms, old_claim)
        self.assertEqual(self.query().time['last_settled_at_ms'], old_claim)
        self.clock.value = old_claim
        self.assertEqual(self.app.settle(self.settlement()).result.accepted_ms, 0)
        self.clock.advance(10)
        self.assertEqual(self.app.settle(self.settlement()).result.accepted_ms, 10)

    def test_invalid_durable_claim_blocks_recovery_atomically(self):
        request = self.request()
        with sqlite3.connect(self.path) as db:
            db.execute('UPDATE current SET wall_claim_digest=? WHERE save_id=?', ('bad', self.save_id))
        self.assert_failure_atomic(request, 'CONFLICT')
        self.assertEqual(self.recovery.inspect(self.save_id).status, 'CONFLICT')

    def test_negative_clock_does_not_write_recovery(self):
        request = self.request()
        self.clock.value = -1
        before = self.dump()
        with self.assertRaises(ValidationError):
            self.recovery.recover(request)
        self.assertEqual(self.dump(), before)

    def test_restart_preserves_new_lineage_and_no_pending(self):
        self.schedule([(10, 0, 'TEST a'), (20, 0, 'TEST b')])
        self.clock.advance(100)
        old = self.app.settle(self.settlement(budget=1)).result.continuation
        self.recovery.recover(self.request())
        expected = self.query()
        self.restart()
        self.assertEqual(self.query().to_dict(), expected.to_dict())
        self.assertIsNone(self.query().time['pending'])
        with self.assertRaises(ConflictError):
            self.app.settle(self.settlement(continuation=old))

    def test_real_subprocess_fresh_load_after_recovery(self):
        self.schedule([(10, 0, 'TEST a'), (20, 0, 'TEST b')])
        self.clock.advance(100)
        self.app.settle(self.settlement(budget=1))
        self.corrupt()
        result = self.recovery.recover(self.request())
        self.store.close()
        program = """import sys
from pathlib import Path
from uuid import uuid4
from src.core.save.sqlite import SQLiteSave
from src.application.memory import Command
from tests.fixtures.persistence import application
with SQLiteSave(Path(sys.argv[1]),allowed_root=Path(sys.argv[2])) as store:
    app=application(store)
    state=app.query(sys.argv[3])
    assert state.generation==2 and state.revision==0
    assert state.time['pending'] is None and state.time['sim_time_ms']==0
    assert state.time['last_settled_at_ms']==1100
    assert state.domains['fixture']['value']==0
    app.execute(Command(state.save_id,state.generation,state.revision,str(uuid4()),'test_increment',{'amount':1}))
"""
        run = subprocess.run([sys.executable, '-B', '-c', program, str(self.path), str(self.root), self.save_id],
                             cwd=V2_ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.restart()
        self.assertEqual((self.query().generation, self.query().revision), (2, 1))
        self.assertEqual(result.new_generation, 2)

    def test_recovery_result_metadata_is_compact_and_persisted(self):
        request = self.request()
        result = self.recovery.recover(request)
        data = asdict(result)
        self.assertEqual((data['old_generation'], data['new_generation'], data['source_revision'], data['new_revision']), (1, 2, 0, 0))
        self.assertNotIn('domains', data)
        self.assertNotIn('state', data)
        self.assertLess(len(canonical(data)), 1024)
        saved = self.store.receipt(self.save_id, 2, request.request_id)
        self.assertEqual(RecoveryResult(**dict(saved.payload)), result)

    def test_post_recovery_checkpoint_then_new_recovery_works(self):
        self.recovery.recover(self.request())
        self.app.execute(self.command())
        self.app.checkpoint(self.save_id)
        source = self.query()
        self.app.execute(self.command())
        self.corrupt()
        result = self.recovery.recover(self.request())
        self.assertEqual(result.new_generation, 3)
        self.assertEqual(self.query().domains, source.domains)
        self.assertEqual(self.query().revision, 0)
        self.assertEqual(self.recovery.inspect(self.save_id).status, 'NO_RECOVERY_AVAILABLE')

    def test_no_save_cannot_be_recovered(self):
        save_id = str(uuid4())
        self.assertEqual(self.recovery.inspect(save_id).reason, 'NO_SAVE')
        request = replace(self.request(), save_id=save_id)
        self.assert_failure_atomic(request, 'NO_RECOVERY_AVAILABLE')

    def test_no_previous_returns_explicit_status(self):
        another = state()
        self.app.create(another)
        self.assertEqual(self.recovery.inspect(another.save_id).status, 'NO_RECOVERY_AVAILABLE')
        from src.core.save.recovery import row_fingerprint
        current, _ = self.store.recovery_rows(another.save_id)
        request = RecoveryRequest(another.save_id, 1, row_fingerprint(current), '0'*64, str(uuid4()), 'TEST no previous')
        self.assert_failure_atomic(request, 'NO_RECOVERY_AVAILABLE')

    def test_invalid_request_rejected_without_write(self):
        before = self.dump()
        for updates in ({'request_id': 'bad'}, {'reason': ''}, {'current_fingerprint': 'bad'}, {'expected_generation': True}):
            with self.subTest(updates=updates), self.assertRaises(ValidationError):
                self.request(**updates)
        self.assertEqual(self.dump(), before)

    def test_recovery_receipt_corruption_detected_on_retry(self):
        request = self.request()
        self.recovery.recover(request)
        with sqlite3.connect(self.path) as db:
            db.execute('UPDATE receipts SET digest=? WHERE request_id=?', ('bad', request.request_id))
        before = self.dump()
        with self.assertRaises(CorruptSaveError):
            self.recovery.recover(request)
        self.assertEqual(self.dump(), before)

    def test_recovery_does_not_advance_simulation_or_draw_clock_on_inspect(self):
        self.clock.advance(1000)
        before = self.dump()
        self.recovery.inspect(self.save_id)
        self.assertEqual(self.clock.reads, 0)
        result = self.recovery.recover(self.request())
        self.assertEqual(self.clock.reads, 1)
        self.assertEqual(self.query().time['sim_time_ms'], 0)
        self.assertEqual(result.status, 'SUCCESS')
        self.assertNotEqual(self.dump(), before)

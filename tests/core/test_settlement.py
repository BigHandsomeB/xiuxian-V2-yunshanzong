"""Time/Settlement contract tests; no sleep, real rewards or persistence."""
from dataclasses import replace
import json
import unittest
from unittest.mock import patch
from uuid import uuid4

from src.application.memory import MemoryApplication
from src.core.state.envelope import StateEnvelope
from src.core.time.clock import SystemClock
from src.core.time.model import (
    Continuation, DEFAULT_GAME_DAY_MS, OFFLINE_CAP_MS, game_days, plan_window,
)
from src.core.validation import ConflictError, ValidationError
from tests.fixtures.foundation import command
from tests.fixtures.time import (
    ManualClock, application, apply, engine, initial, request, settle_all, simulation_content,
)


class SettlementTests(unittest.TestCase):
    def test_clock_boundary_injected_and_system_adapter_ms(self):
        clock = ManualClock()
        app = application(clock=clock)
        clock.advance(321)
        result = app.settle(request(app)).result
        self.assertEqual(result.to_sim_ms, 321)
        self.assertEqual(clock.reads, 1)
        with patch('src.core.time.clock.time_ns', return_value=1234567890):
            self.assertEqual(SystemClock().now_ms(), 1234)

    def test_120_seconds_is_one_game_day(self):
        self.assertEqual(DEFAULT_GAME_DAY_MS, 120000)
        self.assertEqual(game_days(119999), 0)
        self.assertEqual(game_days(120000), 1)
        self.assertEqual(game_days(240000), 2)
        clock = ManualClock(121000)
        app = application(clock=clock)
        app.settle(request(app))
        self.assertEqual(game_days(app.query().time['sim_time_ms']), 1)

    def test_zero_elapsed_is_noop_but_receipt_is_idempotent(self):
        app = application()
        before = app.query()
        req = request(app)
        receipt = app.settle(req)
        self.assertEqual(receipt.result.status, 'COMPLETE')
        self.assertEqual(app.query(), before)
        self.assertEqual(app.query().revision, 0)
        self.assertIs(app.settle(req), receipt)

    def test_negative_elapsed_and_clock_rollback_do_not_move_world(self):
        app = application(clock=ManualClock(900))
        before = app.query()
        result = app.settle(request(app)).result
        self.assertTrue(result.clock_rollback)
        self.assertEqual(result.accepted_ms, 0)
        self.assertEqual(app.query(), before)

    def test_query_never_reads_clock_or_invokes_engine(self):
        clock, core = ManualClock(999999), engine()
        app = application(clock=clock, settlement=core)
        before, records = app.query(), app.receipts()
        with patch.object(core, 'advance', side_effect=AssertionError('Query settled')):
            for _ in range(10):
                self.assertIs(app.query(), before)
        self.assertEqual(clock.reads, 0)
        self.assertEqual(app.receipts(), records)

    def test_wall_clock_and_simulation_positions_are_distinct(self):
        app = application(clock=ManualClock(5000))
        app.settle(request(app))
        self.assertEqual(app.query().time['last_settled_at_ms'], 5000)
        self.assertEqual(app.query().time['sim_time_ms'], 4000)

    def test_stable_order_is_due_priority_event_id(self):
        app = application([(10, 2, 'TEST later priority'), (10, 1, 'TEST first id'),
                           (10, 1, 'TEST second id'), (5, 9, 'TEST earlier time')],
                          clock=ManualClock(1010))
        result = app.settle(request(app)).result
        self.assertEqual(result.processed_work, 4)
        self.assertEqual(app.query().domains['fixture']['event_trace'],
                         ('TEST earlier time', 'TEST first id', 'TEST second id', 'TEST later priority'))

    def test_start_and_end_events_included_future_not_processed(self):
        app = application([(0, 0, 'TEST start'), (100, 0, 'TEST end'), (101, 0, 'TEST future')],
                          clock=ManualClock(1100))
        app.settle(request(app))
        part = app.query().domains['fixture']
        self.assertEqual(part['event_trace'], ('TEST start', 'TEST end'))
        self.assertEqual(len(part['scheduled']), 1)
        self.assertEqual(part['elapsed_ms'], 100)

    def test_event_before_committed_start_rejected_atomically(self):
        app = application(initial_state=initial([(9, 0, 'TEST stale')], sim_time=10),
                          clock=ManualClock(1100))
        before = app.query()
        with self.assertRaisesRegex(ValidationError, 'cursor'):
            app.settle(request(app))
        self.assertEqual(app.query(), before)
        self.assertEqual(app.receipts(), ())

    def test_target_event_not_reprocessed_in_next_window(self):
        clock = ManualClock(1100)
        app = application([(100, 0, 'TEST target')], clock=clock)
        app.settle(request(app))
        clock.advance(100)
        app.settle(request(app))
        self.assertEqual(app.query().domains['fixture']['value'], 1)
        self.assertEqual(app.query().domains['fixture']['elapsed_ms'], 200)

    def test_budget_produces_consistent_pending_and_cursor(self):
        app = application([(10, 0, 'TEST a'), (10, 0, 'TEST b'), (20, 0, 'TEST c')],
                          clock=ManualClock(1100))
        receipt = app.settle(request(app, budget=1))
        result, state = receipt.result, app.query()
        self.assertEqual(result.status, 'PENDING')
        self.assertEqual((result.from_sim_ms, result.to_sim_ms, result.target_sim_ms), (0, 10, 100))
        self.assertEqual(state.time['pending']['accrued_to_ms'], state.time['sim_time_ms'])
        self.assertEqual(state.time['pending']['revision'], state.revision)
        self.assertEqual(state.domains['fixture']['elapsed_ms'], 10)
        self.assertEqual(state.revision, 1)

    def test_same_time_resume_does_not_reaccrue_or_duplicate(self):
        app = application([(10, 0, 'TEST a'), (10, 0, 'TEST b'), (10, 0, 'TEST c')],
                          clock=ManualClock(1100))
        final, processed = settle_all(app, budget=1)
        self.assertEqual(final.status, 'COMPLETE')
        self.assertEqual(len(processed), len(set(processed)))
        self.assertEqual(app.query().domains['fixture']['value'], 3)
        self.assertEqual(app.query().domains['fixture']['elapsed_ms'], 100)
        self.assertIsNone(app.query().time['pending'])
        self.assertEqual(app.query().revision, 3)

    def test_full_vs_chunks_equal_simulation_with_commit_count_revision(self):
        base = initial([(10, 0, 'TEST a'), (10, 0, 'TEST b'), (30, 0, 'TEST c')])
        full = application(initial_state=base, clock=ManualClock(1100))
        chunked = application(initial_state=base, clock=ManualClock(1100))
        all_result = full.settle(request(full)).result
        final, processed = settle_all(chunked)
        self.assertEqual(simulation_content(full.query()), simulation_content(chunked.query()))
        self.assertEqual(all_result.processed_events, processed)
        self.assertEqual(full.query().revision, 1)
        self.assertEqual(chunked.query().revision, 3)

    def test_budget_exactly_covers_events_completes_tail_in_same_chunk(self):
        app = application([(10, 0, 'TEST a')], clock=ManualClock(1100))
        result = app.settle(request(app, budget=1)).result
        self.assertEqual(result.status, 'COMPLETE')
        self.assertEqual(result.to_sim_ms, 100)
        self.assertEqual(result.processed_work, 1)

    def test_stale_continuation_rejected_after_resume(self):
        app = application([(10, 0, 'TEST a'), (20, 0, 'TEST b'), (30, 0, 'TEST c')],
                          clock=ManualClock(1100))
        old = app.settle(request(app, budget=1)).result.continuation
        app.settle(request(app, budget=1, continuation=old))
        before = app.query()
        with self.assertRaises(ConflictError):
            app.settle(request(app, budget=1, continuation=old))
        self.assertEqual(app.query(), before)

    def test_wrong_generation_continuation_rejected(self):
        app = application([(10, 0, 'TEST a'), (20, 0, 'TEST b')], clock=ManualClock(1100))
        cont = app.settle(request(app, budget=1)).result.continuation
        before = app.query()
        with self.assertRaises(ConflictError):
            app.settle(request(app, continuation=replace(cont, generation=2)))
        self.assertEqual(app.query(), before)

    def test_wrong_target_or_same_revision_modified_state_rejected(self):
        app = application([(10, 0, 'TEST a'), (20, 0, 'TEST b')], clock=ManualClock(1100))
        cont = app.settle(request(app, budget=1)).result.continuation
        with self.assertRaises(ValidationError):
            app.settle(request(app, continuation=replace(cont, target_sim_ms=101)))
        raw = app.query().to_dict()
        raw['domains']['fixture']['value'] = 999
        changed = StateEnvelope.from_dict(raw)
        other = application(initial_state=changed)
        with self.assertRaises(ConflictError):
            other.settle(request(other, continuation=cont))

    def test_state_revision_changed_before_resume_rejected(self):
        app = application([(10, 0, 'TEST a'), (20, 0, 'TEST b')], clock=ManualClock(1100))
        cont = app.settle(request(app, budget=1)).result.continuation
        changed = replace(app.query(), revision=app.query().revision + 1)
        other = application(initial_state=changed)
        with self.assertRaises(ConflictError):
            other.settle(request(other, continuation=cont))

    def test_rules_version_changed_during_pending_rejected(self):
        app = application([(10, 0, 'TEST a'), (20, 0, 'TEST b')], clock=ManualClock(1100))
        cont = app.settle(request(app, budget=1)).result.continuation
        other = application(initial_state=app.query(), settlement=engine(rules_version='test_other_rules'))
        with self.assertRaises(ConflictError):
            other.settle(request(other, continuation=cont))

    def test_pending_json_round_trip_can_resume_without_lost_events(self):
        app = application([(10, 0, 'TEST a'), (10, 0, 'TEST b')], clock=ManualClock(1100))
        cont = app.settle(request(app, budget=1)).result.continuation
        copied = StateEnvelope.from_dict(json.loads(json.dumps(app.query().to_dict())))
        restarted = application(initial_state=copied)
        result = restarted.settle(request(restarted, continuation=cont)).result
        self.assertEqual(result.status, 'COMPLETE')
        self.assertEqual(restarted.query().domains['fixture']['value'], 2)
        self.assertEqual(restarted.query().domains['fixture']['elapsed_ms'], 100)

    def test_configured_hour_cap_and_excess_do_not_generate_effects(self):
        clock = ManualClock(1000 + 100 * 3600000)
        app = application([(OFFLINE_CAP_MS, 0, 'TEST cap'),
                           (OFFLINE_CAP_MS + 1, 0, 'TEST frozen')], clock=clock)
        result = app.settle(request(app)).result
        self.assertEqual(result.accepted_ms, OFFLINE_CAP_MS)
        self.assertEqual(result.discarded_ms, 100 * 3600000 - OFFLINE_CAP_MS)
        self.assertEqual(app.query().domains['fixture']['elapsed_ms'], OFFLINE_CAP_MS)
        self.assertEqual(app.query().domains['fixture']['test_cost_ms'], OFFLINE_CAP_MS)
        self.assertEqual(app.query().domains['fixture']['event_trace'], ('TEST cap',))

    def test_frozen_excess_cannot_be_reclaimed_by_repeated_settlement(self):
        clock = ManualClock(1000 + 100 * 3600000)
        app = application(clock=clock)
        app.settle(request(app))
        before = app.query()
        for _ in range(3):
            result = app.settle(request(app)).result
            self.assertEqual(result.accepted_ms, 0)
            self.assertEqual(app.query(), before)
        clock.advance(123)
        app.settle(request(app))
        self.assertEqual(app.query().time['sim_time_ms'], OFFLINE_CAP_MS + 123)

    def test_cap_not_reapplied_during_pending_and_clock_not_read_on_resume(self):
        clock = ManualClock(1000 + 100 * 3600000)
        app = application([(1, 0, 'TEST a'), (2, 0, 'TEST b')], clock=clock)
        result = app.settle(request(app, budget=1)).result
        anchor = app.query().time['last_settled_at_ms']
        clock.advance(100 * 3600000)
        result = app.settle(request(app, continuation=result.continuation)).result
        self.assertEqual(clock.reads, 1)
        self.assertEqual(app.query().time['last_settled_at_ms'], anchor)
        self.assertEqual(app.query().time['sim_time_ms'], OFFLINE_CAP_MS)
        self.assertEqual(result.discarded_ms, 100 * 3600000 - OFFLINE_CAP_MS)

    def test_online_segments_and_offline_single_window_share_rules(self):
        base = initial([(10, 0, 'TEST change rate', {'rate': 3}), (25, 0, 'TEST event')])
        online_clock, offline_clock = ManualClock(), ManualClock(1100)
        online = application(initial_state=base, clock=online_clock)
        offline = application(initial_state=base, clock=offline_clock)
        offline.settle(request(offline))
        for delta in (10, 7, 8, 25, 50):
            online_clock.advance(delta)
            online.settle(request(online))
        self.assertEqual(simulation_content(online.query()), simulation_content(offline.query()))
        self.assertEqual(online.query().domains['fixture']['elapsed_ms'], 280)

    def test_simulation_independent_of_fps_and_query_frequency(self):
        base = initial([(50, 0, 'TEST event')])
        outcomes = []
        for fps in (5, 30, 60):
            clock = ManualClock(1100)
            app = application(initial_state=base, clock=clock)
            for _ in range(fps):
                app.query()  # Arbitrary rendering/read count contributes no time.
            app.settle(request(app))
            outcomes.append(app.query())
        self.assertEqual(outcomes[0], outcomes[1])
        self.assertEqual(outcomes[1], outcomes[2])

    def test_large_wall_jump_still_capped(self):
        app = application(clock=ManualClock(10 ** 15))
        app.settle(request(app))
        self.assertEqual(app.query().time['sim_time_ms'], OFFLINE_CAP_MS)

    def test_event_failure_rolls_back_entire_current_chunk(self):
        app = application([(10, 0, 'TEST a'), (20, 0, 'TEST fail', {'reject': True})],
                          clock=ManualClock(1100))
        before = app.query()
        with self.assertRaisesRegex(ValidationError, 'failed'):
            app.settle(request(app))
        self.assertEqual(app.query(), before)
        self.assertEqual(app.receipts(), ())

    def test_failure_on_later_chunk_preserves_prior_commit_and_pending(self):
        app = application([(10, 0, 'TEST a'), (20, 0, 'TEST fail', {'reject': True})],
                          clock=ManualClock(1100))
        cont = app.settle(request(app, budget=1)).result.continuation
        before, records = app.query(), app.receipts()
        with self.assertRaises(ValidationError):
            app.settle(request(app, continuation=cont))
        self.assertEqual(app.query(), before)
        self.assertEqual(app.receipts(), records)
        self.assertEqual(app.query().domains['fixture']['value'], 1)

    def test_invalid_candidate_and_accrual_failure_do_not_leak(self):
        app = application([(10, 0, 'TEST invalid', {'invalid': True})], clock=ManualClock(1100))
        before = app.query()
        with self.assertRaises(ValidationError):
            app.settle(request(app))
        self.assertEqual(app.query(), before)
        def fail(partition, start, end):
            partition['value'] = 100
            raise RuntimeError('TEST accrual failed')
        other = application(clock=ManualClock(1100), settlement=engine(elapsed=fail))
        before = other.query()
        with self.assertRaises(RuntimeError):
            other.settle(request(other))
        self.assertEqual(other.query(), before)

    def test_request_retry_does_not_advance_to_next_chunk_or_read_clock(self):
        clock = ManualClock(1100)
        app = application([(10, 0, 'TEST a'), (20, 0, 'TEST b')], clock=clock)
        req = request(app, budget=1)
        receipt = app.settle(req)
        before = app.query()
        self.assertIs(app.settle(req), receipt)
        self.assertEqual(app.query(), before)
        self.assertEqual(clock.reads, 1)
        with self.assertRaises(ConflictError):
            app.settle(replace(req, max_events=2))

    def test_gameplay_and_settlement_share_one_authority_and_request_namespace(self):
        app = application(clock=ManualClock(1100))
        action = command(app)
        app.execute(action)
        with self.assertRaises(ConflictError):
            app.settle(request(app, request_id=action.request_id))
        app.settle(request(app))
        self.assertEqual(app.query().revision, 2)
        self.assertEqual(app.query().domains['fixture']['value'], 1)

    def test_gameplay_blocked_during_pending_and_allowed_after_completion(self):
        app = application([(10, 0, 'TEST a'), (20, 0, 'TEST b')], clock=ManualClock(1100))
        cont = app.settle(request(app, budget=1)).result.continuation
        with self.assertRaises(ConflictError):
            app.execute(command(app))
        app.settle(request(app, continuation=cont))
        app.execute(command(app))
        self.assertEqual(app.query().domains['fixture']['value'], 3)

    def test_pending_without_continuation_and_continuation_without_pending_rejected(self):
        app = application([(10, 0, 'TEST a'), (20, 0, 'TEST b')], clock=ManualClock(1100))
        cont = app.settle(request(app, budget=1)).result.continuation
        with self.assertRaises(ConflictError):
            app.settle(request(app))
        app.settle(request(app, continuation=cont))
        with self.assertRaises(ConflictError):
            app.settle(request(app, continuation=cont))

    def test_future_event_generation_and_zero_time_rescheduling_rules(self):
        good = application([(10, 0, 'TEST create', {'new_due': 20})], clock=ManualClock(1100))
        good.settle(request(good))
        self.assertEqual(good.query().domains['fixture']['value'], 2)
        for new_due in (9, 10):
            bad = application([(10, 0, 'TEST create', {'new_due': new_due})], clock=ManualClock(1100))
            before = bad.query()
            with self.assertRaises(ValidationError):
                bad.settle(request(bad))
            self.assertEqual(bad.query(), before)

    def test_invalid_budget_and_clock_values_rejected_without_mutation(self):
        app = application()
        for budget in (0, -1, True, 1.5):
            with self.subTest(budget=budget), self.assertRaises(ValidationError):
                request(app, budget=budget)
        for now in (-1, True, 1000.5):
            other = application(clock=ManualClock(now))
            before = other.query()
            with self.subTest(now=now), self.assertRaises(ValidationError):
                other.settle(request(other))
            self.assertEqual(other.query(), before)

    def test_wrong_request_generation_revision_or_save_rejected(self):
        app = application()
        for change in ({'generation': 2}, {'expected_revision': 1}, {'save_id': str(uuid4())}):
            with self.subTest(change=change), self.assertRaises(ConflictError):
                app.settle(request(app, **change))
        self.assertEqual(app.query().revision, 0)

    def test_cross_save_continuation_rejected(self):
        app = application([(10, 0, 'TEST a'), (20, 0, 'TEST b')], clock=ManualClock(1100))
        cont = app.settle(request(app, budget=1)).result.continuation
        with self.assertRaises(ConflictError):
            app.settle(request(app, continuation=replace(cont, save_id=str(uuid4()))))

    def test_pending_watermark_format_and_cap_are_validated(self):
        app = application([(10, 0, 'TEST a'), (20, 0, 'TEST b')], clock=ManualClock(1100))
        app.settle(request(app, budget=1))
        original = app.query().to_dict()
        for change in ({'version': True}, {'generation': True}, {'accrued_to_ms': 9},
                       {'accepted_ms': 72 * 3600000 + 1,
                        'target_sim_ms': 72 * 3600000 + 1}, {'last_order': [9, 0, 'TEST bad']}):
            raw = json.loads(json.dumps(original))
            raw['time']['pending'].update(change)
            malformed = StateEnvelope.from_dict(raw)
            other = application(initial_state=malformed)
            with self.subTest(change=change), self.assertRaises(ValidationError):
                other.settle(request(other, continuation=Continuation.for_state(malformed)))
            self.assertEqual(other.query(), malformed)

    def test_previously_accepted_72h_pending_is_preserved(self):
        app = application([(10, 0, 'TEST a'), (20, 0, 'TEST b')], clock=ManualClock(1100))
        app.settle(request(app, budget=1))
        raw = app.query().to_dict()
        raw['time']['pending'].update(accepted_ms=72*3600000, target_sim_ms=72*3600000)
        old = StateEnvelope.from_dict(raw)
        other = application(initial_state=old)
        result = other.settle(request(other, continuation=Continuation.for_state(old))).result
        self.assertEqual(result.target_sim_ms, 72*3600000)
        self.assertEqual(result.accepted_ms, 72*3600000)
        self.assertEqual(result.discarded_ms, 0)
        self.assertEqual(other.query().time['sim_time_ms'], 72*3600000)

    def test_handler_must_consume_event_and_ids_must_be_unique(self):
        def do_not_consume(partition, event):
            partition['value'] += 1
        app = application([(10, 0, 'TEST a')], clock=ManualClock(1100),
                          settlement=engine(event_apply=do_not_consume))
        before = app.query()
        with self.assertRaisesRegex(ValidationError, 'consume'):
            app.settle(request(app))
        self.assertEqual(app.query(), before)
        raw = before.to_dict()
        raw['domains']['fixture']['scheduled'].append(raw['domains']['fixture']['scheduled'][0].copy())
        other = application(initial_state=StateEnvelope.from_dict(raw), clock=ManualClock(1100))
        with self.assertRaisesRegex(ValidationError, 'duplicate'):
            other.settle(request(other))

    def test_unallocated_event_identity_and_negative_due_rejected(self):
        base = initial([(10, 0, 'TEST a')])
        for change in ({'event_id': base.save_id + ':1:e:101'}, {'due_sim_ms': -1}):
            raw = base.to_dict()
            raw['domains']['fixture']['scheduled'][0].update(change)
            other = application(initial_state=StateEnvelope.from_dict(raw), clock=ManualClock(1100))
            before = other.query()
            with self.subTest(change=change), self.assertRaises(ValidationError):
                other.settle(request(other))
            self.assertEqual(other.query(), before)

    def test_partition_aliases_do_not_escape_settlement_commit(self):
        leaked = []
        def leaking(partition, event):
            apply(partition, event)
            leaked.append(partition)
        app = application([(10, 0, 'TEST a')], clock=ManualClock(1100),
                          settlement=engine(event_apply=leaking))
        app.settle(request(app))
        leaked[0]['value'] = 999
        self.assertEqual(app.query().domains['fixture']['value'], 1)

    def test_query_pending_is_readonly_even_when_clock_has_moved(self):
        clock = ManualClock(1100)
        app = application([(10, 0, 'TEST a'), (20, 0, 'TEST b')], clock=clock)
        app.settle(request(app, budget=1))
        before = app.query()
        clock.advance(1000)
        for _ in range(5):
            self.assertIs(app.query(), before)
        self.assertEqual(clock.reads, 1)
        self.assertEqual(app.query().time['sim_time_ms'], 10)

    def test_arbitrary_millisecond_segments_do_not_accumulate_float_error(self):
        base = initial()
        whole = application(initial_state=base, clock=ManualClock(2003))
        clock = ManualClock()
        parts = application(initial_state=base, clock=clock)
        whole.settle(request(whole))
        for elapsed in (1, 2, 333, 17, 650):
            clock.advance(elapsed)
            parts.settle(request(parts))
        self.assertEqual(simulation_content(whole.query()), simulation_content(parts.query()))

    def test_callback_validation_and_budget_exclude_clock_cpu_speed(self):
        base = initial([(10, 0, 'TEST a'), (20, 0, 'TEST b'), (30, 0, 'TEST c')])
        first = application(initial_state=base, clock=ManualClock(1100))
        second = application(initial_state=base, clock=ManualClock(1100))
        a = first.settle(request(first, budget=1)).result
        b = second.settle(request(second, budget=1)).result
        self.assertEqual(a, b)
        self.assertEqual(first.query(), second.query())

    def test_clock_rollback_after_progress_does_not_reaccrue(self):
        clock = ManualClock(1100)
        app = application(clock=clock)
        app.settle(request(app))
        before = app.query()
        clock.advance(-50)
        app.settle(request(app))
        self.assertEqual(app.query(), before)
        clock.advance(100)
        app.settle(request(app))
        self.assertEqual(app.query().domains['fixture']['elapsed_ms'], 150)

    def test_elapsed_callback_cannot_hide_an_event_inside_skipped_tail(self):
        def schedule_in_tail(partition, start, end):
            partition['scheduled'][0]['due_sim_ms'] = end - 1
        app = application([(200, 0, 'TEST future')], clock=ManualClock(1100),
                          settlement=engine(elapsed=schedule_in_tail))
        before = app.query()
        with self.assertRaisesRegex(ValidationError, 'elapsed handlers'):
            app.settle(request(app))
        self.assertEqual(app.query(), before)

    def test_settlement_configuration_and_explicit_operation_validation(self):
        from tests.fixtures.foundation import application as no_time_app, registry
        plain = no_time_app()
        with self.assertRaises(ValidationError):
            plain.settle(request(plain))
        with self.assertRaises(ValidationError):
            MemoryApplication(initial(), registry(), {}, settlement_engine=engine())
        with self.assertRaises(ValidationError):
            MemoryApplication(initial(), registry(), {}, settlement_engine=object(), clock=ManualClock())

    def test_cross_domain_event_order_independent_of_registration_order(self):
        from src.core.time.engine import SettlementEngine
        from src.core.time.model import SimulationDomain
        from tests.fixtures.time import events, accrue, validate
        base = initial([(10, 1, 'TEST first')])
        raw = base.to_dict()
        other = json.loads(json.dumps(raw['domains']['fixture']))
        other['scheduled'][0].update(event_id=base.save_id + ':1:e:2', domain='fixture_other')
        other['scheduled'][0]['payload']['label'] = 'TEST second'
        raw['domains']['fixture_other'] = other
        base = StateEnvelope.from_dict(raw)
        spec = SimulationDomain(events, apply, accrue, validate)
        left = application(initial_state=base, clock=ManualClock(1100),
                           settlement=SettlementEngine({'fixture': spec, 'fixture_other': spec}))
        right = application(initial_state=base, clock=ManualClock(1100),
                            settlement=SettlementEngine({'fixture_other': spec, 'fixture': spec}))
        a = left.settle(request(left)).result
        b = right.settle(request(right)).result
        self.assertEqual(a.processed_events, b.processed_events)
        self.assertEqual(left.query(), right.query())

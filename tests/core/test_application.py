"""Command/query ownership, optimistic guards and transaction tests."""
from dataclasses import replace
import unittest
from unittest.mock import patch
from uuid import uuid4

from src.application.memory import Command, CommandSpec, MemoryApplication
from src.core.state.envelope import StateEnvelope
from src.core.validation import ConflictError, NotFoundError, ValidationError
from src.data.registry import DefinitionKey, DefinitionRegistry
from tests.fixtures.foundation import application, command, registry, state


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.definitions = registry()
        self.app = application(definitions=self.definitions)

    def assert_unchanged(self, before, records):
        self.assertEqual(self.app.query(), before)
        self.assertEqual(self.app.receipts(), records)

    def test_query_has_no_state_revision_generation_or_receipt_effects(self):
        before, records = self.app.query(), self.app.receipts()
        entry = self.definitions.lookup(DefinitionKey('fixture', 'test_entry'))
        with patch.object(MemoryApplication, 'execute', side_effect=AssertionError('Query ran command')), \
             patch.object(StateEnvelope, 'with_domain', side_effect=AssertionError('Query mutated')):
            for _ in range(5):
                self.assertIs(self.app.query(), before)
        self.assert_unchanged(before, records)
        self.assertEqual(before.time, self.app.query().time)
        self.assertEqual(before.identity, self.app.query().identity)
        self.assertIs(self.definitions.lookup(entry.key), entry)

    def test_successful_command_changes_only_owned_partition_and_revision(self):
        before = self.app.query()
        receipt = self.app.execute(command(self.app, amount=3))
        after = self.app.query()
        self.assertEqual(after.domains['fixture']['value'], 3)
        self.assertEqual(after.revision, before.revision + 1)
        self.assertEqual(receipt.committed_revision, after.revision)
        self.assertEqual(after.domains['fixture_other'], before.domains['fixture_other'])
        self.assertEqual(after.generation, before.generation)
        self.assertEqual(after.time, before.time)
        self.assertEqual(after.identity, before.identity)
        self.assertEqual(before.domains['fixture']['value'], 0)

    def test_invalid_payload_has_no_side_effect(self):
        before, records = self.app.query(), self.app.receipts()
        for payload in ({}, {'amount': -1}, {'amount': True}, {'amount': 1, 'unexpected': 1}):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                self.app.execute(command(self.app, payload=payload))
            self.assert_unchanged(before, records)

    def test_late_handler_failure_discards_partial_candidate(self):
        before, records = self.app.query(), self.app.receipts()
        with self.assertRaisesRegex(ValidationError, 'after mutation'):
            self.app.execute(command(self.app, payload={'amount': 9, 'reject': True}))
        self.assert_unchanged(before, records)

    def test_unexpected_handler_failure_also_discards_candidate(self):
        def broken(partition, payload):
            partition['value'] = 100
            raise RuntimeError('TEST unexpected error')
        self.app = application(transition=broken)
        before, records = self.app.query(), self.app.receipts()
        with self.assertRaises(RuntimeError):
            self.app.execute(command(self.app))
        self.assert_unchanged(before, records)

    def test_invalid_candidate_and_result_are_not_committed(self):
        for invalid_result in (False, True):
            def broken(partition, payload):
                partition['value'] = 20
                if invalid_result:
                    return object()
                partition['value'] = float('nan')
                return 20
            self.app = application(transition=broken)
            before, records = self.app.query(), self.app.receipts()
            with self.subTest(invalid_result=invalid_result), self.assertRaises(ValidationError):
                self.app.execute(command(self.app))
            self.assert_unchanged(before, records)

    def test_stale_revision_rejected(self):
        self.app.execute(command(self.app))
        before, records = self.app.query(), self.app.receipts()
        with self.assertRaisesRegex(ConflictError, 'revision'):
            self.app.execute(command(self.app, expected_revision=0))
        self.assert_unchanged(before, records)

    def test_wrong_generation_and_save_rejected_before_execution(self):
        before, records = self.app.query(), self.app.receipts()
        for fields in ({'generation': 2}, {'save_id': str(uuid4())}):
            with self.subTest(fields=fields), self.assertRaises(ConflictError):
                self.app.execute(command(self.app, **fields))
        self.assert_unchanged(before, records)

    def test_duplicate_request_replays_before_stale_revision_check(self):
        request = command(self.app)
        receipt = self.app.execute(request)
        self.app.execute(command(self.app, amount=2))
        before, records = self.app.query(), self.app.receipts()
        self.assertIs(self.app.execute(request), receipt)
        self.assert_unchanged(before, records)
        self.assertEqual(before.domains['fixture']['value'], 3)

    def test_duplicate_request_with_new_revision_replays_same_intent(self):
        request = command(self.app)
        receipt = self.app.execute(request)
        self.assertIs(self.app.execute(replace(request, expected_revision=1)), receipt)
        self.assertEqual(self.app.query().revision, 1)

    def test_request_id_reused_with_different_intent_conflicts(self):
        request = command(self.app)
        self.app.execute(request)
        before, records = self.app.query(), self.app.receipts()
        for change in ({'payload': {'amount': 2}}, {'name': 'another_test'}, {'version': 2}):
            with self.subTest(change=change), self.assertRaises(ConflictError):
                self.app.execute(replace(request, **change))
            self.assert_unchanged(before, records)

    def test_payload_key_order_does_not_change_idempotency(self):
        request = command(self.app, payload={'amount': 1, 'reject': False})
        receipt = self.app.execute(request)
        self.assertIs(self.app.execute(replace(request, payload={'reject': False, 'amount': 1})), receipt)
        self.assertEqual(len(self.app.receipts()), 1)

    def test_distinct_request_ids_apply_normally(self):
        self.app.execute(command(self.app))
        self.app.execute(command(self.app))
        self.assertEqual(self.app.query().domains['fixture']['value'], 2)
        self.assertEqual(self.app.query().revision, 2)
        self.assertEqual(len(self.app.receipts()), 2)

    def test_failed_request_has_no_receipt_and_can_retry_after_valid_input(self):
        request = command(self.app, payload={'amount': 1, 'reject': True})
        with self.assertRaises(ValidationError):
            self.app.execute(request)
        self.assertEqual(self.app.receipts(), ())
        self.app.execute(replace(request, payload={'amount': 1}))
        self.assertEqual(self.app.query().revision, 1)

    def test_query_and_command_snapshots_are_not_mutable_authorities(self):
        snapshot = self.app.query()
        with self.assertRaises(TypeError):
            snapshot.domains['fixture']['value'] = 700
        receipt = self.app.execute(command(self.app))
        with self.assertRaises(TypeError):
            receipt.result['value'] = 700
        detached = self.app.query().to_dict()
        detached['domains']['fixture']['markers'].append('not committed')
        self.assertEqual(self.app.query().domains['fixture']['markers'], ('TEST command',))

    def test_definition_access_and_state_mutation_are_isolated(self):
        entry = self.definitions.lookup(DefinitionKey('fixture', 'test_entry'))
        before = self.app.query()
        self.definitions.lookup(entry.key)
        self.assertEqual(self.app.query(), before)
        self.app.execute(command(self.app))
        self.assertIs(self.definitions.lookup(entry.key), entry)
        self.assertEqual(entry.display_name, 'TEST 测试定义')

    def test_caller_and_handler_aliases_cannot_mutate_committed_state(self):
        payload = {'amount': 1}
        request = command(self.app, payload=payload)
        payload['amount'] = 100
        leaked = []
        def transition(partition, value):
            partition['value'] += value['amount']
            leaked.append(partition)
            return partition
        self.app = application(transition=transition)
        request = replace(request, save_id=self.app.query().save_id)
        receipt = self.app.execute(request)
        leaked[0]['value'] = 900
        self.assertEqual(self.app.query().domains['fixture']['value'], 1)
        self.assertEqual(receipt.result['value'], 1)

    def test_noop_receipt_does_not_increment_state_revision(self):
        self.app = application(transition=lambda partition, payload: {'test': 'no change'})
        request = command(self.app)
        receipt = self.app.execute(request)
        self.assertEqual(self.app.query().revision, 0)
        self.assertIs(self.app.execute(request), receipt)
        self.assertEqual(len(self.app.receipts()), 1)

    def test_pending_state_blocks_command_without_query_settlement(self):
        initial = state()
        raw = initial.to_dict()
        raw['time']['pending'] = {'test_pending_target': 100}
        self.app = application(initial=StateEnvelope.from_dict(raw))
        before, records = self.app.query(), self.app.receipts()
        with self.assertRaisesRegex(ConflictError, 'pending'):
            self.app.execute(command(self.app))
        self.assert_unchanged(before, records)
        self.assertEqual(self.app.query().time['sim_time_ms'], 0)

    def test_unknown_command_and_version_are_rejected(self):
        before, records = self.app.query(), self.app.receipts()
        with self.assertRaises(NotFoundError):
            self.app.execute(command(self.app, name='unknown_test'))
        with self.assertRaises(ValidationError):
            self.app.execute(command(self.app, version=2))
        self.assert_unchanged(before, records)

    def test_request_metadata_and_payload_format_validation(self):
        for change in ({'request_id': 'bad'}, {'request_id': str(uuid4()).upper()},
                       {'expected_revision': True}, {'generation': 0},
                       {'payload': []}, {'payload': {'amount': float('inf')}}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                command(self.app, **change)

    def test_initial_state_must_use_sealed_matching_content(self):
        catalog = DefinitionRegistry(schema_version=1, content_version='test_fixture_v1')
        with self.assertRaises(ValidationError):
            application(definitions=catalog)
        with self.assertRaises(ConflictError):
            application(initial=state(content_version='test_fixture_v2'))
        with self.assertRaises(ValidationError):
            MemoryApplication(state(), registry(),
                              {'test_unknown_domain': CommandSpec('missing', lambda p, v: None)})

    def test_replayed_request_with_wrong_generation_is_still_rejected(self):
        request = command(self.app)
        self.app.execute(request)
        before, records = self.app.query(), self.app.receipts()
        with self.assertRaisesRegex(ConflictError, 'generation'):
            self.app.execute(replace(request, generation=request.generation + 1))
        self.assert_unchanged(before, records)

    def test_query_does_not_copy_or_serialize_entire_state(self):
        with patch.object(StateEnvelope, 'to_dict', side_effect=AssertionError('Query copied state')):
            self.assertEqual(self.app.query().revision, 0)

    def test_input_state_does_not_become_another_authority(self):
        initial = state()
        self.app = application(initial=initial)
        self.app.execute(command(self.app))
        self.assertEqual(initial.revision, 0)
        self.assertEqual(initial.domains['fixture']['value'], 0)
        self.assertEqual(self.app.query().revision, 1)

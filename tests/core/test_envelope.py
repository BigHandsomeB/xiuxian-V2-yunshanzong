"""Minimal envelope validation, alias isolation and memory round-trip."""
from dataclasses import FrozenInstanceError
import json
import unittest

from src.core.state.envelope import StateEnvelope
from src.core.validation import ValidationError
from tests.fixtures.foundation import state


class EnvelopeTests(unittest.TestCase):
    def test_minimal_envelope_has_contract_fields(self):
        snapshot = state()
        self.assertEqual((snapshot.save_schema_version, snapshot.data_schema_version), (1, 1))
        self.assertEqual((snapshot.generation, snapshot.revision), (1, 0))
        self.assertEqual(snapshot.time['day_length_ms'], 120000)
        self.assertIsNone(snapshot.time['pending'])
        self.assertEqual(snapshot.identity['rng_streams'], {})

    def test_nested_state_is_immutable(self):
        snapshot = state()
        with self.assertRaises(FrozenInstanceError):
            snapshot.revision = 50
        with self.assertRaises(TypeError):
            snapshot.domains['fixture']['value'] = 50
        with self.assertRaises(TypeError):
            snapshot.time['sim_time_ms'] = 50
        with self.assertRaises(AttributeError):
            snapshot.domains['fixture']['markers'].append('bad')

    def test_input_containers_and_serialized_copy_are_detached(self):
        value = state().to_dict()
        envelope = StateEnvelope.from_dict(value)
        value['domains']['fixture']['markers'].append('caller write')
        exported = envelope.to_dict()
        exported['domains']['fixture']['value'] = 90
        self.assertEqual(envelope.domains['fixture']['markers'], ())
        self.assertEqual(envelope.domains['fixture']['value'], 0)

    def test_json_round_trip_in_memory(self):
        original = state()
        decoded = json.loads(json.dumps(original.to_dict(), allow_nan=False))
        self.assertEqual(StateEnvelope.from_dict(decoded), original)

    def test_generation_revision_and_schema_validation(self):
        for patch in ({'generation': 0}, {'generation': True}, {'revision': -1},
                      {'revision': True}, {'save_schema_version': 2},
                      {'data_schema_version': 2}, {'save_id': 'not_uuid'}):
            with self.subTest(patch=patch), self.assertRaises(ValidationError):
                state(**patch)

    def test_unknown_and_missing_envelope_fields(self):
        value = state().to_dict()
        with self.assertRaises(ValidationError):
            StateEnvelope.from_dict({**value, 'extra': 1})
        del value['identity']
        with self.assertRaises(ValidationError):
            StateEnvelope.from_dict(value)

    def test_invalid_time_identity_and_domain_shapes(self):
        baseline = state().to_dict()
        for patch in ({'time': {}}, {'time': {**baseline['time'], 'sim_time_ms': -1}},
                      {'time': {**baseline['time'], 'pending': 'bad'}},
                      {'identity': {**baseline['identity'], 'rng_streams': {'unsupported': 1}}},
                      {'domains': {'bad-domain': {}}}, {'domains': {'fixture': []}}):
            with self.subTest(patch=patch), self.assertRaises(ValidationError):
                state(**patch)

    def test_nonfinite_and_non_json_domain_values_rejected(self):
        for bad in (float('nan'), float('inf'), object(), {1: 'bad key'}):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                state(domains={'fixture': {'value': bad}})

    def test_cyclic_containers_rejected_but_shared_subtrees_allowed(self):
        cycle = []
        cycle.append(cycle)
        with self.assertRaisesRegex(ValidationError, 'cyclic'):
            state(domains={'fixture': {'value': cycle}})
        shared = {'test': [1]}
        snapshot = state(domains={'fixture': {'left': shared, 'right': shared}})
        shared['test'].append(2)
        self.assertEqual(snapshot.domains['fixture']['left']['test'], (1,))
        self.assertEqual(snapshot.domains['fixture']['right']['test'], (1,))

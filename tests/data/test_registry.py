"""Definition identity/reference/schema tests; all content is TEST ONLY."""
from dataclasses import FrozenInstanceError, replace
import json
import unittest

from src.core.validation import ConflictError, DuplicateError, NotFoundError, ValidationError
from src.data.registry import Definition, DefinitionKey, DefinitionRegistry
from tests.fixtures.foundation import PACKAGE, registry


class RegistryTests(unittest.TestCase):
    def test_valid_registration_lookup_and_existence(self):
        entry = Definition('fixture', 'test_entry', 'TEST Name')
        catalog = DefinitionRegistry(schema_version=1, content_version='test_v1')
        catalog.register(entry)
        catalog.seal()
        self.assertIs(catalog.lookup(entry.key), entry)
        self.assertTrue(catalog.contains(entry.key))
        self.assertFalse(catalog.contains(DefinitionKey('fixture', 'missing')))

    def test_invalid_ids_and_domains_rejected(self):
        for invalid in ('', '中文', 'A_test', 'test-id', '1test', 'test\n', None, 7):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValidationError):
                    Definition('fixture', invalid, 'TEST')
                with self.assertRaises(ValidationError):
                    Definition(invalid, 'test_entry', 'TEST')

    def test_invalid_display_names_rejected(self):
        for name in ('', '  ', None, 42, 'TEST\x00'):
            with self.subTest(name=name), self.assertRaises(ValidationError):
                Definition('fixture', 'test_entry', name)

    def test_duplicate_identity_never_overwrites(self):
        catalog = DefinitionRegistry(schema_version=1, content_version='test_v1')
        original = Definition('fixture', 'test_entry', 'TEST first')
        catalog.register(original)
        with self.assertRaises(DuplicateError):
            catalog.register(replace(original, display_name='TEST second'))
        catalog.seal()
        self.assertEqual(catalog.lookup(original.key).display_name, 'TEST first')

    def test_same_local_id_in_different_domains_is_distinct(self):
        catalog = DefinitionRegistry(schema_version=1, content_version='test_v1')
        for domain in ('fixture', 'fixture_other'):
            catalog.register(Definition(domain, 'test_entry', 'TEST'))
        catalog.seal()
        self.assertNotEqual(catalog.lookup(DefinitionKey('fixture', 'test_entry')).key,
                            catalog.lookup(DefinitionKey('fixture_other', 'test_entry')).key)

    def test_unknown_definition_raises_specific_error(self):
        with self.assertRaises(NotFoundError):
            registry().lookup(DefinitionKey('fixture', 'missing'))

    def test_display_name_change_preserves_identity(self):
        original = Definition('fixture', 'test_entry', 'TEST Old')
        renamed = replace(original, display_name='TEST 新名称')
        self.assertEqual(original.key, renamed.key)
        self.assertNotEqual(original.display_name, renamed.display_name)

    def test_definitions_and_reference_tuple_are_immutable(self):
        entry = registry().lookup(DefinitionKey('fixture', 'test_reference'))
        with self.assertRaises(FrozenInstanceError):
            entry.display_name = 'changed'
        with self.assertRaises(FrozenInstanceError):
            entry.references[0].machine_id = 'changed'
        with self.assertRaises(ValidationError):
            Definition('fixture', 'test_entry', 'TEST', references=[])

    def test_missing_reference_rejected_before_seal(self):
        catalog = DefinitionRegistry(schema_version=1, content_version='test_v1')
        catalog.register(Definition('fixture', 'test_ref', 'TEST',
                                    (DefinitionKey('fixture', 'missing'),)))
        with self.assertRaisesRegex(ValidationError, 'missing'):
            catalog.seal()
        self.assertFalse(catalog.is_sealed)
        with self.assertRaises(ConflictError):
            catalog.lookup(DefinitionKey('fixture', 'test_ref'))

    def test_forward_reference_resolves_after_complete_loading(self):
        package = {**PACKAGE, 'definitions': list(reversed(PACKAGE['definitions']))}
        catalog = DefinitionRegistry.from_json(json.dumps(package))
        self.assertTrue(catalog.contains(DefinitionKey('fixture', 'test_reference')))

    def test_registry_is_sealed_against_runtime_registration(self):
        with self.assertRaises(ConflictError):
            registry().register(Definition('fixture', 'test_new', 'TEST'))

    def test_duplicate_json_keys_rejected_at_any_depth(self):
        for source in ('{"schema_version":1,"schema_version":1}',
                       '{"definitions":[{"machine_id":"test_a","machine_id":"test_b"}]}'):
            with self.subTest(source=source), self.assertRaises(DuplicateError):
                DefinitionRegistry.from_json(source)

    def test_unknown_missing_or_malformed_definition_fields(self):
        for patch in ({'extra': 1}, {'references': {}}, {'references': [{'domain': 'fixture'}]}):
            value = {**PACKAGE['definitions'][0], **patch}
            with self.subTest(patch=patch), self.assertRaises(ValidationError):
                Definition.from_mapping(value)
        with self.assertRaises(ValidationError):
            Definition.from_mapping({'machine_id': 'test_entry'})
        with self.assertRaises(ValidationError):
            DefinitionRegistry.from_json('{bad')

    def test_package_metadata_versions_and_nonfinite_values_rejected(self):
        for version in (0, 2, True, '1'):
            with self.subTest(version=version), self.assertRaises(ValidationError):
                DefinitionRegistry(schema_version=version, content_version='test_v1')
        with self.assertRaises(ValidationError):
            DefinitionRegistry(schema_version=1, content_version='')
        for number in ('NaN', 'Infinity', '-Infinity'):
            with self.subTest(number=number), self.assertRaises(ValidationError):
                DefinitionRegistry.from_json('{"bad":' + number + '}')

    def test_registry_rejects_player_state_as_definition(self):
        catalog = DefinitionRegistry(schema_version=1, content_version='test_v1')
        with self.assertRaises(ValidationError):
            catalog.register({'instance_id': 'test', 'value': 3})

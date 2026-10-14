"""Immutable sharing must preserve external alias isolation and JSON validation."""
import unittest
from dataclasses import replace
from types import MappingProxyType
from src.core.state.envelope import freeze_json, thaw_json
from src.core.validation import ValidationError
from tests.fixtures.foundation import state


class StructuralSharingTests(unittest.TestCase):
    def test_revision_and_other_domain_changes_reuse_immutable_partitions(self):
        original = state()
        newer = replace(original, revision=original.revision + 1)
        self.assertIs(newer.domains, original.domains)
        self.assertIs(newer.time, original.time)
        changed = replace(original, domains={**original.domains, 'extra': {'rows': [1]}})
        self.assertIs(changed.domains['fixture'], original.domains['fixture'])
        with self.assertRaises(TypeError):
            changed.domains['fixture']['value'] = 10

    def test_external_mapping_proxy_and_nested_tuple_are_detached(self):
        child = {'value': [1]}
        frozen = freeze_json(MappingProxyType({'rows': (child,)}))
        child['value'].append(2)
        self.assertEqual(thaw_json(frozen), {'rows': [{'value': [1]}]})

    def test_freezing_trusted_subtrees_preserves_validation_of_other_children(self):
        trusted = freeze_json({'nested': [1]})
        for bad in (float('nan'), object(), {1: 'bad'}):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                freeze_json({'trusted': trusted, 'bad': bad})
        cycle = []; cycle.append(cycle)
        with self.assertRaises(ValidationError):
            freeze_json({'trusted': trusted, 'cycle': cycle})

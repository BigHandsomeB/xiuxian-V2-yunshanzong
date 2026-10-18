"""Explicit runtime profiles and deterministic package evidence; no save mutation."""
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
import hashlib
import json
from types import MappingProxyType

from src.core.validation import ValidationError
from src.data.dungeons.definitions import COLD_JADE_MANAGEMENT_VERSION
from src.data.economy.ecology import VERSION as ECOLOGY_VERSION
from src.data.item_effects import bindings_for
from src.data.combat.mechanics import CONTENT_VERSION as EFFECTS_VERSION

COMMON_DOMAINS = frozenset({'inventory', 'sect', 'production', 'disciples', 'automation',
    'equipment', 'cultivation', 'combat', 'dungeon', 'sect_management', 'offline_reports'})


@dataclass(frozen=True, slots=True)
class ContentProfile:
    version: str
    loader: str
    flags: tuple
    application: str
    domains: frozenset


PROFILES = (
    ContentProfile(COLD_JADE_MANAGEMENT_VERSION, 'dungeons',
                   (('management', True), ('cold_jade', True)), 'management', COMMON_DOMAINS),
    ContentProfile(ECOLOGY_VERSION, 'dungeons', (('management',True),('cold_jade',True),('ecology',True)), 'ecology', COMMON_DOMAINS | {'ecology'}),
    ContentProfile(EFFECTS_VERSION, 'current', (), 'ecology', COMMON_DOMAINS | {'ecology'}),
)


def validate_profiles(entries=None):
    entries = PROFILES if entries is None else entries
    result = {}
    expected = {COLD_JADE_MANAGEMENT_VERSION: ('dungeons', (('management', True), ('cold_jade', True)), 'management', COMMON_DOMAINS),
                ECOLOGY_VERSION: ('dungeons', (('management',True),('cold_jade',True),('ecology',True)), 'ecology', COMMON_DOMAINS | {'ecology'}),
                EFFECTS_VERSION: ('current', (), 'ecology', COMMON_DOMAINS | {'ecology'})}
    for row in entries:
        if not isinstance(row, ContentProfile) or type(row.version) is not str or row.version not in expected:
            raise ValidationError('unsupported runtime content profile')
        if row.version in result:
            raise ValidationError('duplicate runtime content profile')
        if (type(row.flags) is not tuple or type(row.domains) is not frozenset or
                any(type(pair) is not tuple or len(pair) != 2 or type(pair[1]) is not bool for pair in row.flags)):
            raise ValidationError('immutable typed runtime profile parameters required')
        if (row.loader, row.flags, row.application, row.domains) != expected[row.version]:
            raise ValidationError('runtime content profile adapter differs from declaration')
        result[row.version] = row
    if set(result) != set(expected):
        raise ValidationError('runtime content profile missing')
    return MappingProxyType(result)


def profile(version):
    if type(version) is not str or version not in validate_profiles():
        raise ValidationError('unsupported runtime content version')
    return validate_profiles()[version]


def transition(source, target):
    profile(source); profile(target)
    if source == target:
        return 'NOT_NEEDED'
    return 'REQUIRES_EXPLICIT_MIGRATION' if (source==COLD_JADE_MANAGEMENT_VERSION and target==ECOLOGY_VERSION) or (source==ECOLOGY_VERSION and target==EFFECTS_VERSION) else 'BLOCKED'


def canonical(value):
    """Typed dataclass fields plus canonical mappings, independent of insertion order."""
    def plain(item):
        if is_dataclass(item):
            return {'type': type(item).__module__ + '.' + type(item).__qualname__,
                    'fields': {field.name: plain(getattr(item, field.name)) for field in fields(item)}}
        if isinstance(item, Mapping):
            return {key: plain(value) for key, value in item.items()}
        if isinstance(item, (tuple, list)):
            return [plain(value) for value in item]
        return item
    return json.dumps(plain(value), sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def package_evidence(registry):
    if not registry.is_sealed:
        raise ValidationError('package evidence requires sealed registry')
    definitions = {key.domain + ':' + key.machine_id: digest(value)
                   for key, value in registry._definitions.items()}
    effects = {command + ':' + item: digest(binding)
               for (command, item), binding in bindings_for(registry).items()}
    evidence = {'data_schema_version': registry.schema_version,
                'content_version': registry.content_version,
                'definitions': definitions, 'effects': effects}
    return {**evidence, 'fingerprint': digest(evidence)}


def differences(source, target):
    result = {}
    for group in ('definitions', 'effects'):
        left, right = source[group], target[group]
        result[group] = {'added': sorted(right.keys() - left.keys()),
                         'removed': sorted(left.keys() - right.keys()),
                         'modified': sorted(key for key in left.keys() & right.keys() if left[key] != right[key])}
    return result

"""@module core/state/envelope
@purpose Minimal immutable State envelope; in-memory conversion only.
@depends core/validation, Python standard library
@usedBy application/memory, tests/core
@see ./INDEX.md
"""
from collections.abc import Mapping
from dataclasses import dataclass, replace
import math
from types import MappingProxyType
from uuid import uuid4

from src.core.time.config import DEFAULT_GAME_DAY_MS
from src.core.state import draft

from src.core.validation import (
    ValidationError, integer, machine_id, schema_version, text, uuid4_id,
)


_FROZEN_TOKEN = object()


class _FrozenObject(Mapping):
    """Owned, recursively frozen JSON; external mapping proxies are never trusted."""
    __slots__ = ('_parts','_json_cache')

    def __init__(self, parts, token):
        if token is not _FROZEN_TOKEN:
            raise TypeError('frozen JSON objects are constructed by freeze_json')
        object.__setattr__(self, '_parts', MappingProxyType(parts))
        object.__setattr__(self, '_json_cache', None)

    def __setattr__(self, name, value):
        raise TypeError('frozen JSON objects are immutable')

    def __getitem__(self, key):
        return self._parts[key]

    def __iter__(self):
        return iter(self._parts)

    def __len__(self):
        return len(self._parts)

    def items(self):
        return self._parts.items()

    def values(self):
        return self._parts.values()

    def __eq__(self, other):
        if type(other) is _FrozenObject:
            return self._parts == other._parts
        if isinstance(other, Mapping):
            return dict(self._parts) == dict(other)
        return NotImplemented


def freeze_json(value):
    """Detach caller containers; reject cycles/non-JSON/invalid numbers."""
    def freeze(item, active):
        if type(item) is _FrozenObject or (type(item) is draft.DraftObject and draft.enabled()):
            return item
        if item is None or type(item) in (str, bool, int):
            return item
        if type(item) is float and math.isfinite(item):
            return item
        if isinstance(item, Mapping) or type(item) in (list, tuple, draft.BranchList):
            if id(item) in active:
                raise ValidationError('cyclic containers are not JSON values')
            active.add(id(item))
            try:
                if isinstance(item, Mapping):
                    if any(type(key) is not str for key in item):
                        raise ValidationError('JSON object keys must be strings')
                    parts=dict.items(item) if type(item) is draft.Branch else item.items()
                    values={key: freeze(part, active) for key, part in parts}
                    return draft.DraftObject(values) if draft.enabled() else _FrozenObject(values, _FROZEN_TOKEN)
                return tuple(freeze(part, active) for part in item)
            finally:
                active.remove(id(item))
        raise ValidationError('state/payload must contain only finite JSON values')
    return freeze(value, set())


def thaw_json(value):
    """Explicit detached conversion, never used for a read-only query."""
    if draft.enabled():
        branch=draft.writable(value)
        if branch is not None:return branch
    if type(value) is _FrozenObject or isinstance(value, Mapping):
        return {key: thaw_json(item) for key, item in value.items()}
    if type(value) in (tuple,list,draft.BranchList):
        return [thaw_json(item) for item in value]
    return value


def _object(value, fields, name):
    if not isinstance(value, Mapping) or set(value) != set(fields):
        raise ValidationError(f'{name} requires exactly {fields}')


@dataclass(frozen=True, slots=True, weakref_slot=True)
class StateEnvelope:
    save_schema_version: int
    data_schema_version: int
    content_version: str
    save_id: str
    generation: int
    revision: int
    time: Mapping
    identity: Mapping
    domains: Mapping

    def __post_init__(self):
        schema_version(self.save_schema_version, 'save_schema_version')
        schema_version(self.data_schema_version, 'data_schema_version')
        text(self.content_version, 'content_version')
        uuid4_id(self.save_id, 'save_id')
        integer(self.generation, 'generation', 1)
        integer(self.revision, 'revision')
        base_time={'last_settled_at_ms','sim_time_ms','pending','day_length_ms'}
        if not isinstance(self.time,Mapping) or not base_time<=set(self.time) or set(self.time)-base_time-{'world_paused'}:
            raise ValidationError('unsupported time fields')
        if 'world_paused' in self.time and type(self.time['world_paused']) is not bool:
            raise ValidationError('world_paused must be boolean')
        if self.time.get('world_paused',False) and self.time['pending'] is not None:
            raise ValidationError('pause requires completed settlement')
        integer(self.time['last_settled_at_ms'], 'last_settled_at_ms')
        integer(self.time['sim_time_ms'], 'sim_time_ms')
        integer(self.time['day_length_ms'], 'day_length_ms', 1)
        if self.time['pending'] is not None and not isinstance(self.time['pending'], Mapping):
            raise ValidationError('pending must be an object or null')
        _object(self.identity, ('instance_counter', 'event_counter', 'rng_streams'), 'identity')
        integer(self.identity['instance_counter'], 'instance_counter')
        integer(self.identity['event_counter'], 'event_counter')
        if not isinstance(self.identity['rng_streams'], Mapping) or self.identity['rng_streams']:
            raise ValidationError('Phase 4 has no RNG implementation; rng_streams must be empty')
        if not isinstance(self.domains, Mapping):
            raise ValidationError('domains must be an object')
        for domain, partition in self.domains.items():
            machine_id(domain, 'domain')
            if not isinstance(partition, Mapping):
                raise ValidationError('each domain partition must be an object')
        for field in ('time', 'identity', 'domains'):
            object.__setattr__(self, field, freeze_json(getattr(self, field)))

    @classmethod
    def create(cls, *, content_version, domains, last_settled_at_ms,
               data_schema_version=1):
        return cls(1, data_schema_version, content_version, str(uuid4()), 1, 0,
                   {'last_settled_at_ms': last_settled_at_ms, 'sim_time_ms': 0,
                    'pending': None, 'day_length_ms': DEFAULT_GAME_DAY_MS},
                   {'instance_counter': 0, 'event_counter': 0, 'rng_streams': {}},
                   domains)

    @classmethod
    def from_dict(cls, value):
        _object(value, cls.__dataclass_fields__, 'state envelope')
        return cls(**value)

    def to_dict(self):
        return {field: thaw_json(getattr(self, field)) for field in self.__dataclass_fields__}

    def with_domain(self, domain, candidate):
        if domain not in self.domains:
            raise ValidationError(f'cannot add an unowned domain: {domain}')
        return replace(self, domains={**self.domains, domain: candidate},
                       revision=self.revision + 1)

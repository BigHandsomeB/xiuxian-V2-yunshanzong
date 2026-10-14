"""@module data/registry
@purpose Immutable definitions and a validated, sealed content registry.
@depends core/validation, Python standard library
@usedBy application/memory, tests/data
@see ./INDEX.md
"""
from collections.abc import Mapping
from dataclasses import dataclass
import json
from types import MappingProxyType

from src.core.validation import (
    ConflictError, DuplicateError, NotFoundError, ValidationError,
    machine_id, schema_version as validate_schema_version, text,
)


def _fields(value, required, optional=()):
    if not isinstance(value, Mapping):
        raise ValidationError('definition input must be an object')
    if not set(required) <= value.keys() or value.keys() - set(required) - set(optional):
        raise ValidationError(f'expected fields {required}; optional {optional}')


@dataclass(frozen=True, slots=True)
class DefinitionKey:
    domain: str
    machine_id: str

    def __post_init__(self):
        machine_id(self.domain, 'domain')
        machine_id(self.machine_id)

    @classmethod
    def from_mapping(cls, value):
        _fields(value, ('domain', 'machine_id'))
        return cls(**value)


@dataclass(frozen=True, slots=True)
class Definition:
    domain: str
    machine_id: str
    display_name: str
    references: tuple[DefinitionKey, ...] = ()

    def __post_init__(self):
        DefinitionKey(self.domain, self.machine_id)
        text(self.display_name, 'display_name')
        if type(self.references) is not tuple or any(
            not isinstance(ref, DefinitionKey) for ref in self.references
        ):
            raise ValidationError('references must be an immutable tuple of DefinitionKey')

    @property
    def key(self):
        return DefinitionKey(self.domain, self.machine_id)

    @classmethod
    def from_mapping(cls, value):
        _fields(value, ('domain', 'machine_id', 'display_name'), ('references',))
        refs = value.get('references', [])
        if type(refs) is not list:
            raise ValidationError('references must be a JSON array')
        return cls(value['domain'], value['machine_id'], value['display_name'],
                   tuple(DefinitionKey.from_mapping(ref) for ref in refs))


class DefinitionRegistry:
    """Build once, seal after reference validation, then consume read-only."""
    __slots__ = ('_schema_version', '_content_version', '_definitions', '_sealed')

    def __init__(self, *, schema_version: int, content_version: str):
        # Package metadata, not one version per individual definition.
        validate_schema_version(schema_version, 'data_schema_version')
        text(content_version, 'content_version')
        self._schema_version = schema_version
        self._content_version = content_version
        self._definitions = {}
        self._sealed = False

    @property
    def schema_version(self):
        return self._schema_version

    @property
    def content_version(self):
        return self._content_version

    @property
    def is_sealed(self):
        return self._sealed

    def register(self, definition: Definition) -> None:
        if self._sealed:
            raise ConflictError('registry is sealed')
        if not isinstance(definition, Definition):
            raise ValidationError('register requires a Definition, not player state/instance')
        if definition.key in self._definitions:
            raise DuplicateError(f'duplicate definition: {definition.key}')
        self._definitions[definition.key] = definition

    def seal(self) -> None:
        for definition in self._definitions.values():
            for ref in definition.references:
                if ref not in self._definitions:
                    raise ValidationError(f'{definition.key} references missing definition {ref}')
        self._definitions = MappingProxyType(dict(self._definitions))
        self._sealed = True

    def contains(self, key: DefinitionKey) -> bool:
        self._check_read(key)
        return key in self._definitions

    def lookup(self, key: DefinitionKey) -> Definition:
        self._check_read(key)
        try:
            return self._definitions[key]
        except KeyError as exc:
            raise NotFoundError(f'unknown definition: {key}') from exc

    def _check_read(self, key):
        if not self._sealed:
            raise ConflictError('seal registry before reading definitions')
        if not isinstance(key, DefinitionKey):
            raise ValidationError('lookup requires a DefinitionKey')

    @classmethod
    def from_json(cls, source: str):
        def unique_object(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise DuplicateError(f'duplicate JSON key: {key}')
                result[key] = value
            return result

        def invalid_constant(value):
            raise ValidationError(f'non-finite JSON number: {value}')

        try:
            package = json.loads(source, object_pairs_hook=unique_object,
                                 parse_constant=invalid_constant)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValidationError('invalid definition JSON') from exc
        _fields(package, ('schema_version', 'content_version', 'definitions'))
        if type(package['definitions']) is not list:
            raise ValidationError('definitions must be a JSON array')
        registry = cls(schema_version=package['schema_version'],
                       content_version=package['content_version'])
        for value in package['definitions']:
            registry.register(Definition.from_mapping(value))
        registry.seal()
        return registry

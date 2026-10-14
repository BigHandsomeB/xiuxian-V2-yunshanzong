"""@module application/memory
@purpose Single-threaded, in-memory Contract verification; NOT a Save store.
@depends core/state/envelope, core/validation, data/registry, application/settlement
@usedBy tests/core/test_application, tests/core/test_settlement
@see ./INDEX.md
"""
from src.core.time.world import require_running
from collections.abc import Callable, Mapping
from dataclasses import dataclass
import hashlib
import json
from types import MappingProxyType

from src.core.state.envelope import StateEnvelope, freeze_json, thaw_json
from src.core.validation import (
    ConflictError, NotFoundError, ValidationError, integer, machine_id, uuid4_id,
)
from src.data.registry import DefinitionRegistry
from src.application.settlement import SettlementRequest, SettlementReceipt


@dataclass(frozen=True, slots=True)
class Command:
    save_id: str
    generation: int
    expected_revision: int
    request_id: str
    name: str
    payload: Mapping
    version: int = 1

    def __post_init__(self):
        uuid4_id(self.save_id, 'save_id')
        uuid4_id(self.request_id, 'request_id')
        integer(self.generation, 'generation', 1)
        integer(self.expected_revision, 'expected_revision')
        machine_id(self.name, 'command name')
        integer(self.version, 'command version', 1)
        if not isinstance(self.payload, Mapping):
            raise ValidationError('command payload must be an object')
        object.__setattr__(self, 'payload', freeze_json(self.payload))

    def digest(self):
        intent = {'operation': 'command', 'name': self.name, 'version': self.version,
                  'payload': thaw_json(self.payload)}
        canonical = json.dumps(intent, sort_keys=True, separators=(',', ':'), allow_nan=False)
        return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class CommandSpec:
    domain: str
    transition: Callable
    version: int = 1

    def __post_init__(self):
        machine_id(self.domain, 'command domain')
        integer(self.version, 'command version', 1)
        if not callable(self.transition):
            raise ValidationError('transition must be callable')


@dataclass(frozen=True, slots=True)
class Receipt:
    request_id: str
    committed_revision: int
    result: object

    def __post_init__(self):
        object.__setattr__(self, 'result', freeze_json(self.result))


class MemoryApplication:
    """One committed cell, immutable snapshots, candidate commit with receipt.

    No persistence, thread or HTTP. Optional explicit settlement uses injected
    engine/clock; query never invokes them. Handlers are trusted
    application configuration; test-only behavior lives exclusively in tests/.
    """
    def __init__(self, state: StateEnvelope, registry: DefinitionRegistry,
                 commands: Mapping[str, CommandSpec], *, settlement_engine=None, clock=None):
        if not isinstance(state, StateEnvelope) or not isinstance(registry, DefinitionRegistry):
            raise ValidationError('application requires StateEnvelope and DefinitionRegistry')
        if not registry.is_sealed:
            raise ValidationError('registry must be sealed before using state')
        if (state.data_schema_version, state.content_version) != (
            registry.schema_version, registry.content_version
        ):
            raise ConflictError('state and definition package versions differ')
        specs = dict(commands)
        for name, spec in specs.items():
            machine_id(name, 'command name')
            if not isinstance(spec, CommandSpec) or spec.domain not in state.domains:
                raise ValidationError('command requires an owned domain and CommandSpec')
        if (settlement_engine is None) != (clock is None):
            raise ValidationError('settlement_engine and clock must be supplied together')
        if settlement_engine is not None and (
            not callable(getattr(settlement_engine, 'advance', None)) or
            not callable(getattr(clock, 'now_ms', None))
        ):
            raise ValidationError('settlement engine/clock interfaces are invalid')
        self._settlement_engine = settlement_engine
        self._clock = clock
        self._commands = MappingProxyType(specs)
        # Reconstruct once to sever all initial external container ownership.
        self._committed = (StateEnvelope.from_dict(state.to_dict()), {})

    def query(self) -> StateEnvelope:
        """Borrow a deeply immutable Snapshot, with no work or writes."""
        return self._committed[0]

    def receipts(self) -> tuple[Receipt | SettlementReceipt, ...]:
        return tuple(entry[1] for entry in self._committed[1].values())

    def execute(self, command: Command) -> Receipt:
        if not isinstance(command, Command):
            raise ValidationError('execute requires Command')
        state, records = self._committed
        if command.save_id != state.save_id or command.generation != state.generation:
            raise ConflictError('save_id/generation mismatch')
        key = (command.save_id, command.generation, command.request_id)
        digest = command.digest()
        if key in records:
            previous_digest, receipt = records[key]
            if previous_digest != digest:
                raise ConflictError('request_id reused with a different intent')
            return receipt
        require_running(state.time)
        if command.expected_revision != state.revision:
            raise ConflictError('stale expected_revision')
        if state.time['pending'] is not None:
            raise ConflictError('settlement pending; ordinary commands are blocked')
        if command.name not in self._commands:
            raise NotFoundError(f'unknown command: {command.name}')
        spec = self._commands[command.name]
        if command.version != spec.version:
            raise ValidationError('unsupported command version')
        candidate = thaw_json(state.domains[spec.domain])
        result = spec.transition(candidate, command.payload)
        # Validation/freeze of both candidate and result precedes all commits.
        frozen_candidate = freeze_json(candidate)
        def canonical(value):
            return json.dumps(thaw_json(value), sort_keys=True,
                              separators=(',', ':'), allow_nan=False)
        changed = canonical(frozen_candidate) != canonical(state.domains[spec.domain])
        next_state = state.with_domain(spec.domain, candidate) if changed else state
        receipt = Receipt(command.request_id, next_state.revision, result)
        next_records = {**records, key: (digest, receipt)}
        self._committed = (next_state, next_records)
        return receipt

    def settle(self, request: SettlementRequest) -> SettlementReceipt:
        """Explicit operation: clock capture only on a NEW window, never query."""
        if not isinstance(request, SettlementRequest):
            raise ValidationError('settle requires SettlementRequest')
        state, records = self._committed
        if request.save_id != state.save_id or request.generation != state.generation:
            raise ConflictError('save_id/generation mismatch')
        key = (request.save_id, request.generation, request.request_id)
        digest = request.digest()
        if key in records:
            previous_digest, receipt = records[key]
            if previous_digest != digest:
                raise ConflictError('request_id reused with a different intent')
            return receipt
        if request.expected_revision != state.revision:
            raise ConflictError('stale expected_revision')
        if self._settlement_engine is None:
            raise ValidationError('settlement engine/clock not configured')
        options = dict(max_events=request.max_events, continuation=request.continuation)
        if request.continuation is None:
            if state.time['pending'] is not None:
                raise ConflictError('pending settlement requires resume')
            options['now_ms'] = self._clock.now_ms()
        candidate, result = self._settlement_engine.advance(state, **options)
        receipt = SettlementReceipt(request.request_id, candidate.revision, result)
        self._committed = (candidate, {**records, key: (digest, receipt)})
        return receipt

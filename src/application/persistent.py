"""@module application/persistent
@purpose SQLite authority coordination: load/validate/candidate/atomic commit/replay.
@depends application/memory, application/settlement, core/save, core/time, data/registry
@usedBy tests/core/test_persistence; no HTTP or formal gameplay
@see ./INDEX.md
"""
from src.core.time.world import require_running
from types import MappingProxyType
from dataclasses import asdict, replace

from src.application.memory import Command, CommandSpec, MemoryApplication, Receipt
from src.application.settlement import SettlementRequest, SettlementReceipt
from src.core.save.codec import CorruptSaveError, StoredReceipt
from src.core.save.sqlite import LoadResult
from src.core.state.envelope import thaw_json
from src.core.time.config import PERSISTED_OFFLINE_CAP_MS, OFFLINE_CAP_MS
from src.core.time.model import Continuation, SettlementResult
from src.core.validation import (ConflictError, NotFoundError, ValidationError, integer, machine_id, text)
from src.data.registry import DefinitionKey, DefinitionRegistry


class PersistentApplication:
    """SQLite is authority, no synchronized mutable in-memory authority/cache.

    Configured validators/reference extractors are pure Schema interfaces.
    Only MemoryApplication builds candidates; SQLite owns disk/transaction details.
    """
    def __init__(self, store, registry: DefinitionRegistry, commands, *, references,
                 validators=None, settlement_engine=None, clock=None):
        if not isinstance(registry, DefinitionRegistry) or not registry.is_sealed:
            raise ValidationError('sealed registry required')
        if not callable(references):
            raise ValidationError('explicit Schema reference extractor required')
        if (settlement_engine is None) != (clock is None):
            raise ValidationError('engine and clock must be configured together')
        self.store, self.registry = store, registry
        specs = dict(commands)
        for name, spec in specs.items():
            machine_id(name, 'command name')
            if not isinstance(spec, CommandSpec):
                raise ValidationError('commands require CommandSpec')
        self._commands = MappingProxyType(specs)
        self._references = references
        self._validators = MappingProxyType(dict(validators or {}))
        if any(not callable(handler) for handler in self._validators.values()):
            raise ValidationError('Domain validators must be callable')
        if settlement_engine is not None and (
            not callable(getattr(settlement_engine, 'validate_state', None)) or
            not callable(getattr(settlement_engine, 'advance', None)) or
            not callable(getattr(clock, 'now_ms', None))
        ):
            raise ValidationError('invalid settlement validator/engine/clock interfaces')
        self.engine, self.clock = settlement_engine, clock

    def _validate(self, state):
        if (state.data_schema_version, state.content_version) != (
            self.registry.schema_version, self.registry.content_version
        ):
            raise ValidationError('save and definition package versions differ')
        for key in self._references(state):
            if not isinstance(key, DefinitionKey):
                raise ValidationError('reference extractor must return DefinitionKey')
            self.registry.lookup(key)
        for domain, validator in self._validators.items():
            if domain not in state.domains:
                raise ValidationError('required Domain partition missing')
            validator(state.domains[domain])
        if self.engine is not None:
            self.engine.validate_state(state)
        elif state.time['pending'] is not None:
            raise ValidationError('pending save requires configured settlement validator')
        if any(spec.domain not in state.domains for spec in self._commands.values()):
            raise ValidationError('configured command Domain missing from State')
        return state

    def validate_state(self, state):
        """Pure Schema/Definition/queue validation for lifecycle coordination."""
        return self._validate(state)

    def inspect(self, save_id, *, include_recovery=True):
        result = self.store.inspect(save_id, include_recovery=include_recovery)
        recovery = result.recovery
        if recovery is not None:
            try:
                self._validate(recovery)
            except (ValidationError, ConflictError, NotFoundError):
                recovery = None
        if result.status == 'NO_SAVE':
            return result
        error = result.error
        if result.current is not None:
            try:
                self._validate(result.current)
                return replace(result, recovery=recovery)
            except (ValidationError, ConflictError, NotFoundError) as exc:
                error = str(exc)
        return LoadResult('CURRENT_INVALID_RECOVERY_AVAILABLE' if recovery is not None else
                          'CURRENT_INVALID_NO_RECOVERY', recovery=recovery, error=error)

    def query(self, save_id):
        result = self.inspect(save_id, include_recovery=False)
        if result.status == 'NO_SAVE':
            raise NotFoundError('no saved State')
        if result.status != 'CURRENT_VALID':
            raise CorruptSaveError(result.error or 'invalid current State')
        return result.current

    def create(self, state):
        self._validate(state)
        with self.store.transaction():
            self.store.create(state)

    def checkpoint(self, save_id):
        """Explicit bounded recovery checkpoint, not a Query or simulation tick."""
        with self.store.transaction():
            self.query(save_id)
            self.store.checkpoint(save_id)

    def _decode_receipt(self, record):
        payload = thaw_json(record.payload)
        if record.kind == 'command':
            return Receipt(record.request_id, record.committed_revision, payload)
        try:
            if type(payload) is not dict or not set(SettlementResult.__dataclass_fields__)-{'offline_report'}<=set(payload) or set(payload)-set(SettlementResult.__dataclass_fields__)-{'xp_gained','levels_gained'}:
                raise ValidationError('invalid settlement receipt fields')
            continuation = payload['continuation']
            if continuation is not None:
                continuation = Continuation(**continuation)
                if (continuation.save_id, continuation.generation, continuation.revision,
                    continuation.target_sim_ms) != (
                    record.save_id, record.generation, record.committed_revision, payload['target_sim_ms']
                ):
                    raise ValidationError('receipt continuation identity mismatch')
            for name in ('from_sim_ms', 'to_sim_ms', 'target_sim_ms', 'accepted_ms', 'discarded_ms'):
                integer(payload[name], 'receipt ' + name)
            events = payload['processed_events']
            if (type(events) is not list or len(set(events)) != len(events) or
                any(type(event) is not str for event in events)):
                raise ValidationError('invalid processed event list')
            for event in events:
                text(event, 'processed event')
            if (payload['status'] not in ('COMPLETE', 'PENDING') or
                (payload['status'] == 'PENDING') != (continuation is not None) or
                not payload['from_sim_ms'] <= payload['to_sim_ms'] <= payload['target_sim_ms'] or
                (payload['status'] == 'COMPLETE' and payload['to_sim_ms'] != payload['target_sim_ms']) or
                payload['accepted_ms'] > PERSISTED_OFFLINE_CAP_MS or type(payload['clock_rollback']) is not bool):
                raise ValidationError('invalid settlement result')
            payload.update(continuation=continuation, processed_events=tuple(events))
            from src.application.settlement import GrowthSettlementResult
            for key in ('xp_gained','levels_gained'):integer(payload.get(key,0),'receipt '+key)
            result_type=GrowthSettlementResult if 'xp_gained' in payload or 'levels_gained' in payload else SettlementResult
            return SettlementReceipt(record.request_id, record.committed_revision, result_type(**payload))
        except (TypeError, ValueError, KeyError) as exc:
            raise CorruptSaveError('invalid persisted settlement receipt') from exc

    def _mutate(self, request, method):
        if not isinstance(request, Command if method == 'execute' else SettlementRequest):
            raise ValidationError('invalid application request type')
        with self.store.transaction():
            state = self.query(request.save_id)
            if request.generation != state.generation:
                raise ConflictError('save generation mismatch')
            previous = self.store.receipt(state.save_id, state.generation, request.request_id)
            if previous is not None:
                if previous.intent != request.digest() or previous.kind != ('command' if method == 'execute' else 'settlement'):
                    raise ConflictError('request_id reused with different intent')
                if previous.committed_revision > state.revision:
                    raise CorruptSaveError('receipt revision is ahead of State')
                return self._decode_receipt(previous)  # Replay precedes expected_revision.
            require_running(state.time)
            memory = MemoryApplication(state, self.registry, self._commands,
                                       settlement_engine=self.engine, clock=self.clock)
            receipt = getattr(memory, method)(request)
            candidate = self._validate(memory.query())
            payload = thaw_json(receipt.result) if method == 'execute' else asdict(receipt.result)
            record = StoredReceipt(candidate.save_id, candidate.generation, request.request_id,
                                   request.digest(), receipt.committed_revision,
                                   'command' if method == 'execute' else 'settlement', payload)
            self.store.commit(state, candidate, record)
        return receipt  # Success exposed only AFTER COMMIT.

    def execute(self, command):
        return self._mutate(command, 'execute')

    def settle(self, request):
        return self._mutate(request, 'settle')

"""@module application/recovery
@purpose Explicit lifecycle recovery; not a gameplay handler or automatic fallback.
@depends application/persistent interface, core/save, core/state, core/validation
@usedBy tests/core/test_recovery
@see ./INDEX.md
"""
from dataclasses import asdict, replace

from src.core.save.codec import CorruptSaveError, StoredReceipt, decode_state, wall_claim
from src.core.save.recovery import (RecoveryObservation, RecoveryRequest, RecoveryResult,
                                    row_fingerprint)
from src.core.state.envelope import thaw_json
from src.core.validation import ConflictError, NotFoundError, ValidationError, integer, uuid4_id


class RecoveryApplication:
    """Trusted administrative caller provides explicit observation and intent.

    No auth/HTTP, external import or second Authority. Pure configured Schema
    validators recheck Source and candidate; all writes use one SQLite transaction.
    """
    def __init__(self, application, clock):
        if not callable(getattr(clock, 'now_ms', None)):
            raise ValidationError('recovery requires injected trusted Clock')
        self.application, self.store, self.clock = application, application.store, clock

    def _source(self, save_id, row):
        state = decode_state(row)
        if state.save_id != save_id:
            raise ValidationError('recovery source belongs to another Save')
        return self.application.validate_state(state)

    def inspect(self, save_id):
        uuid4_id(save_id, 'recovery save_id')
        self.store.check_layout()
        current, previous = self.store.recovery_rows(save_id)
        if current is None:
            return RecoveryObservation('NO_RECOVERY_AVAILABLE', save_id, reason='NO_SAVE')
        if previous is None:
            return RecoveryObservation('NO_RECOVERY_AVAILABLE', save_id, reason='NO_PREVIOUS')
        try:
            source = self._source(save_id, previous)
        except (ValidationError, ConflictError, NotFoundError) as exc:
            return RecoveryObservation('RECOVERY_CANDIDATE_INVALID', save_id, reason=type(exc).__name__)
        try:
            integer(current[1], 'current generation', 1)
            wall_claim(current)
            if source.generation > current[1]:
                raise ConflictError('source lineage newer than current header')
        except (ValidationError, ConflictError):
            return RecoveryObservation('CONFLICT', save_id, reason='UNSAFE_LINEAGE_METADATA')
        return RecoveryObservation('READY', save_id, current[1], row_fingerprint(current),
                                   row_fingerprint(previous), source.generation, source.revision)

    def recover(self, request):
        if not isinstance(request, RecoveryRequest):
            raise ValidationError('explicit RecoveryRequest required')
        with self.store.transaction():
            self.store.check_layout()
            current, previous = self.store.recovery_rows(request.save_id)
            if current is None:
                return RecoveryResult('NO_RECOVERY_AVAILABLE', request.save_id, reason='NO_SAVE')
            try:
                integer(current[1], 'current generation', 1)
                durable_claim = wall_claim(current)
            except ValidationError:
                return RecoveryResult('CONFLICT', request.save_id, reason='UNSAFE_LINEAGE_METADATA')
            # Successful retry may arrive after Source was consumed and generation changed.
            replay = self.store.receipt(request.save_id, current[1], request.request_id)
            if replay is not None:
                if replay.kind != 'recovery' or replay.intent != request.digest():
                    return RecoveryResult('CONFLICT', request.save_id, reason='REQUEST_ID_INTENT_CONFLICT')
                try:
                    result = RecoveryResult(**thaw_json(replay.payload))
                    if (result.status, result.save_id, result.old_generation, result.new_generation,
                        result.current_fingerprint, result.source_fingerprint, replay.committed_revision) != (
                        'SUCCESS', request.save_id, request.expected_generation, current[1],
                        request.current_fingerprint, request.source_fingerprint, 0
                    ):
                        raise CorruptSaveError('invalid recovery receipt identity')
                    return result
                except (TypeError, ValidationError) as exc:
                    raise CorruptSaveError('invalid persisted recovery receipt') from exc
            if current[1] != request.expected_generation or row_fingerprint(current) != request.current_fingerprint:
                return RecoveryResult('CONFLICT', request.save_id, reason='CURRENT_CHANGED')
            if previous is None:
                return RecoveryResult('NO_RECOVERY_AVAILABLE', request.save_id, reason='SOURCE_CONSUMED_OR_MISSING')
            # Validate again under the lock before deciding stale observation vs invalid Source.
            try:
                source = self._source(request.save_id, previous)
            except (ValidationError, ConflictError, NotFoundError) as exc:
                return RecoveryResult('RECOVERY_CANDIDATE_INVALID', request.save_id, reason=type(exc).__name__)
            if row_fingerprint(previous) != request.source_fingerprint:
                return RecoveryResult('CONFLICT', request.save_id, reason='SOURCE_CHANGED')
            if source.generation > current[1]:
                return RecoveryResult('CONFLICT', request.save_id, reason='UNSAFE_SOURCE_LINEAGE')
            try:
                generation = self.store.highest_generation(request.save_id) + 1
            except (ValidationError, ConflictError):
                return RecoveryResult('CONFLICT', request.save_id, reason='UNSAFE_LINEAGE_METADATA')
            now = self.clock.now_ms()
            integer(now, 'recovery wall now')
            # Retain known future watermarks if Clock rolled back; never rewind claims.
            anchor = max(now, source.time['last_settled_at_ms'], durable_claim)
            current_reason = 'CURRENT_INVALID'
            try:
                current_state = decode_state(current)
                anchor = max(anchor, current_state.time['last_settled_at_ms'])
                self.application.validate_state(current_state)
                current_reason = 'EXPLICIT_PROGRESS_ROLLBACK'
            except (ValidationError, ConflictError, NotFoundError):
                pass
            candidate = replace(source, generation=generation, revision=0,
                                time={**source.time, 'pending': None, 'last_settled_at_ms': anchor})
            try:
                self.application.validate_state(candidate)
            except (ValidationError, ConflictError, NotFoundError) as exc:
                return RecoveryResult('RECOVERY_CANDIDATE_INVALID', request.save_id, reason=type(exc).__name__)
            result = RecoveryResult('SUCCESS', request.save_id, current[1], generation,
                                    source.generation, source.revision, 0, anchor,
                                    request.current_fingerprint, request.source_fingerprint,
                                    (current_reason + ': ' + request.reason)[:512])
            receipt = StoredReceipt(candidate.save_id, generation, request.request_id,
                                    request.digest(), 0, 'recovery', asdict(result))
            self.store.replace_from_recovery(request, candidate, receipt)
        return result

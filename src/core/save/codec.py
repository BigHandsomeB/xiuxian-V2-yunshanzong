"""@module core/save/codec
@purpose Strict canonical State snapshots and continuation integrity; no gameplay.
@depends core/state, core/time/model, core/validation, standard library
@usedBy core/save/sqlite, application/persistent
@see ./INDEX.md
"""
from dataclasses import asdict, dataclass
import hashlib
import json

from src.core.state.envelope import StateEnvelope, freeze_json, thaw_json
from src.core.state.serialization import canonical_json,snapshot
from src.core.time.model import Continuation
from src.core.validation import ValidationError, integer, uuid4_id


class CorruptSaveError(ValidationError):
    pass


class PersistenceError(Exception):
    pass


def canonical(value):
    return canonical_json(value)


def parse(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise CorruptSaveError('duplicate JSON key')
            result[key] = value
        return result
    def constant(value):
        raise CorruptSaveError('non-finite JSON value')
    try:
        return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, TypeError, RecursionError) as exc:
        raise CorruptSaveError('invalid save JSON') from exc


def sha(text):
    if type(text) is not str:
        raise CorruptSaveError('serialized save must be text')
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def wall_claim(row):
    """Independently verifiable claim witness remains usable if State JSON is bad."""
    try:
        saved_id, watermark, digest = row[0], row[9], row[10]
        uuid4_id(saved_id, 'claim save_id')
        integer(watermark, 'durable wall claim')
        if sha(canonical([saved_id, watermark])) != digest:
            raise CorruptSaveError('wall claim witness checksum mismatch')
        return watermark
    except (IndexError, TypeError, ValidationError) as exc:
        raise CorruptSaveError('invalid durable wall claim witness') from exc


def encode_state(state):
    if not isinstance(state, StateEnvelope):
        raise ValidationError('save requires StateEnvelope')
    body,digest = snapshot(state)
    continuation = None if state.time['pending'] is None else canonical(asdict(Continuation.for_state(state)))
    return (state.save_id, state.generation, state.revision, state.save_schema_version,
            state.data_schema_version, state.content_version, body, digest, continuation,
            state.time['last_settled_at_ms'], sha(canonical([state.save_id, state.time['last_settled_at_ms']])))


def decode_state(row):
    try:
        identity, generation, revision, schema, data_schema, content, body, digest, continuation, _, _ = row
        if sha(body) != digest:
            raise CorruptSaveError('snapshot checksum mismatch')
        state = StateEnvelope.from_dict(parse(body))
        if wall_claim(row) != state.time['last_settled_at_ms']:
            raise CorruptSaveError('wall claim witness and State disagree')
        if (identity, generation, revision, schema, data_schema, content) != (
            state.save_id, state.generation, state.revision, state.save_schema_version,
            state.data_schema_version, state.content_version
        ):
            raise CorruptSaveError('snapshot metadata disagrees with envelope')
        if state.time['pending'] is None:
            if continuation is not None:
                raise CorruptSaveError('unexpected continuation without pending state')
        else:
            saved = Continuation(**parse(continuation))
            if saved != Continuation.for_state(state):
                raise CorruptSaveError('continuation does not match saved state')
        return state
    except (ValidationError, TypeError, ValueError, KeyError, RecursionError) as exc:
        raise CorruptSaveError('invalid state/metadata/continuation: ' + str(exc)) from exc


@dataclass(frozen=True, slots=True)
class StoredReceipt:
    save_id: str
    generation: int
    request_id: str
    intent: str
    committed_revision: int
    kind: str
    payload: object

    def __post_init__(self):
        uuid4_id(self.save_id, 'receipt save_id')
        uuid4_id(self.request_id, 'receipt request_id')
        integer(self.generation, 'receipt generation', 1)
        integer(self.committed_revision, 'receipt revision')
        if type(self.intent) is not str or len(self.intent) != 64 or any(c not in '0123456789abcdef' for c in self.intent):
            raise ValidationError('receipt intent must be SHA256 hex')
        if self.kind not in ('command', 'settlement', 'recovery'):
            raise ValidationError('unsupported receipt kind')
        object.__setattr__(self, 'payload', freeze_json(self.payload))

    def row(self):
        body = canonical({'kind': self.kind, 'payload': thaw_json(self.payload)})
        return (self.save_id, self.generation, self.request_id, self.intent,
                self.committed_revision, body, sha(canonical([self.save_id, self.generation,
                    self.request_id, self.intent, self.committed_revision, body])))

    @classmethod
    def from_row(cls, row):
        try:
            save, generation, request, intent, revision, body, digest = row
            if sha(canonical([save, generation, request, intent, revision, body])) != digest:
                raise CorruptSaveError('receipt checksum mismatch')
            value = parse(body)
            if type(value) is not dict or set(value) != {'kind', 'payload'}:
                raise CorruptSaveError('invalid receipt representation')
            return cls(save, generation, request, intent, revision, **value)
        except (ValidationError, TypeError, ValueError) as exc:
            raise CorruptSaveError('invalid receipt: ' + str(exc)) from exc

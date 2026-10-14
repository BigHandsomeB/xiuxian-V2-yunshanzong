"""@module core/save/recovery
@purpose Administrative recovery identity, observation and compact result contracts.
@depends core/save/codec, core/validation, standard library
@usedBy application/recovery, core/save/sqlite, tests/core/test_recovery
@see ./INDEX.md
"""
from dataclasses import asdict, dataclass
import hashlib

from src.core.save.codec import canonical
from src.core.validation import ValidationError, integer, text, uuid4_id


def row_fingerprint(row):
    """Opaque CAS for raw SQLite rows, even when State JSON is unreadable."""
    if row is None:
        return None
    digest = hashlib.sha256()
    for cell in row:
        value = (type(cell).__name__ + ':' + repr(cell)).encode('utf-8', errors='backslashreplace')
        digest.update(len(value).to_bytes(8, 'big'))
        digest.update(value)
    return digest.hexdigest()


def fingerprint(value, name):
    if type(value) is not str or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise ValidationError(name + ' must be SHA256 hex')


@dataclass(frozen=True, slots=True)
class RecoveryObservation:
    status: str
    save_id: str
    current_generation: int | None = None
    current_fingerprint: str | None = None
    source_fingerprint: str | None = None
    source_generation: int | None = None
    source_revision: int | None = None
    reason: str = ''


@dataclass(frozen=True, slots=True)
class RecoveryRequest:
    save_id: str
    expected_generation: int
    current_fingerprint: str
    source_fingerprint: str
    request_id: str
    reason: str

    def __post_init__(self):
        uuid4_id(self.save_id, 'recovery save_id')
        uuid4_id(self.request_id, 'recovery request_id')
        integer(self.expected_generation, 'recovery generation', 1)
        fingerprint(self.current_fingerprint, 'current fingerprint')
        fingerprint(self.source_fingerprint, 'source fingerprint')
        text(self.reason, 'recovery reason')
        if len(self.reason) > 256:
            raise ValidationError('recovery reason exceeds 256 characters')

    def digest(self):
        # Lifecycle intent includes the observed lineage/tokens, never server now.
        intent = {**asdict(self), 'operation': 'recovery', 'version': 1}
        intent.pop('request_id')
        return hashlib.sha256(canonical(intent).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    status: str
    save_id: str
    old_generation: int | None = None
    new_generation: int | None = None
    source_generation: int | None = None
    source_revision: int | None = None
    new_revision: int | None = None
    wall_anchor_ms: int | None = None
    current_fingerprint: str | None = None
    source_fingerprint: str | None = None
    reason: str = ''

    def __post_init__(self):
        uuid4_id(self.save_id, 'result save_id')
        if self.status not in ('SUCCESS', 'NO_RECOVERY_AVAILABLE', 'RECOVERY_CANDIDATE_INVALID', 'CONFLICT'):
            raise ValidationError('invalid recovery result status')
        if type(self.reason) is not str or len(self.reason) > 512:
            raise ValidationError('invalid recovery result reason')
        for name in ('old_generation', 'new_generation', 'source_generation'):
            if getattr(self, name) is not None:
                integer(getattr(self, name), name, 1)
        for name in ('source_revision', 'new_revision', 'wall_anchor_ms'):
            if getattr(self, name) is not None:
                integer(getattr(self, name), name)
        for name in ('current_fingerprint', 'source_fingerprint'):
            if getattr(self, name) is not None:
                fingerprint(getattr(self, name), name)
        if self.status == 'SUCCESS':
            required = ('old_generation', 'new_generation', 'source_generation', 'source_revision',
                        'new_revision', 'wall_anchor_ms', 'current_fingerprint', 'source_fingerprint')
            if any(getattr(self, name) is None for name in required):
                raise ValidationError('success recovery metadata missing')
            if self.new_generation <= self.old_generation or self.new_revision != 0:
                raise ValidationError('invalid recovery rollover metadata')

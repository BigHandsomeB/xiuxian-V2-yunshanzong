"""@module application/settlement
@purpose Explicit settlement request/receipt, separate from gameplay Command.
@depends core/time/model, core/validation, Python standard library
@usedBy application/memory, tests/core/test_settlement
@see ./INDEX.md
"""
from dataclasses import asdict, dataclass
import hashlib
import json

from src.core.time.model import Continuation, SettlementResult
from src.core.validation import ValidationError, integer, uuid4_id


@dataclass(frozen=True, slots=True)
class SettlementRequest:
    save_id: str
    generation: int
    expected_revision: int
    request_id: str
    max_events: int
    continuation: Continuation | None = None

    def __post_init__(self):
        uuid4_id(self.save_id, 'save_id')
        uuid4_id(self.request_id, 'request_id')
        integer(self.generation, 'generation', 1)
        integer(self.expected_revision, 'expected_revision')
        integer(self.max_events, 'max_events', 1)
        if self.continuation is not None and not isinstance(self.continuation, Continuation):
            raise ValidationError('continuation must be Continuation or null')

    def digest(self):
        intent = {'operation': 'settlement', 'version': 1, 'max_events': self.max_events,
                  'continuation': asdict(self.continuation) if self.continuation is not None else None}
        return hashlib.sha256(json.dumps(intent, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class SettlementReceipt:
    request_id: str
    committed_revision: int
    result: SettlementResult


@dataclass(frozen=True, slots=True)
class GrowthSettlementResult(SettlementResult):
    """Application-level receipt observations; no Core gameplay fields."""
    xp_gained: int = 0
    levels_gained: int = 0

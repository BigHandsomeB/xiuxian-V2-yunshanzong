"""@module core/time/model
@purpose Integer time windows, event interfaces and continuation/results.
@depends core/validation, core/state/envelope, Python standard library
@usedBy core/time/engine, application/settlement
@see ./INDEX.md
"""
from collections.abc import Callable, Mapping
from dataclasses import dataclass
import hashlib
import json

from src.core.state.envelope import freeze_json
from src.core.state.serialization import snapshot
from src.core.validation import ValidationError, integer, machine_id, text, uuid4_id

from src.core.time.config import DEFAULT_GAME_DAY_MS, OFFLINE_CAP_MS


def game_days(sim_time_ms: int, day_length_ms: int = DEFAULT_GAME_DAY_MS) -> int:
    integer(sim_time_ms, 'sim_time_ms')
    integer(day_length_ms, 'day_length_ms', 1)
    return sim_time_ms // day_length_ms


@dataclass(frozen=True, slots=True)
class TimeWindow:
    wall_anchor_ms: int
    from_sim_ms: int
    target_sim_ms: int
    accepted_ms: int
    discarded_ms: int
    clock_rollback: bool


def plan_window(time: Mapping, now_ms: int) -> TimeWindow:
    integer(now_ms, 'now_ms')
    if time['pending'] is not None:
        raise ValidationError('pending window must be resumed, not replanned')
    wall = time['last_settled_at_ms']
    start = time['sim_time_ms']
    elapsed = 0 if time.get('world_paused',False) else max(0, now_ms - wall)
    accepted = min(elapsed, OFFLINE_CAP_MS)
    return TimeWindow(max(wall, now_ms), start, start + accepted,
                      accepted, elapsed - accepted, now_ms < wall)


@dataclass(frozen=True, slots=True)
class Event:
    event_id: str
    domain: str
    due_sim_ms: int
    priority: int
    payload: Mapping

    def __post_init__(self):
        text(self.event_id, 'event_id')
        machine_id(self.domain, 'event domain')
        integer(self.due_sim_ms, 'event due_sim_ms')
        integer(self.priority, 'event priority')
        if not isinstance(self.payload, Mapping):
            raise ValidationError('event payload must be an object')
        object.__setattr__(self, 'payload', freeze_json(self.payload))

    @property
    def order(self):
        return self.due_sim_ms, self.priority, self.event_id


@dataclass(frozen=True, slots=True)
class SimulationDomain:
    events: Callable  # Immutable partition -> finite iterable[Event].
    apply: Callable   # Owned mutable partition, Event -> None (consume event).
    accrue: Callable | None = None  # Owned partition, start_ms, end_ms -> None.
    validate: Callable | None = None

    def __post_init__(self):
        for name in ('events', 'apply', 'accrue', 'validate'):
            handler = getattr(self, name)
            if (name in ('events', 'apply') or handler is not None) and not callable(handler):
                raise ValidationError(f'{name} must be callable')


def state_fingerprint(state) -> str:
    return snapshot(state)[1]


@dataclass(frozen=True, slots=True)
class Continuation:
    save_id: str
    generation: int
    revision: int
    target_sim_ms: int
    state_fingerprint: str

    def __post_init__(self):
        uuid4_id(self.save_id, 'continuation save_id')
        integer(self.generation, 'continuation generation', 1)
        integer(self.revision, 'continuation revision')
        integer(self.target_sim_ms, 'continuation target')
        if not isinstance(self.state_fingerprint, str) or len(self.state_fingerprint) != 64 or any(
            char not in '0123456789abcdef' for char in self.state_fingerprint
        ):
            raise ValidationError('continuation fingerprint must be SHA256 hex')

    @classmethod
    def for_state(cls, state):
        return cls(state.save_id, state.generation, state.revision,
                   state.time['pending']['target_sim_ms'], state_fingerprint(state))


@dataclass(frozen=True, slots=True)
class SettlementResult:
    status: str
    from_sim_ms: int
    to_sim_ms: int
    target_sim_ms: int
    processed_events: tuple[str, ...]
    accepted_ms: int
    discarded_ms: int
    clock_rollback: bool
    continuation: Continuation | None
    offline_report: dict | None = None

    @property
    def processed_work(self):
        return len(self.processed_events)

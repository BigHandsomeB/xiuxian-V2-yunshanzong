"""@module core/time/engine
@purpose Pure candidate settlement with deterministic event budget/resume.
@depends core/time/model, core/state/envelope, core/validation
@usedBy application/memory, tests/core/test_settlement
@see ./INDEX.md
"""
from src.core.time.world import require_running
from src.core.time.config import PERSISTED_OFFLINE_CAP_MS
from collections.abc import Mapping
from dataclasses import replace
from types import MappingProxyType

from src.core.state.envelope import freeze_json, thaw_json
from src.core.time.model import (
    Continuation, Event, OFFLINE_CAP_MS, SettlementResult, SimulationDomain, plan_window, state_fingerprint,
)
from src.core.validation import ConflictError, ValidationError, integer, machine_id, text


class SettlementEngine:
    """No authority, clock, timer or persistence; Domain handlers are injected."""
    def __init__(self, domains: Mapping[str, SimulationDomain], *, rules_version='settlement_v1'):
        text(rules_version, 'rules_version')
        handlers = dict(domains)
        for domain, handler in handlers.items():
            machine_id(domain, 'simulation domain')
            if not isinstance(handler, SimulationDomain):
                raise ValidationError('simulation handlers require SimulationDomain')
        self._domains = MappingProxyType(handlers)
        self._rules_version = rules_version

    def _events(self, state, working):
        events, seen = [], set()
        for domain, spec in self._domains.items():
            for event in spec.events(freeze_json(working[domain])):
                if not isinstance(event, Event) or event.domain != domain:
                    raise ValidationError('provider returned an Event for an unowned domain')
                parts = event.event_id.split(':')
                if len(parts) != 4 or parts[0] != state.save_id or parts[2] != 'e':
                    raise ValidationError('event_id must be save_id:generation:e:counter')
                try:
                    generation, counter = int(parts[1]), int(parts[3])
                except ValueError as exc:
                    raise ValidationError('invalid event identity counter') from exc
                if (str(generation) != parts[1] or str(counter) != parts[3] or
                    not 1 <= generation <= state.generation or
                    not 1 <= counter <= state.identity['event_counter']):
                    raise ValidationError('event identity outside allocated save namespace')
                if event.event_id in seen:
                    raise ValidationError('duplicate scheduled event identity')
                seen.add(event.event_id)
                events.append(event)
        return sorted(events, key=lambda event: event.order)

    def _pending(self, state, continuation):
        pending = state.time['pending']
        if not isinstance(continuation, Continuation) or pending is None:
            raise ConflictError('resume requires a matching continuation and pending state')
        if (continuation.save_id, continuation.generation, continuation.revision,
            continuation.state_fingerprint) != (
            state.save_id, state.generation, state.revision, state_fingerprint(state)
        ):
            raise ConflictError('stale continuation: state identity/content changed')
        fields = {'version', 'rules_version', 'save_id', 'generation', 'revision',
                  'from_sim_ms', 'target_sim_ms', 'wall_anchor_ms', 'accepted_ms',
                  'discarded_ms', 'last_order', 'processed_total', 'accrued_to_ms',
                  'clock_rollback'}
        if (set(pending) not in (fields, fields | {'report_id'}) or
            ('report_id' in pending and (type(pending['report_id']) is not str or not pending['report_id'])) or
            type(pending['version']) is not int or pending['version'] != 1):
            raise ValidationError('unsupported pending settlement format')
        integer(pending['generation'], 'pending generation', 1)
        integer(pending['revision'], 'pending revision')
        if (pending['rules_version'] != self._rules_version or
            (pending['save_id'], pending['generation'], pending['revision']) !=
            (state.save_id, state.generation, state.revision)):
            raise ConflictError('pending settlement identity/rules changed')
        for name in ('from_sim_ms', 'target_sim_ms', 'wall_anchor_ms', 'accepted_ms',
                     'discarded_ms', 'processed_total', 'accrued_to_ms'):
            integer(pending[name], name)
        if (not pending['from_sim_ms'] <= state.time['sim_time_ms'] <= pending['target_sim_ms'] or
            pending['target_sim_ms'] - pending['from_sim_ms'] != pending['accepted_ms'] or
            pending['accepted_ms'] > PERSISTED_OFFLINE_CAP_MS or
            pending['wall_anchor_ms'] != state.time['last_settled_at_ms'] or
            pending['accrued_to_ms'] != state.time['sim_time_ms'] or
            pending['target_sim_ms'] != continuation.target_sim_ms or
            type(pending['clock_rollback']) is not bool):
            raise ValidationError('inconsistent pending settlement watermarks')
        order = pending['last_order']
        if order is not None:
            if not isinstance(order, tuple) or len(order) != 3:
                raise ValidationError('invalid pending event cursor')
            integer(order[0], 'cursor due')
            integer(order[1], 'cursor priority')
            text(order[2], 'cursor event_id')
            if order[0] != state.time['sim_time_ms']:
                raise ValidationError('cursor and accrued position disagree')
        return thaw_json(pending)

    def validate_state(self, state):
        """Pure load validation; never advance time, consume events or read a Clock."""
        if any(domain not in state.domains for domain in self._domains):
            raise ValidationError('simulation domain missing from state')
        if state.time['pending'] is not None:
            self._pending(state, Continuation.for_state(state))
        working = {domain: state.domains[domain] for domain in self._domains}
        for domain, spec in self._domains.items():
            if spec.validate is not None:
                spec.validate(working[domain])
        events = self._events(state, working)
        pending = state.time['pending']
        order = None if pending is None else pending['last_order']
        if events and (events[0].due_sim_ms < state.time['sim_time_ms'] or
                       (order is not None and events[0].order <= tuple(order))):
            raise ValidationError('loaded event queue precedes committed cursor')

    def advance(self, state, *, max_events, now_ms=None, continuation=None):
        return self._advance(state,max_events=max_events,now_ms=now_ms,continuation=continuation)

    def _batch_step(self,state,*,now_ms=None):
        # Only the Application's private detached batch may skip external resume hashing.
        from src.core.state.draft import enabled
        if not enabled():raise ValidationError('batch step requires a detached working scope')
        return self._advance(state,max_events=1,now_ms=now_ms,internal=True)

    def _advance(self, state, *, max_events, now_ms=None, continuation=None,internal=False):
        require_running(state.time)
        integer(max_events, 'max_events', 1)
        if any(domain not in state.domains for domain in self._domains):
            raise ValidationError('simulation domain missing from state')
        start = state.time['sim_time_ms']
        if internal and state.time['pending'] is not None:
            if now_ms is not None:raise ValidationError('resume cannot claim a new wall-clock window')
            pending=dict(state.time['pending'])
        elif continuation is not None:
            if now_ms is not None:
                raise ValidationError('resume cannot claim a new wall-clock window')
            pending = self._pending(state, continuation)
        else:
            if state.time['pending'] is not None:
                raise ConflictError('pending settlement requires resume')
            window = plan_window(state.time, now_ms)
            pending = dict(version=1, rules_version=self._rules_version, save_id=state.save_id,
                           generation=state.generation, revision=state.revision,
                           from_sim_ms=window.from_sim_ms, target_sim_ms=window.target_sim_ms,
                           wall_anchor_ms=window.wall_anchor_ms, accepted_ms=window.accepted_ms,
                           discarded_ms=window.discarded_ms, last_order=None, processed_total=0,
                           accrued_to_ms=start, clock_rollback=window.clock_rollback)
        working = {domain: thaw_json(state.domains[domain]) for domain in self._domains}
        cursor = start
        target = pending['target_sim_ms']
        last_order = tuple(pending['last_order']) if pending['last_order'] is not None else None
        processed = []

        def accrue(end):
            nonlocal cursor
            if end > cursor:
                before_events = self._events(state, working)
                for domain, spec in self._domains.items():
                    if spec.accrue is not None:
                        spec.accrue(working[domain], cursor, end)
                if self._events(state, working) != before_events:
                    raise ValidationError('elapsed handlers must not edit scheduled events')
                cursor = end

        while True:
            events = self._events(state, working)
            if events and (events[0].due_sim_ms < cursor or
                           (last_order is not None and events[0].order <= last_order)):
                raise ValidationError('scheduled event precedes the committed cursor')
            if not events or events[0].due_sim_ms > target:
                accrue(target)
                complete = True
                break
            if len(processed) == max_events:
                complete = False
                break
            event = events[0]
            before_ids = {item.event_id for item in events}
            accrue(event.due_sim_ms)
            self._domains[event.domain].apply(working[event.domain], event)
            after = self._events(state, working)
            if any(item.event_id == event.event_id for item in after):
                raise ValidationError('handler must consume its event exactly once')
            if any(item.event_id not in before_ids and item.due_sim_ms <= cursor for item in after):
                raise ValidationError('newly scheduled events must move strictly forward')
            processed.append(event.event_id)
            last_order = event.order

        for domain, spec in self._domains.items():
            if not internal and spec.validate is not None:
                spec.validate(freeze_json(working[domain]))
        new_time = {**state.time, 'sim_time_ms': cursor,
                    'last_settled_at_ms': pending['wall_anchor_ms'], 'pending': None}
        if not complete:
            pending.update(revision=state.revision + 1, accrued_to_ms=cursor,
                           last_order=list(last_order),
                           processed_total=pending['processed_total'] + len(processed))
            new_time['pending'] = pending
        candidate = replace(state, time=new_time, domains={**state.domains, **working})
        if candidate != state:
            candidate = replace(candidate, revision=state.revision + 1)
        next_continuation = None if complete or internal else Continuation.for_state(candidate)
        result = SettlementResult('COMPLETE' if complete else 'PENDING', start, cursor, target,
                                  tuple(processed), pending['accepted_ms'], pending['discarded_ms'],
                                  pending['clock_rollback'], next_continuation)
        return candidate, result

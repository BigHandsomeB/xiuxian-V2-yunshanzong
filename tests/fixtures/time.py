"""TEST ONLY Clock/events/elapsed counters; no real rewards or gameplay."""
from dataclasses import replace
from uuid import uuid4

from src.application.memory import CommandSpec, MemoryApplication
from src.application.settlement import SettlementRequest
from src.core.state.envelope import StateEnvelope
from src.core.time.engine import SettlementEngine
from src.core.time.model import Event, SimulationDomain
from src.core.validation import ValidationError, integer
from tests.fixtures.foundation import increment, registry, state


class ManualClock:
    def __init__(self, value=1000):
        self.value = value
        self.reads = 0

    def now_ms(self):
        self.reads += 1
        return self.value

    def advance(self, elapsed):
        self.value += elapsed


def events(partition):
    return tuple(Event(**event) for event in partition['scheduled'])


def apply(partition, event):
    partition['value'] += 1
    partition['event_trace'].append(event.payload['label'])
    partition['scheduled'] = [item for item in partition['scheduled']
                              if item['event_id'] != event.event_id]
    if 'rate' in event.payload:
        partition['rate'] = event.payload['rate']
    if event.payload.get('reject', False):
        raise ValidationError('TEST event failed after candidate mutation')
    if event.payload.get('invalid', False):
        partition['value'] = float('nan')
    if 'new_due' in event.payload:
        identity = event.event_id.rsplit(':', 1)[0] + ':99'
        partition['scheduled'].append(dict(event_id=identity, domain=event.domain,
                                          due_sim_ms=event.payload['new_due'], priority=0,
                                          payload={'label': 'TEST future event'}))


def accrue(partition, start, end):
    partition['elapsed_ms'] += (end - start) * partition['rate']
    partition['test_cost_ms'] += end - start


def validate(partition):
    for name in ('value', 'elapsed_ms', 'test_cost_ms', 'rate'):
        integer(partition[name], 'TEST ' + name)


def initial(schedule=(), *, sim_time=0):
    base = state()
    raw = base.to_dict()
    raw['time']['sim_time_ms'] = sim_time
    raw['identity']['event_counter'] = 100
    part = raw['domains']['fixture']
    part.update(elapsed_ms=0, test_cost_ms=0, rate=1, event_trace=[], scheduled=[])
    # schedule: (due, priority, label[, payload additions]).
    for counter, row in enumerate(schedule, 1):
        due, priority, label, *extra = row
        part['scheduled'].append(dict(event_id=f'{base.save_id}:1:e:{counter}',
                                      domain='fixture', due_sim_ms=due, priority=priority,
                                      payload={'label': label, **(extra[0] if extra else {})}))
    return StateEnvelope.from_dict(raw)


def engine(*, event_apply=apply, elapsed=accrue, rules_version='settlement_v1'):
    return SettlementEngine({'fixture': SimulationDomain(events, event_apply, elapsed, validate)},
                            rules_version=rules_version)


def application(schedule=(), *, initial_state=None, clock=None, settlement=None):
    return MemoryApplication(initial_state if initial_state is not None else initial(schedule),
                             registry(), {'test_increment': CommandSpec('fixture', increment)},
                             settlement_engine=settlement if settlement is not None else engine(),
                             clock=clock if clock is not None else ManualClock())


def request(app, *, budget=100, continuation=None, request_id=None, **overrides):
    snapshot = app.query()
    fields = dict(save_id=snapshot.save_id, generation=snapshot.generation,
                  expected_revision=snapshot.revision, request_id=request_id or str(uuid4()),
                  max_events=budget, continuation=continuation)
    fields.update(overrides)
    return SettlementRequest(**fields)


def settle_all(app, *, budget=1):
    result = app.settle(request(app, budget=budget)).result
    processed = list(result.processed_events)
    while result.status == 'PENDING':
        result = app.settle(request(app, budget=budget, continuation=result.continuation)).result
        processed.extend(result.processed_events)
    return result, tuple(processed)


def simulation_content(snapshot):
    result = snapshot.to_dict()
    # revision is commit-history metadata, not simulated world content.
    result.pop('revision')
    return result

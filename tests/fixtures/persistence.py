"""TEST ONLY persistent fixture; no formal content, paths or production Save."""
from src.application.memory import CommandSpec
from src.application.persistent import PersistentApplication
from src.core.state.envelope import StateEnvelope
from src.data.registry import DefinitionKey
from tests.fixtures.foundation import increment, registry
from tests.fixtures.time import ManualClock, engine, initial


def state(schedule=()):
    raw = initial(schedule).to_dict()
    raw['domains']['fixture']['definition_refs'] = [{'domain': 'fixture', 'machine_id': 'test_entry'}]
    return StateEnvelope.from_dict(raw)


def references(snapshot):
    return tuple(DefinitionKey.from_mapping(key) for key in snapshot.domains['fixture']['definition_refs'])


def noop(partition, payload):
    return {'test_noop': True}


def application(store, clock=None):
    # Fresh Registry, engine and Application every time, especially after restart.
    return PersistentApplication(store, registry(), {'test_increment': CommandSpec('fixture', increment),
                                  'test_noop': CommandSpec('fixture', noop)},
                                 references=references, settlement_engine=engine(),
                                 clock=clock if clock is not None else ManualClock())

"""TEST ONLY: artificial definitions and commands, never game content."""
import json
from uuid import uuid4

from src.application.memory import Command, CommandSpec, MemoryApplication
from src.core.state.envelope import StateEnvelope
from src.core.validation import ValidationError, integer
from src.data.registry import DefinitionRegistry

PACKAGE = {
    'schema_version': 1,
    'content_version': 'test_fixture_v1',
    'definitions': [
        {'domain': 'fixture', 'machine_id': 'test_entry', 'display_name': 'TEST 测试定义'},
        {'domain': 'fixture', 'machine_id': 'test_reference', 'display_name': 'TEST 测试引用',
         'references': [{'domain': 'fixture', 'machine_id': 'test_entry'}]},
    ],
}


def registry():
    return DefinitionRegistry.from_json(json.dumps(PACKAGE))


def state(**overrides):
    result = StateEnvelope.create(
        content_version='test_fixture_v1', last_settled_at_ms=1000,
        domains={'fixture': {'value': 0, 'markers': []},
                 'fixture_other': {'value': 99}},
    )
    if overrides:
        data = result.to_dict()
        data.update(overrides)
        result = StateEnvelope.from_dict(data)
    return result


def increment(partition, payload):
    if set(payload) - {'amount', 'reject'} or 'amount' not in payload:
        raise ValidationError('TEST payload requires amount and optional reject')
    integer(payload['amount'], 'TEST amount', 1)
    if type(payload.get('reject', False)) is not bool:
        raise ValidationError('TEST reject must be boolean')
    partition['value'] += payload['amount']
    partition['markers'].append('TEST command')
    # Deliberate failure AFTER modifying a candidate proves rollback isolation.
    if payload.get('reject', False):
        raise ValidationError('TEST rejected candidate after mutation')
    return {'value': partition['value'], 'markers': partition['markers']}


def application(initial=None, definitions=None, transition=increment):
    return MemoryApplication(initial if initial is not None else state(),
                             definitions if definitions is not None else registry(),
                             {'test_increment': CommandSpec('fixture', transition)})


def command(app, *, amount=1, request_id=None, **overrides):
    snapshot = app.query()
    fields = dict(save_id=snapshot.save_id, generation=snapshot.generation,
                  expected_revision=snapshot.revision, request_id=request_id or str(uuid4()),
                  name='test_increment', payload={'amount': amount})
    fields.update(overrides)
    return Command(**fields)

"""Authenticated HTTP intents over disposable ecology SQLite fixtures."""
import unittest
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4
from werkzeug.test import Client
from werkzeug.wrappers import Response
from tests.systems import test_ecology as fixtures
from src.application.ecology import EcologyApplication
from src.core.save.sqlite import SQLiteSave
from src.transport.danding import create_app


class EcologyHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.EcologyTests.setUpClass()
        cls.registry = fixtures.EcologyTests.registry

    for name in ('read', 'bid', 'request', 'execute', 'command', 'assign', 'settle', 'fixture'):
        locals()[name] = getattr(fixtures.EcologyTests, name)

    def setUp(self):
        fixtures.EcologyTests.setUp(self)
        @contextmanager
        def factory():
            with SQLiteSave(self.path, allowed_root=self.root) as store:
                yield EcologyApplication(store, self.registry, self.clock)
        app = create_app(factory, self.sid, lambda view: {}, lambda _: None,
                         'isolated-ecology-http-token-123', secure=False,
                         ui_root=Path('src/ui/pages/game').resolve(), cookie_path='/')
        app.testing = True
        self.client = Client(app, Response)
        self.client.post('/login', data={'token': 'isolated-ecology-http-token-123'})

    def body(self, name, payload):
        view = self.client.get('/api/view').json
        return {'protocol_version': 1, 'save_id': self.sid, 'generation': view['generation'],
                'expected_revision': view['revision'], 'request_id': str(uuid4()),
                'command': {'name': name, 'version': 1, 'payload': payload}}

    def post(self, body):
        return self.client.post('/api/command', json=body,
            headers={'X-CSRF-Token': self.client.get('/api/view').json['csrf']})

    def test_pure_view_purchase_replay_and_stale_revision(self):
        before = self.read()
        response = self.client.get('/api/view')
        self.assertEqual(200, response.status_code)
        self.assertEqual(24, len(response.json['view']['ecology']['species']))
        self.assertEqual(before, self.read())
        body = self.body('ecology_buy', {'building_id': self.bid('pasture'),
                                      'species_id': 'pasture_species_02', 'count': 1})
        self.assertEqual(200, self.post(body).status_code)
        after = self.read()
        self.assertEqual(200, self.post(body).status_code)
        self.assertEqual(after, self.read())
        body['request_id'] = str(uuid4())
        self.assertEqual(409, self.post(body).status_code)
        self.assertEqual(after, self.read())

    def test_collect_once_and_paused_commands_rejected(self):
        self.assign('pasture')
        body = self.body('ecology_buy', {'building_id': self.bid('pasture'),
                                      'species_id': 'pasture_species_02', 'count': 1})
        self.assertEqual(200, self.post(body).status_code)
        self.settle(240000)
        batch_id = next(iter(self.read().domains['ecology']['batches']))
        collect = self.body('ecology_collect', {'batch_id': batch_id, 'count': 1, 'mode': 'periodic'})
        self.assertEqual(200, self.post(collect).status_code)
        after = self.read()
        self.assertEqual(200, self.post(collect).status_code)
        self.assertEqual(after, self.read())
        self.command('world_pause', {})
        before = self.read()
        self.assertEqual(422, self.post(self.body('ecology_supply', {'enabled': True, 'target_days': 3})).status_code)
        self.assertEqual(422, self.post(self.body('sect_recruit', {'count': 1})).status_code)
        self.assertEqual(before, self.read())

    def test_csrf_bad_species_and_public_migration_are_safe(self):
        before = self.read()
        body = self.body('ecology_buy', {'building_id': self.bid('pasture'),
                                      'species_id': 'invalid', 'count': 1})
        self.assertEqual(403, self.client.post('/api/command', json=body).status_code)
        self.assertEqual(422, self.post(body).status_code)
        self.assertIn(self.post(self.body('ecology_content_upgrade', {})).status_code, (400, 422))
        self.assertEqual(before, self.read())

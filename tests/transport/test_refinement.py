"""Authenticated refinement command, replay and invalid intent over disposable SQLite."""
import unittest
from contextlib import contextmanager
from pathlib import Path
from werkzeug.test import Client
from werkzeug.wrappers import Response
from tests import test_refinement as fixture
from tests.transport import test_ecology as http_fixture
from src.application.ecology import EcologyApplication
from src.core.save.sqlite import SQLiteSave
from src.transport.danding import create_app


class RefinementHTTPTests(unittest.TestCase):
    setUpClass = classmethod(fixture.RefinementTests.setUpClass.__func__)
    for name in ('app', 'read', 'view', 'request', 'command', 'fixture'):
        locals()[name] = getattr(fixture.RefinementTests, name)
    body = http_fixture.EcologyHTTPTests.body
    post = http_fixture.EcologyHTTPTests.post

    def setUp(self):
        fixture.RefinementTests.setUp(self)
        @contextmanager
        def factory():
            with SQLiteSave(self.path, allowed_root=self.root) as store:
                yield EcologyApplication(store, self.registry, self.clock)
        app = create_app(factory, self.sid, lambda view: {}, lambda _: None,
            'isolated-refinement-http-token-123', secure=False,
            ui_root=Path('src/ui/pages/game').resolve(), cookie_path='/')
        app.testing = True
        self.client = Client(app, Response)
        self.client.post('/login', data={'token': 'isolated-refinement-http-token-123'})

    def test_command_replay_and_pure_view(self):
        before=self.read();response=self.client.get('/api/view')
        self.assertEqual(response.status_code,200)
        self.assertEqual(len(response.json['view']['refinement']['materials']),84)
        self.assertEqual(before,self.read())
        body=self.body('equipment_refine',{'instance_id':self.item,'materials':['ore',None,None]})
        self.assertEqual(self.post(body).status_code,200);after=self.read()
        self.assertEqual(self.post(body).status_code,200);self.assertEqual(after,self.read())
        row=self.client.get('/api/view').json['view']['equipment']['instances'][0]
        self.assertEqual(row['refinement']['stats']['attack_milli'],500)

    def test_invalid_and_csrf_fail_without_spend(self):
        before=self.read();bad=self.body('equipment_refine',{'instance_id':self.item,'materials':['coins',None,None]})
        self.assertEqual(self.post(bad).status_code,422);self.assertEqual(before,self.read())
        valid=self.body('equipment_refine',{'instance_id':self.item,'materials':['ore',None,None]})
        self.assertEqual(self.client.post('/api/command',json=valid).status_code,403)
        self.assertEqual(before,self.read())

"""Authenticated recipe staffing, replay and invalid intent over disposable SQLite."""
import unittest
from contextlib import contextmanager
from pathlib import Path
from werkzeug.test import Client
from werkzeug.wrappers import Response
from tests import test_recipe_staffing as fixture
from tests.transport import test_ecology as http_fixture
from src.application.ecology import EcologyApplication
from src.core.save.sqlite import SQLiteSave
from src.transport.danding import create_app


class RecipeStaffingHTTPTests(unittest.TestCase):
    setUpClass = classmethod(fixture.RecipeStaffingTests.setUpClass.__func__)
    for name in ('app', 'read', 'view', 'request', 'command', 'fixture'):
        locals()[name] = getattr(fixture.RecipeStaffingTests, name)
    body = http_fixture.EcologyHTTPTests.body
    post = http_fixture.EcologyHTTPTests.post

    def setUp(self):
        fixture.RecipeStaffingTests.setUp(self)
        @contextmanager
        def factory():
            with SQLiteSave(self.path, allowed_root=self.root) as store:
                yield EcologyApplication(store, self.registry, self.clock)
        app = create_app(factory, self.sid, lambda view: {}, lambda _: None,
            'isolated-staffing-http-token-123', secure=False,
            ui_root=Path('src/ui/pages/game').resolve(), cookie_path='/')
        app.testing = True
        self.client = Client(app, Response)
        self.client.post('/login', data={'token': 'isolated-staffing-http-token-123'})

    def test_adjust_replay_and_view_counts(self):
        before=self.read();view=self.client.get('/api/view')
        self.assertEqual(view.status_code,200);self.assertEqual(before,self.read())
        body=self.body('work_recipe_adjust',{'building_id':self.alchemy,'recipe_id':'pill','delta':1})
        self.assertEqual(self.post(body).status_code,200);after=self.read()
        self.assertEqual(self.post(body).status_code,200);self.assertEqual(after,self.read())
        model=self.client.get('/api/view').json['view']['recipe_staffing']
        building=next(b for b in model['buildings'] if b['building_id']==self.alchemy)
        self.assertEqual(next(r for r in building['rows'] if r['recipe_id']=='pill')['count'],1)
        minus=self.body('work_recipe_adjust',{'building_id':self.alchemy,'recipe_id':'pill','delta':-1})
        self.assertEqual(self.post(minus).status_code,200)

    def test_invalid_count_wrong_building_and_csrf_are_atomic(self):
        before=self.read()
        for rid,delta in [('pill',2),('pill',True),('herb',1)]:
            bad=self.body('work_recipe_adjust',{'building_id':self.alchemy,'recipe_id':rid,'delta':delta})
            self.assertEqual(self.post(bad).status_code,422);self.assertEqual(before,self.read())
        good=self.body('work_recipe_adjust',{'building_id':self.alchemy,'recipe_id':'pill','delta':1})
        self.assertEqual(self.client.post('/api/command',json=good).status_code,403)
        self.assertEqual(before,self.read())

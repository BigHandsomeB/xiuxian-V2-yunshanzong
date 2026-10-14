"""Committed receipt progress is sufficient to resume without querying the UI view."""
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4
from src.core.save.sqlite import SQLiteSave, V2_ROOT
from src.application.sect_management import ManagementApplication
from src.transport.danding import create_app
from tests.systems import test_settlement_batch as fixtures


class SettleProgressHTTPTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.SettlementBatchTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        self.fixture = fixture; self.state = fixture.state; fixture.clock.advance(80000)
        temp = tempfile.TemporaryDirectory(dir=V2_ROOT/'tests'); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name); self.path = self.root/'http.sqlite3'
        with SQLiteSave.initialize(self.path, allowed_root=self.root) as store:
            ManagementApplication(store, fixture.registry, fixture.clock).create(self.state)
        self.client = self.make_web().test_client()
        with self.client.session_transaction() as session:
            session['authenticated'] = True; session['csrf'] = 'fixture-csrf'
        self.body = dict(protocol_version=1, save_id=self.state.save_id, generation=self.state.generation,
                         expected_revision=self.state.revision, request_id=str(uuid4()), continuation=None)

    @contextmanager
    def application(self):
        with SQLiteSave(self.path, allowed_root=self.root) as store:
            game = ManagementApplication(store, self.fixture.registry, self.fixture.clock)
            game.settlement_max_events = 2
            def forbidden(*args): raise AssertionError('settle must not load the UI view')
            original=game.view
            game.view = lambda *args: forbidden(*args) if game.query(self.state.save_id).time['pending'] else original(*args)
            yield game

    def make_web(self):
        return create_app(self.application, self.state.save_id, lambda v: {}, lambda *args: None,
                          'isolated-test-access-token-000000', secure=False, cookie_path='/')

    def post(self, body):
        return self.client.post('/api/settle', json=body, headers={'X-CSRF-Token': 'fixture-csrf'})

    def test_progress_matches_commit_and_replay_does_not_advance(self):
        response = self.post(self.body); self.assertEqual(response.status_code, 200)
        p = response.get_json(); self.assertTrue(p['time']['pending'])
        self.assertEqual(p['time']['target_sim_ms'], 80000)
        self.assertEqual(p['time']['remaining_ms'], 80000-p['time']['simulation_time_ms'])
        self.assertEqual(p['revision'], p['receipt']['committed_revision'])
        self.assertEqual(p['time']['continuation'], p['receipt']['result']['continuation'])
        self.assertNotIn('csrf', p); self.assertNotIn('view', p)
        with self.application() as game: before = game.query(self.state.save_id)
        self.assertEqual(self.post(self.body).get_json(), p)
        with self.application() as game: self.assertEqual(game.query(self.state.save_id), before)

    def test_fixed_target_resume_and_stale_revision(self):
        p = self.post(self.body).get_json(); self.fixture.clock.advance(1000000)
        stale = {**self.body, 'request_id': str(uuid4())}
        self.assertEqual(self.post(stale).status_code, 409)
        next_body = {**self.body, 'expected_revision': p['revision'], 'request_id': str(uuid4()), 'continuation': p['time']['continuation']}
        next_p = self.post(next_body).get_json()
        self.assertEqual(next_p['time']['target_sim_ms'], 80000)
        self.assertGreater(next_p['time']['simulation_time_ms'], p['time']['simulation_time_ms'])

    def test_request_limits_and_csrf_are_unchanged(self):
        self.assertEqual(self.client.post('/api/settle', json=self.body).status_code, 403)
        self.assertEqual(self.client.post('/api/settle', data='x'*4097, content_type='application/json', headers={'X-CSRF-Token': 'fixture-csrf'}).status_code, 413)

    def test_complete_returns_view_once_and_old_receipt_fields_remain(self):
        body=self.body
        for _ in range(100):
            p=self.post(body).get_json()
            self.assertEqual(p['processed_count'],p['receipt']['result']['processed_count'])
            if p['complete']:
                self.assertEqual(p['view']['revision'],p['revision'])
                self.assertIn('presentation',p)
                break
            self.assertNotIn('view',p)
            body={**body,'expected_revision':p['revision'],'request_id':str(uuid4()),'continuation':p['time']['continuation']}
        else:self.fail('did not complete')

"""Real auth/CSRF, per-route limits, and nonmutation of the current gameplay save."""
import copy
import json
from io import BytesIO
from src.application.save_backup import SaveBackup
from src.core.save.backup import BackupStore, MAX_SAVE_BYTES
from src.transport.danding import create_app
from src.transport.save import register
from tests.core.test_save_backup import snapshot
from tests.transport import test_danding as fixtures
TOKEN = fixtures.TOKEN
import unittest


class SaveHTTPTests(unittest.TestCase):
    def setUp(self):
        fixtures.DandingTests.setUp(self)
        self.csrf = self.view()['csrf']
    tearDown = fixtures.DandingTests.tearDown
    application = fixtures.DandingTests.application
    login = fixtures.DandingTests.login
    view = fixtures.DandingTests.view

    def make_web(self):
        app = create_app(self.application, self.save, lambda v: {}, self.assets.file, TOKEN,
                         secure=False, cookie_path='/game/')
        app.config['SESSION_COOKIE_PATH'] = '/'
        self.backups = SaveBackup(self.application, BackupStore(self.root/'backup.sqlite3', self.root), self.save)
        register(app, self.backups)
        return app

    def raw(self):
        with self.application() as game:
            return game.query(self.save).to_dict()

    def put(self, save, base=0, **options):
        return self.client.put('/api/save', json={'save': save, 'baseVersion': base},
                               headers={'X-CSRF-Token': self.csrf}, **options)

    def test_get_exports_full_state_without_initializing_backup(self):
        before = self.raw()
        response = self.client.get('/api/save')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['serverState'], before)
        self.assertIsNone(response.json['save'])
        self.assertFalse((self.root/'backup.sqlite3').exists())
        self.assertEqual(self.raw(), before)

    def test_put_changes_backup_only_and_exports_no_private_data(self):
        before = self.raw()
        save = snapshot(before)
        save['state']['domains']['inventory']['holdings']['coins'] = 1
        response = self.put(save)
        self.assertEqual(response.status_code, 200)
        output = self.client.get('/api/save').json
        self.assertEqual(output['save'], save)
        self.assertEqual(self.raw(), before)
        for key in ('csrf', 'session', 'xianxia-game-pending-v1'):
            self.assertNotIn(key, json.dumps(output))

    def test_only_save_put_allows_more_than_4k(self):
        save = snapshot(self.raw())
        body = json.dumps({'save': save, 'baseVersion': 0}) + ' '*6000
        self.assertGreater(len(body), 4096)
        self.assertEqual(self.client.put('/api/save', data=body, content_type='application/json', headers={'X-CSRF-Token': self.csrf}).status_code, 200)
        before = self.raw()
        for path in ('command', 'settle', 'save'):
            self.assertEqual(self.client.post('/api/'+path, data=' '*4097, content_type='application/json', headers={'X-CSRF-Token': self.csrf}).status_code, 413)
        self.assertEqual(self.raw(), before)
        self.assertEqual(self.web.config['MAX_CONTENT_LENGTH'], 4096)

    def test_save_put_limit_and_streamed_old_requests(self):
        self.assertEqual(self.client.put('/api/save', data=' '*(MAX_SAVE_BYTES+1), content_type='application/json', headers={'X-CSRF-Token': self.csrf}).status_code, 413)
        body = json.dumps({'save': snapshot(self.raw()), 'baseVersion': 0})+' '*6000
        self.assertEqual(self.client.put('/api/save', data=body, content_type='application/json', headers={'X-CSRF-Token': self.csrf}, environ_overrides={'CONTENT_LENGTH': None, 'wsgi.input_terminated': True}).status_code, 200)
        self.assertEqual(self.client.put('/api/save', data='{}'+' '*MAX_SAVE_BYTES, content_type='application/json', headers={'X-CSRF-Token': self.csrf}, environ_overrides={'CONTENT_LENGTH': None, 'wsgi.input_terminated': True}).status_code, 413)
        for path in ('command', 'settle'):
            response = self.client.post('/api/'+path, data=' '*4097, content_type='application/json', headers={'X-CSRF-Token': self.csrf}, environ_overrides={'CONTENT_LENGTH': None, 'wsgi.input_terminated': True})
            self.assertEqual(response.status_code, 413)
        class PartialStream(BytesIO):
            def read(self, size=-1):
                return super().read(min(size, 37))
        self.assertEqual(self.client.put('/api/save', content_type='application/json', headers={'X-CSRF-Token': self.csrf}, environ_overrides={'CONTENT_LENGTH': None, 'wsgi.input_terminated': True, 'wsgi.input': PartialStream(b'{}'+b' '*MAX_SAVE_BYTES)}).status_code, 413)

    def test_anonymous_and_csrf_and_origin_block_put(self):
        body = {'save': snapshot(self.raw()), 'baseVersion': 0}
        anonymous = self.web.test_client()
        self.assertEqual(anonymous.get('/api/save').status_code, 401)
        self.assertEqual(anonymous.put('/api/save', json=body).status_code, 401)
        self.assertEqual(self.client.put('/api/save', json=body).status_code, 403)
        self.assertEqual(self.client.put('/api/save', json=body, headers={'X-CSRF-Token': self.csrf, 'Origin': 'https://elsewhere.invalid'}).status_code, 403)

    def test_put_is_not_enabled_for_other_routes_or_legacy(self):
        self.assertEqual(self.client.put('/api/command', json={}).status_code, 405)
        legacy = create_app(self.application, self.save, lambda v: {}, self.assets.file, TOKEN, secure=False)
        self.assertEqual(legacy.test_client().put('/api/save', json={}).status_code, 405)

    def test_stale_save_reports_current_version_and_preserves_both_states(self):
        first = snapshot(self.raw())
        self.assertEqual(self.put(first).status_code, 200)
        for version in (1, 7):
            branch = snapshot(self.raw(), version=version)
            branch['state']['domains']['inventory']['holdings']['coins'] = version
            response = self.put(branch, 1)
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json['currentVersion'], 1)
            self.assertEqual(self.client.get('/api/save').json['save'], first)

    def test_malformed_domain_future_format_wrong_identity_private_data(self):
        original = snapshot(self.raw())
        cases = []
        bad = copy.deepcopy(original);bad['state']['domains']['inventory']['holdings']['coins'] = -1;cases.append(bad)
        bad = copy.deepcopy(original);bad['state']['domains']['inventory']['csrf'] = 'private';cases.append(bad)
        bad = copy.deepcopy(original);bad['formatVersion'] = 99;cases.append(bad)
        bad = copy.deepcopy(original);bad['state']['content_version'] = 'future';cases.append(bad)
        for bad in cases:
            self.assertEqual(self.put(bad).status_code, 422)
        self.assertFalse((self.root/'backup.sqlite3').exists())

    def test_server_factory_registers_game_only(self):
        from pathlib import Path
        text = (Path(__file__).resolve().parents[2]/'tools/playable/server.py').read_text()
        self.assertIn('register_save(game,backup_application', text)
        self.assertNotIn('register_save(app,', text)

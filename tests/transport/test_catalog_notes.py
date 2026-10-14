"""Planning-note HTTP writes stay outside game saves and Asset Manager SQLite."""
import tempfile,unittest,json
from pathlib import Path
from contextlib import contextmanager
from unittest.mock import patch
from werkzeug.test import Client
from werkzeug.wrappers import Response
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from src.application.catalog_notes import CatalogNotes,NotesConflict
from src.core.save.sqlite import SQLiteSave,V2_ROOT
from src.application.ecology import EcologyApplication
from src.transport.danding import create_app
from tests.systems import test_ecology as fixtures

class CatalogNotesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):fixtures.EcologyTests.setUpClass.__func__(cls)
    def setUp(self):
        fixtures.EcologyTests.setUp(self);(self.root/'registry').mkdir();self.notes=CatalogNotes(self.root,lambda:{'icon.test','icon.other'})
        @contextmanager
        def factory():
            with SQLiteSave(self.path,allowed_root=self.root) as store:yield EcologyApplication(store,self.registry,self.clock)
        self.factory=factory
        app=create_app(factory,self.sid,lambda _: {},lambda _:None,'test-only-catalog-description-token',secure=False,cookie_path='/game/',catalog_notes=self.notes)
        self.client=Client(DispatcherMiddleware(lambda e,s:[],{'/game':app}),Response)
        self.payload={'asset_id':'icon.test','expected_revision':0,'grade':'玄阶','function':'兑换功法','note':'<script>这里只是文本</script>\n待讨论'}
    def login(self):self.client.post('/game/login',data={'token':'test-only-catalog-description-token'});return self.client.get('/game/api/view').json['csrf']
    def state(self):
        with self.factory() as app:return app.query(self.sid)
    def test_authenticated_save_reload_replay_and_game_unchanged(self):
        csrf=self.login();before=self.state();response=self.client.post('/game/api/catalog-notes',json=self.payload,headers={'X-CSRF-Token':csrf})
        self.assertEqual(response.status_code,200,response.json);self.assertEqual(response.json['entry']['revision'],1)
        self.assertEqual(self.notes.read()['assets']['icon.test']['note'],self.payload['note']);self.assertEqual(self.state(),before)
        self.assertEqual(self.client.post('/game/api/catalog-notes',json=self.payload,headers={'X-CSRF-Token':csrf}).json,response.json)
        self.assertEqual(CatalogNotes(self.root,lambda:{'icon.test'}).read(),self.notes.read())
    def test_auth_csrf_length_and_unknown_asset_fail_without_write(self):
        self.assertEqual(self.client.post('/game/api/catalog-notes',json=self.payload).status_code,401)
        csrf=self.login();self.assertEqual(self.client.post('/game/api/catalog-notes',json=self.payload).status_code,403)
        for payload in [{**self.payload,'asset_id':'../../outside'},{**self.payload,'grade':'x'*25},{**self.payload,'extra':'unknown'}]:self.assertEqual(self.client.post('/game/api/catalog-notes',json=payload,headers={'X-CSRF-Token':csrf}).status_code,422)
        self.assertFalse(self.notes.path.exists())
    def test_conflict_preserves_latest_and_reports_note_revision(self):
        csrf=self.login();headers={'X-CSRF-Token':csrf};self.client.post('/game/api/catalog-notes',json=self.payload,headers=headers)
        response=self.client.post('/game/api/catalog-notes',json={**self.payload,'note':'旧页面覆盖'},headers=headers)
        self.assertEqual(response.status_code,409);self.assertEqual(response.json['current_revision'],1)
        self.assertEqual(self.notes.read()['assets']['icon.test']['note'],self.payload['note'])
    def test_atomic_replace_failure_does_not_truncate_previous_file(self):
        self.notes.write(self.payload);before=self.notes.path.read_bytes()
        with patch('src.application.catalog_notes.os.replace',side_effect=OSError('isolated failure')):
            with self.assertRaises(OSError):self.notes.write({**self.payload,'expected_revision':1,'note':'新版'})
        self.assertEqual(self.notes.path.read_bytes(),before);self.assertFalse(list(self.notes.path.parent.glob('.notes-*')))

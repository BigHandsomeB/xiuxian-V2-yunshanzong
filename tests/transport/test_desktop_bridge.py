"""Real in-process routes preserve desktop save/CSRF/replay guards without sockets."""
import json
import socket
import unittest
from unittest.mock import patch
from tests.transport import test_danding as fixtures
from tools.playable.desktop_bridge import DesktopSession

class DesktopBridgeTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.DandingTests('test_initial_scenario_uses_real_domains');self.fixture.setUp()
        with patch.object(socket.socket,'bind',side_effect=AssertionError('No listener allowed')), patch.object(socket.socket,'connect',side_effect=AssertionError('No network allowed')):
            self.desktop=DesktopSession(self.fixture.application,self.fixture.save,self.fixture.root)
            self.current=self.call('/game/api/view')['json']
    def tearDown(self):self.fixture.tearDown()
    def call(self,path,method='GET',body=None,csrf=None):
        headers={'Content-Type':'application/json'}
        if csrf is not None:headers['X-CSRF-Token']=csrf
        response=self.desktop.request({'path':path,'method':method,'body':json.dumps(body) if body else None,'headers':headers})
        return {**response,'json':json.loads(response['body'])}
    def test_authenticated_read_without_network(self):
        self.assertEqual(self.current['view']['save_id'],self.fixture.save)
        self.assertTrue(self.current['csrf'])
    def test_write_requires_csrf(self):
        body=self.fixture.body('unassign')
        self.assertEqual(self.call('/game/api/command','POST',body)['status'],403)
    def test_replay_keeps_same_receipt_and_state(self):
        body=self.fixture.body('unassign');csrf=self.current['csrf']
        first=self.call('/game/api/command','POST',body,csrf)
        second=self.call('/game/api/command','POST',body,csrf)
        self.assertEqual(first['status'],200);self.assertEqual(first['json']['receipt'],second['json']['receipt'])
        self.assertEqual(first['json']['view'],second['json']['view'])
    def test_stale_revision_rejected(self):
        body=self.fixture.body('unassign');body['expected_revision']+=99
        self.assertEqual(self.call('/game/api/command','POST',body,self.current['csrf'])['status'],409)
    def test_bridge_rejects_non_game_routes(self):
        for path in ('http://example.com','/game/login','/game/api/../static/game.js','/other'):
            with self.assertRaises(ValueError):self.desktop.request({'path':path})
        self.assertEqual(self.desktop.resource('/README.md')[0],404)
    def test_internal_page_and_static_resources(self):
        status,mime,data=self.desktop.resource('/game/')
        self.assertEqual(status,200);self.assertIn(b'game-shell',data)
        self.assertEqual(self.desktop.resource('/game/static/game.js')[0],200)

    def test_asset_bridge_only_returns_approved_images(self):
        import base64
        path='/game/runtime/icon.test/'+'a'*64
        with patch.object(self.desktop,'resource',return_value=(200,'image/png',b'png')) as resource:
            reply=self.desktop.asset(path)
            self.assertEqual(base64.b64decode(reply['base64']),b'png')
            resource.assert_called_once_with(path)
        for path in ('/game/api/view','/game/static/game.js','/game/runtime/../private/'+'a'*64):
            with self.assertRaises(ValueError):self.desktop.asset(path)
        with patch.object(self.desktop,'resource',return_value=(404,'text/plain',b'missing')):
            self.assertNotIn('base64',self.desktop.asset('/game/runtime/icon.test/'+'a'*64))

    def test_projection_reference_reuses_artwork_and_recovers_lost_reply(self):
        def read(reference):
            return json.loads(self.desktop.request({'path':'/game/api/view','presentation_ref':reference})['body'])
        first=read(0);ref=first['presentation']['desktop_ref']
        self.assertEqual(first['presentation']['projection'],self.current['presentation'])
        second=read(ref)
        self.assertEqual(second['presentation'],{'desktop_ref':ref})
        self.assertEqual(second['view'],first['view'])
        self.assertEqual(read(0)['presentation']['projection'],self.current['presentation'])
        self.desktop.artwork.invalidate()
        changed=read(ref)['presentation']
        self.assertGreater(changed['desktop_ref'],ref);self.assertIn('projection',changed)
        # Non-native consumers continue to receive the full standard protocol.
        self.assertNotIn('desktop_ref',self.call('/game/api/view')['json']['presentation'])

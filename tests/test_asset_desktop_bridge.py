"""Direct desktop transport preserves asset auth, image validation and publication rules."""
import base64,json,socket,unittest
from unittest.mock import patch
from tests import test_asset_game_link as fixtures
from tools.asset_manager.desktop_bridge import DesktopSession,MAX_BODY


class AssetDesktopBridgeTests(unittest.TestCase):
    setUp=fixtures.AssetGameLinkTests.setUp
    def session(self):return DesktopSession(self.root)
    def call(self,session,path,body=None,csrf=None,**extra):
        headers={'Content-Type':'application/json'}
        if csrf:headers['X-CSRF-Token']=csrf
        return session.request(dict(path=path,method='POST' if body is not None or extra else 'GET',
                                    headers=headers,body=json.dumps(body) if body is not None else None,**extra))
    def test_session_works_without_socket_and_auth_remains(self):
        with patch.object(socket.socket,'bind',side_effect=AssertionError('No network')):
            session=self.session();response=self.call(session,'/api/state?compact=1')
            self.assertEqual(response['status'],200);self.assertTrue(json.loads(response['body'])['csrf'])
            self.assertEqual(self.app.test_client().get('/api/game-runtime').status_code,401)
    def test_csrf_and_explicit_publication_still_required(self):
        session=self.session();state=json.loads(self.call(session,'/api/state?compact=1')['body'])
        body={'asset_id':'icon.resource.link_test'}
        self.assertEqual(self.call(session,'/api/game-runtime/register',body)['status'],403)
        self.assertEqual(self.call(session,'/api/game-runtime/register',body,state['csrf'])['status'],200)
        self.assertEqual(json.loads(self.manifest.read_text()),self.original)
        self.assertEqual(self.call(session,'/api/publish',{},state['csrf'])['status'],200)
        self.assertEqual(json.loads(self.manifest.read_text()),self.original)
    def test_formdata_image_upload_and_preview(self):
        session=self.session();csrf=json.loads(self.call(session,'/api/state?compact=1')['body'])['csrf']
        form=[{'name':'template_id','value':'resource_icon_v1'},
              {'name':'file','filename':'透明测试.png','type':'image/png','base64':base64.b64encode(self.old.read_bytes()).decode()}]
        response=self.call(session,'/api/source',csrf=csrf,multipart=form)
        self.assertEqual(response['status'],200,response)
        source=json.loads(response['body']);status,mime,image=session.resource('/file/source/'+source['source_id']+'/0/0')
        self.assertEqual(status,200);self.assertEqual(mime,'image/png');self.assertEqual(image,self.old.read_bytes())
        self.assertEqual(json.loads(self.manifest.read_text()),self.original)
    def test_invalid_image_is_rejected_by_existing_pipeline(self):
        session=self.session();csrf=json.loads(self.call(session,'/api/state?compact=1')['body'])['csrf']
        form=[{'name':'template_id','value':'resource_icon_v1'},
              {'name':'file','filename':'bad.png','base64':base64.b64encode(b'not an image').decode()}]
        self.assertEqual(self.call(session,'/api/source',csrf=csrf,multipart=form)['status'],400)
        self.assertEqual(self.cat.list('source'),[])
    def test_routes_and_oversized_uploads_are_rejected(self):
        session=self.session()
        for path in ('http://evil/api/state','//evil/api/state','/game/api/view','/api/../file/x','/api/%2e%2e/file/x','/api/state#x'):
            with self.subTest(path=path),self.assertRaises(ValueError):self.call(session,path)
        with self.assertRaises(ValueError):self.call(session,'/api/source',multipart=[{'name':'file','filename':'big.png','base64':base64.b64encode(b'a'*(MAX_BODY+1)).decode()}])
        with self.assertRaises(ValueError):self.call(session,'/api/publish',multipart=[])
        self.assertEqual(session.resource('/login')[0],404)
        self.assertEqual(session.resource('/game/')[0],404)
    def test_desktop_reads_shared_published_images(self):
        session=self.session();before=self.manifest.read_bytes()
        self.assertEqual(session.resource('/game-runtime/image/icon.resource.link_test')[0],200)
        self.old.write_bytes(b'corrupt')
        self.assertEqual(session.resource('/game-runtime/image/icon.resource.link_test')[0],400)
        self.assertEqual(self.manifest.read_bytes(),before)
    def test_game_launcher_only_starts_desktop_module(self):
        from tools.asset_manager.launch import launch
        with patch('tools.asset_manager.launch.subprocess.Popen') as popen:
            launch();args=popen.call_args.args[0]
            self.assertEqual(args[-2:],['-m','tools.asset_manager.desktop'])
            self.assertNotIn('shell',popen.call_args.kwargs)

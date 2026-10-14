"""Authenticated game mount/security and shipped module graph checks."""
from pathlib import Path
import re
import unittest
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.test import Client
from werkzeug.wrappers import Response
from src.rendering.game import present,manifest
from src.transport.danding import create_app
from tests.transport import test_game_shell as shell_tests
from tests.transport.test_danding import TOKEN

ROOT=Path(__file__).resolve().parents[2]
UI=ROOT/'src/ui/pages/game'

class MobileRoutesTests(unittest.TestCase):
    setUp=shell_tests.GameShellTests.setUp
    tearDown=shell_tests.GameShellTests.tearDown
    application=shell_tests.GameShellTests.application
    login=shell_tests.GameShellTests.login
    make_web=shell_tests.GameShellTests.make_web

    def mounted(self):
        web=create_app(self.application,self.save,lambda v:present(v,self.assets),self.assets.file,TOKEN,
                       ui_root=UI,cookie_path='/game/',asset_view=lambda:manifest(self.assets),secure=False)
        def absent(environ,start_response):start_response('404 Not Found',[]);return [b'Not Found']
        client=Client(DispatcherMiddleware(absent,{'/game':web}),Response)
        client.post('/game/login',data={'token':TOKEN})
        return client

    def test_game_root_and_every_es_module_route(self):
        c=self.mounted();page=c.get('/game/');self.assertEqual(page.status_code,200)
        self.assertIn('viewport-fit=cover',page.text);self.assertIn('/game/static/game.js',page.text)
        self.assertEqual(page.text.count('data-tab='),5)
        for path in (UI/'static').rglob('*.js'):
            response=c.get('/game/static/'+path.relative_to(UI/'static').as_posix())
            self.assertEqual(response.status_code,200,path);response.close()
            for target in re.findall(r"from ['\"]([^'\"]+)['\"]",path.read_text()):
                self.assertTrue((path.parent/target).resolve().is_file(),(path,target))
        response=c.get('/game/static/game.css');self.assertEqual(response.status_code,200);response.close()

    def test_game_cookie_csrf_manifest_and_private_routes(self):
        c=self.mounted();view=c.get('/game/api/view');self.assertEqual(view.status_code,200)
        self.assertEqual(c.get('/game/api/assets').status_code,200)
        self.assertEqual(c.post('/game/api/command',json={}).status_code,403)
        private=Client(c.application,Response)
        self.assertEqual(private.get('/game/api/view').status_code,401)
        self.assertEqual(private.get('/game/api/assets').status_code,401)
        self.assertEqual(private.get('/game/').status_code,302)
        response=private.post('/game/login',data={'token':TOKEN})
        self.assertIn('Path=/game/',response.headers['Set-Cookie'])
        self.assertIn('HttpOnly',response.headers['Set-Cookie']);self.assertIn('SameSite=Strict',response.headers['Set-Cookie'])

    def test_loading_empty_error_offline_safe_area_and_no_daily_scene(self):
        html=(UI/'index.html').read_text();css=(UI/'static/game.css').read_text();js=(UI/'static/game.js').read_text()
        self.assertIn('loading-state',html);self.assertIn('safe-area-inset-bottom',css)
        self.assertIn("addEventListener('offline'",js);self.assertIn("addEventListener('online'",js)
        for name in ['sect','building','inventory','disciples','cultivation']:
            source=(UI/f'static/screens/{name}.js').read_text()
            self.assertNotIn('mountBattle',source);self.assertNotIn('scene-image',source)
        self.assertIn('prefers-reduced-motion',css)

if __name__=='__main__':unittest.main()

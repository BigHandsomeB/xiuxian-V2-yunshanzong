"""The reserved Manifest/Runtime contract connects the manager without touching saves."""
import hashlib,io,json,tempfile,unittest
from pathlib import Path
from PIL import Image
from tools.asset_manager.catalog import PROJECT
from tools.asset_manager.local import linked_app
from tools.asset_manager.model import REVIEW
from src.rendering.game_runtime import GameRuntimeAssets

TOKEN='asset-game-link-test-token-long-enough'
class AssetGameLinkTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=PROJECT/'.tmp');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'assets';(self.root/'runtime').mkdir(parents=True)
        image=Image.new('RGBA',(48,48),(10,90,50,255));out=io.BytesIO();image.save(out,format='PNG')
        self.old=self.root/'runtime/old.png';self.old.write_bytes(out.getvalue());digest=hashlib.sha256(out.getvalue()).hexdigest()
        row={'version':1,'format':'png','export_origin':{'template_id':'resource_icon_v1','template_version':1},'files':[{'file':'runtime/old.png','width':48,'height':48,'sha256':digest}]}
        self.original={'schema_version':1,'assets':{'icon.resource.link_test':row,'icon.resource.untouched':row}}
        self.manifest=self.root/'manifest.json';self.manifest.write_text(json.dumps(self.original))
        self.app=linked_app(TOKEN,self.root);self.cat=self.app.extensions['asset_catalog'];self.client=self.app.test_client()
    def login(self):
        self.assertEqual(self.client.post('/login',data={'token':TOKEN}).status_code,302)
        return self.client.get('/api/state?compact=1').json['csrf']
    def register(self,csrf):
        return self.client.post('/api/game-runtime/register',json={'asset_id':'icon.resource.link_test'},headers={'X-CSRF-Token':csrf})
    def test_authentication_and_csrf_are_required(self):
        self.assertEqual(self.client.get('/api/game-runtime').status_code,401)
        self.assertEqual(self.client.get('/game-runtime/image/icon.resource.link_test').status_code,401)
        csrf=self.login();self.assertEqual(self.register('wrong').status_code,403)
        self.assertEqual(self.register(csrf).status_code,200)
    def test_empty_catalog_publication_keeps_game_runtime(self):
        self.assertEqual(self.cat.publish(),self.original)
        self.assertEqual(self.cat.list('asset'),[])
    def test_register_draft_does_not_fabricate_history_or_unpublish(self):
        csrf=self.login();self.assertEqual(self.register(csrf).status_code,200)
        self.assertEqual(self.register(csrf).status_code,200)
        self.assertEqual(len(self.cat.list('asset')),1)
        self.assertEqual(self.cat.get('asset','icon.resource.link_test')['versions'],[])
        self.assertEqual(self.cat.list('source'),[])
        self.assertEqual(self.cat.publish(),self.original)
    def test_approved_replacement_reaches_game_and_preserves_other_assets(self):
        csrf=self.login();self.register(csrf);identity='icon.resource.link_test'
        image=Image.new('RGBA',(48,48),(90,30,150,255));out=io.BytesIO();image.save(out,format='PNG')
        source=self.cat.upload('synthetic-new.png',out.getvalue(),'resource_icon_v1')
        plan=self.cat.plan(source['source_id'],{'icon':1},'independent')
        self.cat.import_version(identity,plan,True)
        self.assertEqual(self.cat.publish(),self.original)
        self.cat.review(identity,1,'needs_review');self.cat.review(identity,1,'approved',{k:True for k in REVIEW})
        self.cat.select(identity,1);self.cat.build(identity,1);published=self.cat.publish()
        self.assertEqual(published['assets']['icon.resource.untouched'],self.original['assets']['icon.resource.untouched'])
        runtime=GameRuntimeAssets(self.root);resolved=runtime.resolve(identity)
        self.assertNotEqual(resolved['digest'],self.original['assets'][identity]['files'][0]['sha256'])
        self.assertIsNotNone(runtime.file(identity,resolved['digest']));self.assertTrue(self.old.exists())
        self.cat.review(identity,1,'deprecated');self.cat.publish()
        self.assertNotIn(identity,json.loads(self.manifest.read_text())['assets'])
        self.assertIn('icon.resource.untouched',json.loads(self.manifest.read_text())['assets'])
    def test_library_is_readonly_and_preview_checks_digest(self):
        self.login();before=self.manifest.read_bytes()
        response=self.client.get('/api/game-runtime');self.assertEqual(response.json['count'],2)
        self.assertEqual(self.client.get('/game-runtime').status_code,200)
        response=self.client.get('/game-runtime/image/icon.resource.link_test');self.assertEqual(response.status_code,200);response.close()
        self.assertEqual(self.manifest.read_bytes(),before);self.assertEqual(self.cat.list('asset'),[])
        self.old.write_bytes(b'corrupt')
        self.assertEqual(self.client.get('/game-runtime/image/icon.resource.link_test').status_code,400)

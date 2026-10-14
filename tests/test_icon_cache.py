"""HTTP caching stays scoped to successful hash-addressed artwork."""
import unittest
from io import BytesIO
from pathlib import Path
from src.transport.danding import create_app
from src.transport.ui_review import create_review_app
ROOT=Path(__file__).resolve().parents[1]
URL='/runtime/test.icon/'+'a'*64
class IconCacheTests(unittest.TestCase):
 def private(self):
  app=create_app(lambda:None,'test-cache',lambda _:None,lambda a,d:BytesIO(b'png') if d=='a'*64 else None,'test-only-icon-cache-token',secure=False,cookie_path='/',ui_root=ROOT/'src/ui/pages/game')
  return app.test_client()
 def test_private_auth_and_cache_scope(self):
  c=self.private();r=c.get(URL);self.assertEqual(r.status_code,401);self.assertEqual(r.headers['Cache-Control'],'no-store')
  c.post('/login',data={'token':'test-only-icon-cache-token'})
  r=c.get(URL);self.assertEqual(r.status_code,200);self.assertEqual(r.headers['Cache-Control'],'private, max-age=31536000, immutable');etag=r.headers['ETag'];r.close()
  r=c.get(URL,headers={'If-None-Match':etag});self.assertEqual(r.status_code,304);self.assertIn('private',r.headers['Cache-Control']);r.close()
  r=c.get('/runtime/test.icon/'+'b'*64);self.assertEqual(r.status_code,404);self.assertEqual(r.headers['Cache-Control'],'no-store')
  r=c.get('/static/game.css');self.assertEqual(r.headers['Cache-Control'],'no-store');r.close()
 def test_public_review_images_only(self):
  bundle={'assets':{},'views':{},'image':'/game/review'+URL}
  app=create_review_app(bundle,lambda a,d:BytesIO(b'png'),ui_root=ROOT/'src/ui/pages/game',guide_root=ROOT/'src/ui/pages/review',design_file=ROOT/'docs/gameplay/current-game-overview.md')
  c=app.test_client();r=c.get(URL);self.assertEqual(r.status_code,200);self.assertEqual(r.headers['Cache-Control'],'public, max-age=31536000, immutable');r.close()
  r=c.get('/runtime/unknown.icon/'+'a'*64);self.assertEqual(r.status_code,404);self.assertEqual(r.headers['Cache-Control'],'no-store')
  r=c.get('/api/assets');self.assertEqual(r.status_code,200);self.assertEqual(r.headers['Cache-Control'],'no-store')

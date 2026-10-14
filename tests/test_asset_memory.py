"""Asset server heap lifecycle only; no live service or artwork mutation."""
import unittest
from unittest.mock import patch, Mock
from flask import Flask
from tools.asset_manager.server import install_heap_reclamation

class AssetMemoryTests(unittest.TestCase):
    def make_app(self):
        app=Flask(__name__)
        app.add_url_rule("/image", "auto_locate", lambda: "image result", methods=["POST"])
        app.add_url_rule("/read", "state", lambda: "read result")
        app.add_url_rule("/metadata", "rename", lambda: "renamed", methods=["POST"])
        return app

    def test_completed_image_request_collects_then_returns_unused_heap(self):
        app=self.make_app();lib=Mock();order=[]
        lib.malloc_trim.side_effect=lambda padding:order.append(("trim",padding))
        with patch("tools.asset_manager.server.ctypes.CDLL",return_value=lib), patch("tools.asset_manager.server.gc.collect",side_effect=lambda:order.append(("collect",))):
            self.assertTrue(install_heap_reclamation(app))
            r=app.test_client().post("/image")
            self.assertEqual(r.data,b"image result")
            self.assertEqual(order,[("collect",),("trim",0)])

    def test_queries_and_metadata_do_not_collect_per_request(self):
        app=self.make_app();lib=Mock()
        with patch("tools.asset_manager.server.ctypes.CDLL",return_value=lib), patch("tools.asset_manager.server.gc.collect") as collect:
            install_heap_reclamation(app)
            client=app.test_client();self.assertEqual(client.get("/read").status_code,200);self.assertEqual(client.post("/metadata").status_code,200)
            collect.assert_not_called();lib.malloc_trim.assert_not_called()

    def test_unsupported_allocator_keeps_normal_request_behavior(self):
        for error in [AttributeError("unsupported"),OSError("unavailable")]:
            with self.subTest(error=type(error).__name__), patch("tools.asset_manager.server.ctypes.CDLL",side_effect=error):
                app=self.make_app();self.assertFalse(install_heap_reclamation(app));self.assertEqual(app.test_client().post("/image").data,b"image result")

    def test_reclamation_failure_does_not_fail_successful_image_request(self):
        app=self.make_app();lib=Mock();lib.malloc_trim.side_effect=OSError("optional failure")
        with patch("tools.asset_manager.server.ctypes.CDLL",return_value=lib), patch("tools.asset_manager.server.gc.collect"):
            install_heap_reclamation(app);self.assertEqual(app.test_client().post("/image").data,b"image result")

    def test_failed_image_request_also_reclaims_without_rewriting_error(self):
        app=self.make_app();app.add_url_rule("/bad", "build", lambda: ("invalid image",400),methods=["POST"]);lib=Mock()
        with patch("tools.asset_manager.server.ctypes.CDLL",return_value=lib), patch("tools.asset_manager.server.gc.collect") as collect:
            install_heap_reclamation(app);r=app.test_client().post("/bad")
            self.assertEqual((r.status_code,r.data),(400,b"invalid image"));collect.assert_called_once();lib.malloc_trim.assert_called_once_with(0)

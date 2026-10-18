"""Independent authenticated asset-tool server behind the local HTTPS proxy."""
import os, ctypes, gc
from flask import request
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.serving import make_server
from werkzeug.wrappers import Response
from .catalog import PROJECT
from .web import create_app

# Only the asset process's released image buffers are returned to the allocator.
IMAGE_ENDPOINTS = frozenset({"source", "quick_preview", "quick_confirm", "auto_locate", "plan", "import_asset", "import_static_set", "replace_frame", "review", "build"})

def install_heap_reclamation(app):
    """Optional glibc optimization; never drops kernel caches or changes asset files."""
    try:
        trim = ctypes.CDLL(None).malloc_trim
        trim.argtypes = [ctypes.c_size_t]
        trim.restype = ctypes.c_int
    except (AttributeError, OSError):
        return False  # Non-glibc platforms keep ordinary Python memory management.

    @app.teardown_request
    def release_image_heap(error):
        if request.method == "POST" and request.endpoint in IMAGE_ENDPOINTS:
            gc.collect()
            try:
                trim(0)
            except (OSError, ValueError):
                pass  # Memory optimization must not change command success/failure.
    return True

def application():
    app = create_app(PROJECT / "assets", os.environ["ASSET_MANAGER_TOKEN"], os.environ.get("ASSET_MANAGER_ALLOWED_HOSTS", "localhost,127.0.0.1").split(","))
    install_heap_reclamation(app)
    app.config.update(SESSION_COOKIE_SECURE=True, SESSION_COOKIE_PATH="/tools/assets/")
    mounted = DispatcherMiddleware(Response("Not found", status=404), {"/tools/assets": app})
    return ProxyFix(mounted, x_proto=1)

if __name__ == "__main__":
    make_server("127.0.0.1", 8002, application(), threaded=True).serve_forever()


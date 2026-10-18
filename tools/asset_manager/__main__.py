"""Local developer tool entry point; no production service installation."""
import os
from .catalog import PROJECT
from .web import create_app

if __name__ == "__main__":
    create_app(PROJECT / "assets", os.environ.get("ASSET_MANAGER_TOKEN", "")).run(host="127.0.0.1", port=8001, debug=False, use_reloader=False)


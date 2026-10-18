"""Fixed local command; opening the workbench never starts an HTTP server."""
import os,subprocess,sys
from pathlib import Path


def launch():
    if getattr(sys,'frozen',False):
        return subprocess.Popen([sys.executable,'--asset-manager'],cwd=Path(sys.executable).parent,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    executable=Path(sys.executable)
    if os.name=='nt':executable=executable.with_name('pythonw.exe')
    return subprocess.Popen([str(executable),'-X','utf8','-m','tools.asset_manager.desktop'],
                            cwd=Path(__file__).resolve().parents[2],
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)

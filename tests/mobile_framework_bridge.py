"""Isolated test-only WSGI adapter, no listening service or production Save access."""
import json,sys
from contextlib import contextmanager
from pathlib import Path
from http.cookies import SimpleCookie
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.test import Client
from werkzeug.wrappers import Response
from src.application.danding import initial_slice
from src.application.world import WorldApplication
from src.transport.combat import register
from src.core.save.sqlite import SQLiteSave
from src.data.cultivation.definitions import load_cultivation
from src.rendering.game_runtime import GameRuntimeAssets
from src.rendering.game import present,manifest
from src.transport.danding import create_app
from tests.fixtures.time import ManualClock
root=Path(sys.argv[1] if len(sys.argv)>1 else '.tmp/framework-combat-e2e').resolve()
project=Path(__file__).resolve().parents[1]
if not root.is_relative_to(project/'.tmp') or root==project/'.tmp' or root.is_symlink():raise RuntimeError('test-only root must be a dedicated V2 .tmp directory')
root.mkdir(exist_ok=True)
path=root/'test.sqlite3';registry=load_cultivation();clock=ManualClock(int((root/'clock').read_text()) if (root/'clock').exists() else 1000)
if not path.exists():
 state=initial_slice(registry,last_settled_at_ms=1000)
 from dataclasses import replace
 from src.systems.inventory.operations import grant
 inventory,_=grant(state.domains['inventory'],registry,{'pill':26,'coins':80},capacity=1000)
 state=replace(state,domains={**state.domains,'inventory':inventory})
 with SQLiteSave.initialize(path,allowed_root=root) as store:WorldApplication(store,registry,clock).create(state)
 (root/'save-id').write_text(state.save_id)
identity=(root/'save-id').read_text()
@contextmanager
def application():
 with SQLiteSave(path,allowed_root=root) as store:yield WorldApplication(store,registry,clock)
assets=GameRuntimeAssets(root/'assets')
app=create_app(application,identity,lambda v:present(v,assets),assets.file,'test-only-framework-combat-e2e-token',secure=False,ui_root=Path('src/ui/pages/game').resolve(),cookie_path='/game/',asset_view=lambda:manifest(assets))
register(app,application,identity)
def absent(e,start):start('404 Not Found',[]);return [b'Not Found']
c=Client(DispatcherMiddleware(absent,{'/game':app}),Response)
cookie=root/'cookie'
if cookie.exists():c.set_cookie('xianxia_game',cookie.read_text(),path='/game/')
else:
 r=c.post('/game/login',data={'token':'test-only-framework-combat-e2e-token'});jar=SimpleCookie();jar.load(r.headers['Set-Cookie']);cookie.write_text(jar['xianxia_game'].value)
request=json.loads(sys.stdin.read())
r=c.open(request['path'],method=request.get('method','GET'),data=request.get('body'),headers=request.get('headers',{}))
print(json.dumps({'status':r.status_code,'result':r.json}))

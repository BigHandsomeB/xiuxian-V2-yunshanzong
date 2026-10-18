"""In-process desktop transport. No socket server or network client is created."""
import json
import base64
import re
import secrets
from threading import RLock
from urllib.parse import urlsplit
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.test import Client
from werkzeug.wrappers import Response
from src.transport.danding import create_app
from src.transport.combat import register as register_combat
from src.transport.save import register as register_save
from src.rendering.game import manifest
from src.rendering.desktop_artwork import DesktopArtwork
from src.rendering.game_runtime import GameRuntimeAssets
from src.application.catalog_notes import CatalogNotes
from tools.playable.game import PROJECT, configured_game, backup_application


class DesktopSession:
    def __init__(self, factory=None, save_id=None, root=None):
        if factory is None:factory,save_id=configured_game()
        self.lock=RLock();self.presentation_ref=0;self.presentation_value=None;self.request_ref=None
        assets=GameRuntimeAssets(PROJECT/'assets');self.artwork=DesktopArtwork(assets,(root or PROJECT/'.game')/'desktop-artwork.json')
        token=secrets.token_urlsafe(32)
        game=create_app(factory,save_id,self.presentation,assets.file,token,
                        allowed_hosts=['localhost'],secure=False,ui_root=PROJECT/'src/ui/pages/game',
                        cookie_path='/game/',asset_view=lambda:manifest(assets),
                        catalog_notes=CatalogNotes(PROJECT/'assets',lambda:set(assets.snapshot())))
        register_combat(game,factory,save_id)
        register_save(game,backup_application(factory,save_id,root or PROJECT/'.game'))
        self.client=Client(DispatcherMiddleware(Response(status=404),{'/game':game}),Response)
        response=self.client.post('/game/login',data={'token':token})
        if response.status_code!=302:raise RuntimeError('Desktop session initialization failed')

    def presentation(self,view):
        value=self.artwork(view)
        if self.request_ref is None:return value
        if value is not self.presentation_value:
            self.presentation_value=value;self.presentation_ref+=1
        # The window reports its last received projection. A cancelled/lost reply
        # therefore cannot strand it with an unknown reference.
        result={'desktop_ref':self.presentation_ref}
        if self.request_ref!=self.presentation_ref:result['projection']=value
        return result

    def request(self, payload):
        """Keep existing auth, CSRF, revision checks and idempotent receipts in-process."""
        if not isinstance(payload,dict):raise ValueError('Invalid desktop request')
        path=payload.get('path','');method=payload.get('method','GET')
        if (not isinstance(path,str) or not path.startswith('/game/api/') or
            any(c in path for c in ('\\','..','#')) or urlsplit(path).netloc or
            method not in ('GET','POST','PUT')):raise ValueError('Invalid desktop route')
        headers=payload.get('headers') or {}
        if not isinstance(headers,dict):raise ValueError('Invalid desktop headers')
        body=payload.get('body')
        if body is not None and (not isinstance(body,str) or len(body.encode())>8*1024*1024):
            raise ValueError('Desktop request too large')
        with self.lock:
            if urlsplit(path).path=='/game/api/assets':self.artwork.invalidate()
            reference=payload.get('presentation_ref')
            if reference is not None and (type(reference) is not int or reference<0):raise ValueError('Invalid presentation reference')
            self.request_ref=reference
            try:
                with self.client.open(path,method=method,headers={k:v for k,v in headers.items()
                                      if k.lower() in ('content-type','x-csrf-token')},data=body) as response:
                    return {'status':response.status_code,'body':response.get_data(as_text=True)}
            finally:self.request_ref=None

    def resource(self,path):
        if path!='/game/' and not path.startswith(('/game/static/','/game/runtime/')):
            return 404,'text/plain',b'Not found'
        with self.lock:
            with self.client.get(path) as response:
                return response.status_code,response.mimetype,response.get_data()

    def asset(self,path):
        """Only fingerprint-addressed, approved images can enter the window cache."""
        if not isinstance(path,str) or not re.fullmatch(r'/game/runtime/[a-z][a-z0-9_.]*/[0-9a-f]{64}',path):
            raise ValueError('Invalid desktop asset')
        status,mime,data=self.resource(path)
        if status!=200 or not mime.startswith('image/'):
            return {'status':status if status!=200 else 415}
        return {'status':200,'mime':mime,'base64':base64.b64encode(data).decode('ascii')}

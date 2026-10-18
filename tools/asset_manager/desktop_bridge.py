"""Asset-only in-process transport, including multipart image uploads."""
import base64,io,secrets
from threading import RLock
from urllib.parse import unquote,urlsplit
from werkzeug.datastructures import MultiDict
from werkzeug.test import Client
from werkzeug.wrappers import Response
from .local import linked_app

MAX_BODY=13*1024*1024
MAX_MESSAGE=18*1024*1024


class DesktopSession:
    desktop_pages=('/', '/game-runtime')
    desktop_script='/static/desktop-bridge.js'

    def __init__(self,root=None):
        self.lock=RLock();token=secrets.token_urlsafe(32)
        self.app=linked_app(token,root)
        self.client=Client(self.app,Response)
        with self.client.post('/login',data={'token':token}) as response:
            if response.status_code!=302:raise RuntimeError('Asset desktop initialization failed')

    @staticmethod
    def safe_path(path):
        if not isinstance(path,str):raise ValueError('Invalid path')
        url=urlsplit(path);decoded=unquote(path)
        if (not path.startswith('/') or path.startswith('//') or url.scheme or url.netloc or
            any(c in decoded for c in ('\\','..','#','\x00'))):raise ValueError('Invalid path')
        return url.path

    def request(self,payload):
        if not isinstance(payload,dict):raise ValueError('Invalid request')
        path=payload.get('path','');route=self.safe_path(path);method=payload.get('method','GET')
        if not route.startswith('/api/') or method not in ('GET','POST'):raise ValueError('Invalid asset route')
        headers=payload.get('headers') or {}
        if not isinstance(headers,dict):raise ValueError('Invalid headers')
        headers={k:v for k,v in headers.items() if k.lower() in ('content-type','x-csrf-token')}
        data=payload.get('body');multipart=payload.get('multipart')
        streams=[]
        try:
            if multipart is not None:
                if route!='/api/source' or method!='POST' or data is not None or not isinstance(multipart,list) or len(multipart)>32:
                    raise ValueError('Invalid image upload')
                data=MultiDict();size=0
                for entry in multipart:
                    key=entry['name']
                    if not isinstance(key,str) or len(key)>128:raise ValueError('Invalid form field')
                    if 'base64' in entry:
                        encoded=entry['base64']
                        if not isinstance(encoded,str) or len(encoded)>MAX_MESSAGE:raise ValueError('Image too large')
                        raw=base64.b64decode(encoded,validate=True);size+=len(raw)
                        stream=io.BytesIO(raw);streams.append(stream)
                        value=(stream,entry['filename'],entry.get('type') or 'application/octet-stream')
                    else:
                        value=entry['value']
                        if not isinstance(value,str):raise ValueError('Invalid form value')
                        size+=len(value.encode('utf-8'))
                    if size>MAX_BODY:raise ValueError('Image upload too large')
                    data.add(key,value)
                headers={k:v for k,v in headers.items() if k.lower()!='content-type'}
            elif data is not None and (not isinstance(data,str) or len(data.encode('utf-8'))>MAX_BODY):
                raise ValueError('Request too large')
            with self.lock:
                with self.client.open(path,method=method,headers=headers,data=data) as response:
                    return {'status':response.status_code,'body':response.get_data(as_text=True)}
        finally:
            for stream in streams:stream.close()

    def resource(self,path):
        route=self.safe_path(path)
        if route not in self.desktop_pages and not route.startswith(('/static/','/file/','/game-runtime/image/')):
            return 404,'text/plain',b'Not found'
        with self.lock:
            with self.client.get(path) as response:
                return response.status_code,response.mimetype,response.get_data()

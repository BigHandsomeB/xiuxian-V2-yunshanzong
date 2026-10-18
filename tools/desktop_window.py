"""Internal resource scheme shared by the game and asset workbench windows."""
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QFile, Signal, Slot
from PySide6.QtWebEngineCore import (QWebEnginePage, QWebEngineUrlSchemeHandler,
                                    QWebEngineUrlRequestJob, QWebEngineUrlRequestInterceptor)


class Resources(QWebEngineUrlSchemeHandler):
    ready=Signal(object,int,str,object)
    def __init__(self,session,parent):
        super().__init__(parent);self.session=session;self.pool=ThreadPoolExecutor(max_workers=2)
        self.ready.connect(self.deliver)
    def requestStarted(self,job):
        url=job.requestUrl()
        if url.host()!='desktop' or bytes(job.requestMethod())!=b'GET':
            job.fail(QWebEngineUrlRequestJob.Error.RequestDenied);return
        path=url.path()
        def load():
            try:
                if path=='/desktop/channel.js':
                    source=QFile(':/qtwebchannel/qwebchannel.js')
                    source.open(QIODevice.OpenModeFlag.ReadOnly);data=bytes(source.readAll());source.close()
                    status,mime=200,'text/javascript'
                else:status,mime,data=self.session.resource(path)
                if path in getattr(self.session,'desktop_pages',('/game/',)) and status==200:
                    scripts='<script src="/desktop/channel.js"></script><script src="'+getattr(self.session,'desktop_script','/game/static/desktop-bridge.js')+'"></script>'
                    policy="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'none'; object-src 'none'; base-uri 'none'; frame-src 'none'"
                    data=data.replace(b'<head>',('<head><meta http-equiv="Content-Security-Policy" content="'+policy+'">'+scripts).encode(),1)
                self.ready.emit(job,status,mime,data)
            except Exception:
                import logging
                logging.exception('Desktop resource failed');self.ready.emit(job,500,'text/plain',b'Unavailable')
        self.pool.submit(load)
    @Slot(object,int,str,object)
    def deliver(self,job,status,mime,data):
        from shiboken6 import isValid
        if not isValid(job):return  # Navigation can cancel an image while it is loading.
        if status!=200:
            job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound);return
        buffer=QBuffer(job);buffer.setData(QByteArray(data));buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        job.reply(mime.encode('ascii'),buffer)


class InternalOnly(QWebEngineUrlRequestInterceptor):
    def interceptRequest(self,info):
        url=info.requestUrl()
        if not ((url.scheme()=='yunshan' and url.host()=='desktop') or url.scheme() in ('data','blob','about')):
            info.block(True)


class Page(QWebEnginePage):
    def __init__(self,profile,parent):super().__init__(profile,parent);self.errors=[]
    def acceptNavigationRequest(self,url,kind,main):
        return (url.scheme()=='yunshan' and url.host()=='desktop') or url.toString()=='about:blank'
    def javaScriptConsoleMessage(self,level,message,line,source):
        if level==QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            self.errors.append(message);print('Desktop JS:',message,flush=True)


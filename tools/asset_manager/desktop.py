"""Native asset workbench; no TCP listener, browser login or game save access."""
import hashlib,json,sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from PySide6.QtCore import QObject,QTimer,QUrl,Signal,Slot
from PySide6.QtNetwork import QLocalServer,QLocalSocket
from PySide6.QtWidgets import QApplication,QFileDialog,QMessageBox
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage,QWebEngineProfile,QWebEngineUrlScheme
from PySide6.QtWebEngineWidgets import QWebEngineView
from tools.desktop_window import Resources,InternalOnly,Page
from .catalog import PROJECT
from .desktop_bridge import DesktopSession,MAX_MESSAGE


class Bridge(QObject):
    completed=Signal(str,str)
    def __init__(self,session,parent):
        super().__init__(parent);self.session=session;self.pool=ThreadPoolExecutor(max_workers=1);self.calls=0
    @Slot(str,str)
    def request(self,identity,raw):
        if len(raw)>MAX_MESSAGE:
            self.completed.emit(identity,json.dumps({'error':'上传数据过大'}));return
        self.calls+=1
        def work():
            try:result=self.session.request(json.loads(raw))
            except Exception:
                import logging
                logging.exception('Asset desktop request failed');result={'error':'素材操作失败，请检查图片或输入；操作不会自动重试。'}
            self.completed.emit(identity,json.dumps(result,ensure_ascii=False))
        self.pool.submit(work)


def run(session=None,smoke=False):
    scheme=QWebEngineUrlScheme(b'yunshan');scheme.setSyntax(QWebEngineUrlScheme.Syntax.Host)
    scheme.setFlags(QWebEngineUrlScheme.Flag.SecureScheme|QWebEngineUrlScheme.Flag.CorsEnabled)
    QWebEngineUrlScheme.registerScheme(scheme)
    app=QApplication(sys.argv[:1]);app.setApplicationName('云山宗素材工坊')
    # QLocalServer uses Windows named pipes, not a TCP port. Reopening raises the window.
    name='yunshan-assets-'+hashlib.sha256(str(PROJECT).encode()).hexdigest()[:24]
    server=QLocalServer(app)
    if not smoke:
        client=QLocalSocket();client.connectToServer(name)
        if client.waitForConnected(500):client.disconnectFromServer();return 0
        QLocalServer.removeServer(name)
        if not server.listen(name):raise RuntimeError('Cannot acquire asset window')
    if session is None:session=DesktopSession()
    view=QWebEngineView();view.resize(1180,850);view.setWindowTitle('云山宗 · 素材工坊')
    def activate():
        while server.hasPendingConnections():
            connection=server.nextPendingConnection();connection.disconnectFromServer();connection.deleteLater()
        view.showNormal();view.raise_();view.activateWindow()
    server.newConnection.connect(activate)
    profile=QWebEngineProfile('yunshan-assets',view) if not smoke else QWebEngineProfile(view)
    if not smoke:
        storage=PROJECT/'.asset-manager/desktop-profile';storage.mkdir(parents=True,exist_ok=True)
        profile.setPersistentStoragePath(str(storage));profile.setCachePath(str(storage/'cache'))
    handler=Resources(session,profile);profile.installUrlSchemeHandler(b'yunshan',handler)
    interceptor=InternalOnly(profile);profile.setUrlRequestInterceptor(interceptor)
    page=Page(profile,view);view.setPage(page)
    channel=QWebChannel(page);bridge=Bridge(session,page);channel.registerObject('assets',bridge);page.setWebChannel(channel)
    def download(item):
        name,_=QFileDialog.getSaveFileName(view,'保存素材',item.suggestedFileName(),'所有文件 (*)')
        if name:
            item.setDownloadDirectory(str(Path(name).parent));item.setDownloadFileName(Path(name).name);item.accept()
        else:item.cancel()
    profile.downloadRequested.connect(download)
    result=[0];finished=[False];stage=[0]
    if smoke:
        # Exercise the real UI bridge, including FormData uploads, navigation and canvas previews.
        import base64,io
        from PIL import Image
        stream=io.BytesIO();Image.new('RGBA',(48,48),(30,120,70,255)).save(stream,format='PNG')
        encoded=base64.b64encode(stream.getvalue()).decode()
        def inspect():
            page.runJavaScript("JSON.stringify({heading:document.querySelector('h1')?.innerText,notice:document.getElementById('notice')?.innerText,library:!!document.querySelector('#runtime-list img'),upload:window.__upload,canvas:window.__canvas,error:window.__smokeError})",checked)
        def finish(ok,data):
            if finished[0]:return
            finished[0]=True;result[0]=0 if ok and not page.errors else 1
            print('ASSET_DESKTOP_SMOKE',json.dumps({'calls':bridge.calls,'ui':data,'errors':page.errors},ensure_ascii=False),flush=True)
            view.grab().save(str(PROJECT/'.tmp/asset-manager-desktop-smoke.png'));view.close();app.quit()
        def checked(raw):
            if finished[0]:return
            data=json.loads(raw or '{}')
            if data.get('error'):finish(False,data);return
            if stage[0]==0 and bridge.calls and data.get('heading'):
                stage[0]=1
                page.runJavaScript("""(async()=>{try{
                 const state=await (await fetch('/api/state?compact=1')).json();
                 const file=new File([Uint8Array.from(atob('"""+encoded+"""'),c=>c.charCodeAt(0))],'desktop-test.png',{type:'image/png'});
                 const form=new FormData();form.set('file',file);form.set('template_id','resource_icon_v1');
                 const response=await fetch('/api/source',{method:'POST',headers:{'X-CSRF-Token':state.csrf},body:form});
                 const source=await response.json();if(!response.ok)throw Error(JSON.stringify(source));
                 window.__upload=source.source_id;
                 const img=new Image();img.onload=()=>{try{const c=document.createElement('canvas');c.width=48;c.height=48;c.getContext('2d').drawImage(img,0,0);window.__canvas=c.toDataURL().startsWith('data:image/png');}catch(e){window.__smokeError=String(e);}};
                 img.onerror=()=>window.__smokeError='Image failed';img.src='/file/source/'+source.source_id+'/0/0';
                }catch(e){window.__smokeError=String(e);}})()""")
            elif stage[0]==1 and data.get('upload') and data.get('canvas'):
                stage[0]=2;page.runJavaScript("location.href='/game-runtime'")
            elif stage[0]==2 and data.get('library'):
                stage[0]=3;page.runJavaScript("location.href='/#browse'")
            elif stage[0]==3 and data.get('heading') and bridge.calls>=6:
                finish(True,data);return
            QTimer.singleShot(500,inspect)
        QTimer.singleShot(1000,inspect);QTimer.singleShot(45000,lambda:finish(False,{'timeout':True}))
    view.setUrl(QUrl('yunshan://desktop/'));view.show();app.exec()
    bridge.pool.shutdown(wait=True);handler.pool.shutdown(wait=True)
    view.setPage(QWebEnginePage(view));page.deleteLater();app.processEvents();server.close()
    return result[0]


def main():
    if '--smoke-test' not in sys.argv:return run()
    import tempfile,io,socket
    from PIL import Image
    from unittest.mock import patch
    directory=PROJECT/'.tmp';directory.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='asset-desktop-',dir=directory) as temporary:
        root=Path(temporary)/'assets';(root/'runtime').mkdir(parents=True)
        stream=io.BytesIO();Image.new('RGBA',(48,48),(90,30,80,255)).save(stream,format='PNG')
        data=stream.getvalue();(root/'runtime/test.png').write_bytes(data)
        row={'version':1,'format':'png','files':[{'file':'runtime/test.png','width':48,'height':48,'sha256':hashlib.sha256(data).hexdigest()}]}
        (root/'manifest.json').write_text(json.dumps({'schema_version':1,'assets':{'icon.resource.test':row}}))
        with patch.object(socket.socket,'bind',side_effect=AssertionError('Desktop cannot bind TCP')):
            return run(DesktopSession(root),smoke=True)


if __name__=='__main__':
    try:sys.exit(main())
    except Exception:
        import traceback
        if '--smoke-test' in sys.argv:raise
        log=PROJECT/'.asset-manager/desktop-error.log';log.parent.mkdir(parents=True,exist_ok=True)
        log.write_text(traceback.format_exc(),encoding='utf-8')
        app=QApplication.instance() or QApplication(sys.argv[:1])
        QMessageBox.critical(None,'素材工坊启动失败','请查看 .asset-manager/desktop-error.log 中的错误信息。')
        sys.exit(1)

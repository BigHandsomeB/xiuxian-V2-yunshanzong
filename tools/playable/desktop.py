"""Native Windows game window, QWebChannel calls and internal asset scheme; no TCP."""
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from PySide6.QtCore import QObject, QUrl, Signal, Slot, QLockFile, QTimer
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import (QWebEnginePage, QWebEngineProfile, QWebEngineUrlScheme)
from PySide6.QtWebEngineWidgets import QWebEngineView
from tools.desktop_window import Resources, InternalOnly, Page
from tools.playable.desktop_bridge import DesktopSession
from tools.playable.game import PROJECT


class Bridge(QObject):
    completed=Signal(str,str)
    def __init__(self,session,parent):
        super().__init__(parent);self.session=session;self.pool=ThreadPoolExecutor(max_workers=1)
        self.calls=0;self.asset_calls=0;self.asset_loads={};self.asset_pool=ThreadPoolExecutor(max_workers=2)
    @Slot(str,str)
    def request(self,identity,raw):
        if len(raw)>9*1024*1024:return self.completed.emit(identity,json.dumps({'error':'Request too large'}))
        self.calls+=1
        def work():
            try:result=self.session.request(json.loads(raw))
            except Exception:
                import logging
                logging.exception('Desktop request failed')
                result={'error':'桌面调用失败，请更新状态后重试；原请求已保留。'}
            self.completed.emit(identity,json.dumps(result,ensure_ascii=False))
        self.pool.submit(work)

    @Slot(str,str)
    def open_manager(self,identity,unused):
        try:
            from tools.asset_manager.launch import launch
            launch()
            result={'ok':True}
        except Exception:
            import logging
            logging.exception('Cannot open asset manager')
            result={'error':'素材管理器启动失败，请运行 start-asset-manager.cmd 查看错误。'}
        self.completed.emit(identity,json.dumps(result,ensure_ascii=False))

    @Slot(str,str)
    def asset(self,identity,path):
        self.asset_calls+=1;self.asset_loads[path]=self.asset_loads.get(path,0)+1
        def work():
            try:result=self.session.asset(path)
            except Exception:result={'error':'图标暂不可用'}
            self.completed.emit(identity,json.dumps(result,ensure_ascii=False))
        self.asset_pool.submit(work)



def run(session=None,smoke=False):
    scheme=QWebEngineUrlScheme(b'yunshan');scheme.setSyntax(QWebEngineUrlScheme.Syntax.Host)
    scheme.setFlags(QWebEngineUrlScheme.Flag.SecureScheme|QWebEngineUrlScheme.Flag.CorsEnabled)
    QWebEngineUrlScheme.registerScheme(scheme)
    app=QApplication(sys.argv[:1]);app.setApplicationName('云山宗')
    lock=QLockFile(str(PROJECT/'.game/desktop.lock'));lock.setStaleLockTime(0)
    if not smoke and not lock.tryLock(0):
        QMessageBox.information(None,'云山宗','游戏桌面窗口已在运行，请切换到已有窗口。');return 1
    if session is None:session=DesktopSession()
    view=QWebEngineView();view.setWindowTitle('云山宗 · 修仙宗门');view.resize(520,900)
    profile=QWebEngineProfile('yunshan-desktop',view) if not smoke else QWebEngineProfile(view)
    if not smoke:
        storage=PROJECT/'.game/desktop-profile';storage.mkdir(exist_ok=True)
        profile.setPersistentStoragePath(str(storage));profile.setCachePath(str(storage/'cache'))
    handler=Resources(session,profile);profile.installUrlSchemeHandler(b'yunshan',handler)
    interceptor=InternalOnly(profile);profile.setUrlRequestInterceptor(interceptor)
    page=Page(profile,view);view.setPage(page)
    channel=QWebChannel(page);bridge=Bridge(session,page);channel.registerObject('desktop',bridge);page.setWebChannel(channel)
    def download(item):
        name,_=QFileDialog.getSaveFileName(view,'导出游戏存档',item.suggestedFileName(),'JSON (*.json);;所有文件 (*)')
        if name:
            item.setDownloadDirectory(str(Path(name).parent));item.setDownloadFileName(Path(name).name);item.accept()
        else:item.cancel()
    profile.downloadRequested.connect(download)
    result=[0];smoke_done=[False];smoke_stage=[0]
    if smoke:
        def inspect():
            page.runJavaScript("JSON.stringify({clockProgress:[...document.querySelectorAll('.sect-time-rail')].reduce((s,n)=>s+n.value,0),clockAdvanced:!!window.__clockAdvanced,text:document.getElementById('screen')?.innerText||'',world:document.getElementById('world-status')?.innerText||'',ready:!document.getElementById('world-toggle')?.disabled,battle:!!document.querySelector('.battle-scene'),retained:!window.__smokeIcons||window.__smokeIcons.every(n=>document.getElementById('screen').contains(n)),cachedIcons:[...document.querySelectorAll('#screen img.runtime-icon')].filter(i=>i.src.startsWith('blob:')&&i.complete&&i.naturalWidth>0).length,images:[...document.images].filter(i=>i.complete&&i.naturalWidth>0).length})",checked)
        def checked(raw):
            if smoke_done[0]:return
            data=json.loads(raw or '{}')
            if data.get('text') and '正在推开' not in data['text'] and bridge.calls>=3 and data.get('images',0)>0:
                if smoke_stage[0]==0:
                    if data.get('ready'):
                        smoke_stage[0]=-1;page.runJavaScript("window.__clockStart="+str(data.get('clockProgress',0)))
                    QTimer.singleShot(1000,inspect);return
                if smoke_stage[0]==-1:
                    page.runJavaScript("window.__clockAdvanced=[...document.querySelectorAll('.sect-time-rail')].reduce((s,n)=>s+n.value,0)>window.__clockStart")
                    if data.get('clockAdvanced'):
                        smoke_stage[0]=1;page.runJavaScript("document.getElementById('world-toggle').click()")
                    QTimer.singleShot(500,inspect);return
                if smoke_stage[0]==1:
                    if '暂停' in data.get('world',''):
                        smoke_stage[0]=2;page.runJavaScript("location.hash='#battle'")
                    QTimer.singleShot(1000,inspect);return
                if smoke_stage[0]==2 and data.get('battle'):
                    smoke_stage[0]=3;QTimer.singleShot(4000,inspect);return
                if smoke_stage[0]<3 and not data.get('battle'):
                    QTimer.singleShot(1000,inspect);return
                if smoke_stage[0]==3:
                    smoke_stage[0]=4;page.runJavaScript("location.hash='#sect'")
                    QTimer.singleShot(3000,inspect);return
                if smoke_stage[0]==4:
                    smoke_stage[0]=5;page.runJavaScript("window.__smokeIcons=[...document.querySelectorAll('#screen img.runtime-icon')];location.hash='#inventory'")
                    QTimer.singleShot(3000,inspect);return
                if smoke_stage[0]==5:
                    smoke_stage[0]=6;page.runJavaScript("location.hash='#sect'")
                    QTimer.singleShot(3000,inspect);return
                smoke_done[0]=True
                duplicate_loads=max(bridge.asset_loads.values(),default=0)>1
                result[0]=1 if page.errors or duplicate_loads or not data.get('clockAdvanced') or not data.get('retained') or not data.get('cachedIcons') else 0
                print('DESKTOP_SMOKE',json.dumps({'calls':bridge.calls,'paused':True,'smooth_clock':data.get('clockAdvanced'),'cached_icons':data['cachedIcons'],'retained_icons':data['retained'],'asset_loads':bridge.asset_calls,'unique_assets':len(bridge.asset_loads),'images':data['images'],'screen':data['text'][:80],'errors':page.errors},ensure_ascii=False),flush=True)
                view.grab().save(str(PROJECT/'.tmp/desktop-smoke.png'))
                view.close();app.quit()
            else:QTimer.singleShot(1000,inspect)
        def timeout():
            if not smoke_done[0]:
                smoke_done[0]=True;result[0]=1
                print('DESKTOP_SMOKE_TIMEOUT',page.errors,flush=True);view.close();app.quit()
        QTimer.singleShot(2000,inspect);QTimer.singleShot(60000,timeout)
    view.setUrl(QUrl('yunshan://desktop/game/'));view.show()
    app.exec()
    bridge.pool.shutdown(wait=True);bridge.asset_pool.shutdown(wait=True);handler.pool.shutdown(wait=True)
    # Destroy the page before its owning profile; Chromium can flush local storage.
    view.setPage(QWebEnginePage(view));page.deleteLater();app.processEvents()
    lock.unlock()
    return result[0]


def main():
    if '--smoke-test' not in sys.argv:return run()
    # Smoke tests use an isolated full-content save, never the player's progression.
    import tempfile
    from src.data.content_loader import load_current
    from src.application.danding import initial_slice
    from src.core.save.sqlite import SQLiteSave
    from src.core.time.clock import SystemClock
    from tools.playable.game import game_factory
    root=PROJECT/'.tmp';root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='desktop-',dir=root) as temporary:
        directory=Path(temporary);registry=load_current()
        clock=SystemClock();state=initial_slice(registry,last_settled_at_ms=clock.now_ms())
        path=directory/'game.sqlite3'
        with SQLiteSave.initialize(path,allowed_root=directory):pass
        factory=game_factory(path,directory,clock,registry=registry)
        with factory() as game:game.create(state)
        from unittest.mock import patch
        import socket
        with patch.object(socket.socket,'bind',side_effect=AssertionError('Desktop cannot bind a socket')):
            return run(DesktopSession(factory,state.save_id,directory),smoke=True)


if __name__=='__main__':
    try:sys.exit(main())
    except Exception:
        import traceback
        report=traceback.format_exc();log=PROJECT/'.game/desktop-error.log'
        log.parent.mkdir(exist_ok=True);log.write_text(report,encoding='utf-8')
        app=QApplication.instance() or QApplication(sys.argv[:1])
        QMessageBox.critical(None,'云山宗启动失败','请查看 .game/desktop-error.log 中的错误信息。')
        sys.exit(1)

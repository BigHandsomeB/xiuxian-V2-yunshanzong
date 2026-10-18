"""Windows source and frozen entry. No save is silently migrated or overwritten."""
import io,json,sys,traceback
from pathlib import Path


def run():
    from tools.playable.game import PROJECT
    if '--asset-manager' in sys.argv:
        from tools.asset_manager.desktop import main
        return main()
    if '--smoke-test' in sys.argv:
        from tools.playable.desktop import main
        return main()
    if '--verify-package' in sys.argv:
        from src.data.content_loader import load_current
        from src.data.artifacts.definitions import CONTENT_VERSION
        assert load_current().content_version==CONTENT_VERSION
        for name in ('src/ui/pages/game/index.html','tools/asset_manager/templates/index.html','assets/manifest.json'):
            assert (PROJECT/name).is_file(),name
        return 0
    if '--upgrade' in sys.argv:
        from PySide6.QtCore import QLockFile
        lock=QLockFile(str(PROJECT/'.game/desktop.lock'));lock.setStaleLockTime(0)
        if not lock.tryLock(0):raise RuntimeError('请先关闭游戏窗口，再执行存档升级。')
        try:
            from src.core.save.sqlite import SQLiteSave
            from src.data.artifacts.definitions import CONTENT_VERSION
            root=PROJECT/'.game';sid=(root/'save-id').read_text().strip()
            with SQLiteSave(root/'danding.sqlite3',allowed_root=root) as store:state=store.inspect(sid,include_recovery=False).current
            if state is None:raise RuntimeError('存档校验未通过，未执行升级。')
            if state.content_version!=CONTENT_VERSION:
                if state.time['pending']:raise RuntimeError('请先用原版本完成离线续算，再升级。')
                from tools.playable.combat_effect_upgrade import run as upgrade_skills
                from tools.playable.artifact_upgrade import run as upgrade_artifacts
                if state.content_version!='sect-skills-v2-6.3.0-r1':upgrade_skills(root,True)
                upgrade_artifacts(root,True)
            return 0
        finally:lock.unlock()
    root=PROJECT/'.game';database=root/'danding.sqlite3';pointer=root/'save-id'
    if not database.exists() and not pointer.exists():
        from tools.playable.setup_local import setup
        setup()
    if not database.is_file() or not pointer.is_file():raise RuntimeError('存档目录不完整，已保留原文件；请恢复备份，不能覆盖初始化。')
    from src.core.save.sqlite import SQLiteSave
    from src.data.artifacts.definitions import CONTENT_VERSION
    with SQLiteSave(database,allowed_root=root) as store:state=store.inspect(pointer.read_text().strip(),include_recovery=False).current
    if state is None:raise RuntimeError('存档校验未通过，未重置存档。')
    if state.content_version!=CONTENT_VERSION:raise RuntimeError('这是旧版本存档。请备份 .game 后运行「升级存档.cmd」，完成后再启动。')
    from tools.playable.desktop import main
    return main()


def main():
    # Windowed executables have no console streams; preserve diagnostics in a local log.
    if sys.stdout is None:sys.stdout=io.StringIO()
    if sys.stderr is None:sys.stderr=io.StringIO()
    try:return run()
    except Exception:
        from tools.playable.game import PROJECT
        log=PROJECT/'.game/windows-error.log';log.parent.mkdir(exist_ok=True);log.write_text(traceback.format_exc(),encoding='utf-8')
        if '--smoke-test' in sys.argv or '--verify-package' in sys.argv:raise
        from PySide6.QtWidgets import QApplication,QMessageBox
        app=QApplication.instance() or QApplication(sys.argv[:1])
        QMessageBox.critical(None,'云山宗',str(sys.exc_info()[1])+'\n详细信息：.game/windows-error.log')
        return 1


if __name__=='__main__':sys.exit(main())

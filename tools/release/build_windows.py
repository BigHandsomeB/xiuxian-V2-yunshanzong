"""Export public files, freeze a portable Windows app, verify it, and create release assets."""
import argparse,hashlib,json,os,shutil,subprocess,sys,zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
EXCLUDED={'.git','.game','.asset-manager','.venv','.tmp','__pycache__','node_modules','dist','build','.github'}
ROOT_FILES={'.gitignore','README.md','CHANGELOG.md','ROADMAP.md','LICENSE','启动云山宗.vbs','启动素材管理器.vbs','升级存档.cmd'}


def public_files(root=ROOT):
    for path in root.iterdir():
        if path.is_file() and (path.name in ROOT_FILES or path.name.startswith(('requirements','start-'))):yield path
    for name in ('src','tools','tests','docs','balance','assets'):
        for directory,dirs,files in os.walk(root/name):
            dirs[:]=[d for d in dirs if d not in EXCLUDED and not d.startswith('tmp')]
            for filename in files:
                path=Path(directory)/filename;relative=path.relative_to(root)
                if path.is_symlink():raise RuntimeError('Symlink cannot enter a release: '+str(relative))
                if filename.startswith('.env') or path.suffix.lower() in ('.pyc','.pyo','.sqlite','.sqlite3','.db','.log','.zip','.pem','.key'):continue
                if name=='assets':
                    parts=relative.parts
                    if len(parts)<2 or parts[1] not in ('runtime','templates','registry','manifest.json'):continue
                    if parts[1]=='registry' and filename not in ('asset-registry.json','published-catalog.json'):continue
                yield path


def archive_tree(directory,target,prefix):
    with zipfile.ZipFile(target,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for base,dirs,files in os.walk(directory):
            dirs[:]=[d for d in dirs if d not in EXCLUDED]
            for name in files:
                path=Path(base)/name;archive.write(path,prefix+'/'+path.relative_to(directory).as_posix())


def build(output,version):
    if os.name!='nt':raise RuntimeError('Windows releases must be built and tested on Windows')
    output=Path(output).resolve()
    if not output.is_relative_to(ROOT):raise RuntimeError('Build output must stay inside this checkout')
    if output.exists():raise RuntimeError('Use a new build output directory; existing artifacts are never deleted')
    public=output/'public';public.mkdir(parents=True)
    for source in public_files():
        target=public/source.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    # Exported source has no initialized game or maker history.
    assert not (public/'.game').exists() and not (public/'assets/registry/catalog.sqlite3').exists()
    command=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onedir','--windowed','--noupx',
             '--python-option','X utf8','--contents-directory','.','--name','YunshanZong','--distpath',str(output/'dist'),
             '--workpath',str(output/'work'),'--specpath',str(output/'spec'),'--paths',str(public),
             '--collect-submodules','src','--collect-submodules','tools.playable',
             '--collect-submodules','tools.asset_manager','--hidden-import','tools.desktop_window',
             '--hidden-import','tools.windows_desktop']
    for name in ('src','tools','assets'):command+=['--add-data',str(public/name)+os.pathsep+name]
    command.append(str(public/'tools/windows_desktop.py'))
    subprocess.run(command,cwd=public,check=True)
    return verify_and_archive(output,version)


def prepare_windows_runtime(app,output):
    # Windows 10/11 supply these OS contracts. A build host's PATH can contain
    # newer private copies from unrelated software; they must not shadow the OS.
    excluded=output/'excluded-system-dlls';excluded.mkdir(exist_ok=True)
    for dll in [*app.glob('api-ms-win-*.dll'),app/'ucrtbase.dll',app/'icuuc.dll',*app.glob('icudt*.dll')]:
        if dll.is_file():
            assert dll.resolve().is_relative_to(app.resolve())
            shutil.move(str(dll),str(excluded/dll.name))
    # Python and Qt can ship different compatible VC redistributable revisions.
    # Use Qt's newer copies consistently, rather than preloading Python's older one.
    for pattern in ('VCRUNTIME140*.dll','MSVCP140*.dll'):
        for dll in (app/'PySide6').glob(pattern):shutil.copy2(dll,app/dll.name)


def verify_and_archive(output,version):
    output=Path(output);public=output/'public'
    app=output/'dist/YunshanZong';exe=app/'YunshanZong.exe'
    prepare_windows_runtime(app,output)
    env={**os.environ,'QT_QPA_PLATFORM':'offscreen','QTWEBENGINE_CHROMIUM_FLAGS':'--disable-gpu','PYTHONUTF8':'1'}
    for args in (['--verify-package'],['--smoke-test'],['--asset-manager','--smoke-test']):
        subprocess.run([str(exe),*args],cwd=app,env=env,check=True,timeout=120)
    (app/'升级存档.cmd').write_text('@echo off\ncd /d "%~dp0"\n"YunshanZong.exe" --upgrade\nif errorlevel 1 (echo Upgrade failed.) else (echo Upgrade complete.)\npause\n',encoding='ascii')
    (app/'素材工坊.cmd').write_text('@echo off\ncd /d "%~dp0"\nstart "" "YunshanZong.exe" --asset-manager\n',encoding='ascii')
    for name in ('LICENSE','README.md'):shutil.copy2(public/name,app/name)
    (app/'开始游戏.txt').write_text('双击 YunshanZong.exe 启动。首次创建新档，进度保存在同目录 .game。\n升级时备份并保留原 .game；旧版本存档需先运行 升级存档.cmd。\n整个文件夹需要一起保留，不能只移动 EXE。\nWindows 10/11 x64；免安装 Python；不启动 HTTP 服务。\n',encoding='utf-8')
    assets=output/'release';assets.mkdir()
    archive_tree(app,assets/f'YunshanZong-{version}-Windows-x64.zip',f'YunshanZong-{version}-Windows-x64')
    archive_tree(public,assets/f'YunshanZong-{version}-Windows-source.zip',f'YunshanZong-{version}-Windows-source')
    sums=''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in sorted(assets.glob('*.zip')))
    (assets/'SHA256SUMS.txt').write_text(sums,encoding='ascii')
    print('WINDOWS_RELEASE_ASSETS',str(assets),flush=True)
    return assets


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);parser.add_argument('--version',default='v0.3.0');args=parser.parse_args()
    build(args.output,args.version)

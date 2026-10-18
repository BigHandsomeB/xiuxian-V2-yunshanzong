"""Editable planning descriptions, separate from gameplay and Asset Manager metadata."""
import json
import os
import sqlite3
import tempfile
from contextlib import closing, contextmanager
from pathlib import Path
from src.core.validation import ValidationError
from src.data.asset_notes import read_notes
from src.data.public_asset_catalog import read_catalog

@contextmanager
def exclusive_lock(guard):
    if os.name == 'nt':
        import msvcrt
        guard.seek(0)
        msvcrt.locking(guard.fileno(), msvcrt.LK_LOCK, 1)
        try:yield
        finally:
            guard.seek(0)
            msvcrt.locking(guard.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(guard, fcntl.LOCK_EX)
        try:yield
        finally:fcntl.flock(guard, fcntl.LOCK_UN)

class NotesConflict(Exception):
    def __init__(self,revision):self.revision=revision

class CatalogNotes:
    LIMITS={'grade':24,'function':240,'note':1000}
    def __init__(self,root,allowed_assets):
        self.root=Path(root).resolve();self.path=self.root/'registry/gameplay-notes.json';self.allowed_assets=allowed_assets
    def read(self):return read_notes(self.root)
    def name(self,identity):
        path=self.root/'registry/catalog.sqlite3'
        try:
            with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=.2)) as db:
                row=db.execute("SELECT json_extract(body,'$.name_zh') FROM metadata WHERE kind='asset' AND id=?",(identity,)).fetchone()
                if row and isinstance(row[0],str):return row[0]
        except sqlite3.Error:pass
        snapshot_path=self.root/'manifest.json'
        try:
            if snapshot_path.is_symlink() or snapshot_path.stat().st_size>2*1024*1024:return identity
            snapshot=json.loads(snapshot_path.read_text())['assets']
            for group in read_catalog(self.root,snapshot)['groups']:
                for item in group['items']:
                    if item['asset_id']==identity:return item['name']
        except (OSError,ValueError,KeyError,TypeError):pass
        return identity
    def write(self,payload):
        if not isinstance(payload,dict) or set(payload)!={'asset_id','expected_revision',*self.LIMITS}:raise ValidationError('请提交品阶、功能和备注')
        identity=payload['asset_id'];expected=payload['expected_revision']
        if type(identity) is not str or identity not in self.allowed_assets():raise ValidationError('素材不存在或尚未发布')
        if type(expected) is not int or expected<0:raise ValidationError('说明版本无效，请重新加载图鉴')
        fields={}
        for key,limit in self.LIMITS.items():
            if type(payload[key]) is not str or len(payload[key])>limit:raise ValidationError(f'{key}内容超过长度限制')
            fields[key]=payload[key].strip()
        if self.path.is_symlink() or self.path.parent.is_symlink():raise ValidationError('图鉴说明文件不可用')
        lock=self.path.with_suffix('.lock')
        if lock.is_symlink():raise ValidationError('图鉴说明锁文件不可用')
        fd=os.open(lock,os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600)
        with os.fdopen(fd,'r+') as guard, exclusive_lock(guard):
            data=self.read();old=data['assets'].get(identity,{});revision=old.get('revision',0)
            if all(old.get(k,'')==v for k,v in fields.items()) and old:return old
            if revision!=expected:raise NotesConflict(revision)
            row={'name':self.name(identity),**fields,'revision':revision+1};data['assets'][identity]=row
            text=json.dumps(data,ensure_ascii=False,indent=2)+'\n'
            if len(text.encode())>2*1024*1024:raise ValidationError('图鉴说明总量超过限制')
            name=None
            try:
                with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=self.path.parent,prefix='.notes-',delete=False) as output:
                    name=output.name;output.write(text);output.flush();os.fsync(output.fileno())
                os.replace(name,self.path)
            finally:
                if name and os.path.exists(name):os.unlink(name)
            return row


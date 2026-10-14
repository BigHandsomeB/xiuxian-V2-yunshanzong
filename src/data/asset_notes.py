"""Read-only planning annotations shared by presentation and the editor."""
import json
from pathlib import Path
from src.core.validation import ValidationError

def read_notes(root):
    path=Path(root)/'registry/gameplay-notes.json'
    if not path.exists():return {'schema_version':1,'assets':{}}
    if path.is_symlink() or path.parent.is_symlink() or path.stat().st_size>2*1024*1024:raise ValidationError('图鉴说明文件不可用')
    try:data=json.loads(path.read_text())
    except (OSError,ValueError) as e:raise ValidationError('图鉴说明读取失败') from e
    if not isinstance(data,dict) or set(data)!={'schema_version','assets'} or data['schema_version']!=1 or not isinstance(data['assets'],dict):raise ValidationError('图鉴说明格式不正确')
    for key,row in data['assets'].items():
        if not isinstance(key,str) or not isinstance(row,dict) or type(row.get('revision')) is not int or row['revision']<0 or any(type(row.get(f,'')) is not str for f in ('name','grade','function','note')):raise ValidationError('素材说明格式不正确')
    return data

"""Presentation-only concepts referencing the sole Asset Registry, never item definitions."""
import json
import re
from functools import lru_cache
from pathlib import Path
PATH=Path(__file__).with_name('asset-concepts.json')

@lru_cache(maxsize=2)
def _read(stamp):
    doc=json.loads(PATH.read_text())
    if doc.get('schema_version')!=1 or not isinstance(doc.get('concepts'),list):raise ValueError('invalid concepts')
    seen=set()
    for row in doc['concepts']:
        key=row['concept_id']
        if not isinstance(key,str) or not re.fullmatch(r'concept\.[a-z][a-z0-9_]*',key) or key in seen:raise ValueError('duplicate concept')
        seen.add(key)
        if not isinstance(row.get('category'),list) or not row['category']:raise ValueError('missing categories')
        if row.get('gameplay_status') not in ('ACTIVE_GAMEPLAY','ASSET_ONLY','NEEDS_CONFIRMATION','BLOCKED'):raise ValueError('invalid status')
        for aid in [row['asset_id'],*row.get('alternate_asset_ids',[])]:
            if not isinstance(aid,str) or not re.fullmatch(r'[a-z][a-z0-9_.]*',aid):raise ValueError('invalid asset')
    return doc['concepts']

def concepts():
    try:
        stat=PATH.stat()
        if PATH.is_symlink() or stat.st_size>128*1024:return []
        # Public projection callers detach rows before modification.
        return _read((stat.st_mtime_ns,stat.st_size))
    except (OSError,ValueError,KeyError,TypeError):return []

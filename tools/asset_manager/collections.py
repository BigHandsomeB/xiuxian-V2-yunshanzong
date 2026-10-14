"""Generic organization containers; stable assets/sets and generation history stay intact."""
import json
from .model import require,identifier
from .sets import suggested_id,available_id
from .catalog import now

def require_collection(catalog,collection_id,conn=None):
    if collection_id is not None:
        identifier(collection_id);catalog.get('collection',collection_id,conn)
    return collection_id

def create(catalog,name_zh):
    require(isinstance(name_zh,str) and 0<len(name_zh.strip())<=160,'请填写集合名称')
    with catalog.transaction() as conn:
        occupied={r[0] for r in conn.execute("SELECT id FROM metadata WHERE kind='collection'")}
        key=available_id(suggested_id('asset_collection',name_zh.strip()),occupied)
        value=dict(collection_id=key,name_zh=name_zh.strip(),created_at=now())
        catalog.put('collection',key,value,conn,True)
    return value

def rename(catalog,collection_id,name_zh):
    require(isinstance(name_zh,str) and 0<len(name_zh.strip())<=160,'请填写集合名称')
    with catalog.transaction() as conn:
        value=catalog.get('collection',identifier(collection_id),conn);value['name_zh']=name_zh.strip()
        catalog.put('collection',collection_id,value,conn)
    return value

def assign(catalog,kind,key,collection_id=None):
    require(kind in ('asset','set'),'仅可归类独立素材或制作组')
    with catalog.transaction() as conn:
        require_collection(catalog,collection_id,conn)
        row=catalog.get(kind,identifier(key),conn)
        require(kind!='asset' or not row.get('set_id'),'组内素材请通过制作组统一归类')
        if collection_id is None:row.pop('collection_id',None)
        else:row['collection_id']=collection_id
        catalog.put(kind,key,row,conn)
    return row

def remove_empty(catalog,collection_id):
    with catalog.transaction() as conn:
        key=identifier(collection_id);catalog.get('collection',key,conn)
        for kind in ('set','asset'):
            rows=conn.execute('SELECT body FROM metadata WHERE kind=?',(kind,))
            require(not any(json.loads(r[0]).get('collection_id')==key for r in rows),'集合非空，请先移出制作组或素材')
        conn.execute("DELETE FROM metadata WHERE kind='collection' AND id=?",(key,))
    return dict(collection_id=key,removed=True)

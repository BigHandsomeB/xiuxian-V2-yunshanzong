"""Canonical JSON fragments cached only on owned immutable partitions.
Full snapshot JSON and SHA share a weak, bounded identity cache; no mutable drafts.
Wire bytes match the existing sort_keys/ASCII/compact JSON contract exactly.
"""
import hashlib,json,weakref
from collections import OrderedDict
from collections.abc import Mapping
from src.core.state.envelope import _FrozenObject,freeze_json
from src.core.state.draft import enabled

_snapshots=OrderedDict()
_LIMIT=8

def canonical_json(value):
    frozen=freeze_json(value)
    def encode(v):
        if type(v) is _FrozenObject:
            cached=v._json_cache
            if cached is None:
                cached='{'+','.join(json.dumps(k,ensure_ascii=True)+':'+encode(v[k]) for k in sorted(v))+'}'
                object.__setattr__(v,'_json_cache',cached)
            return cached
        if isinstance(v,Mapping):return '{'+','.join(json.dumps(k,ensure_ascii=True)+':'+encode(v[k]) for k in sorted(v))+'}'
        if type(v) is tuple:return '['+','.join(encode(item) for item in v)+']'
        return json.dumps(v,ensure_ascii=True,allow_nan=False,separators=(',',':'))
    return encode(frozen)

def snapshot(state):
    if enabled():raise ValueError('mutable batch snapshots cannot be serialized')
    key=id(state);entry=_snapshots.get(key)
    if entry and entry[0]() is state:
        _snapshots.move_to_end(key);return entry[1],entry[2]
    body=canonical_json({name:getattr(state,name) for name in state.__dataclass_fields__})
    digest=hashlib.sha256(body.encode('utf-8')).hexdigest()
    def release(ref):
        current=_snapshots.get(key)
        if current and current[0] is ref:_snapshots.pop(key,None)
    _snapshots[key]=(weakref.ref(state,release),body,digest)
    while len(_snapshots)>_LIMIT:_snapshots.popitem(last=False)
    return body,digest

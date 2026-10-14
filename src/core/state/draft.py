"""Request-scoped copy-on-write JSON snapshots; never persisted or shared as mutable state.
A batch detaches the input once. Existing pure handlers get cheap writable branches;
sealing those branches preserves their historical snapshot/exception semantics.
"""
from collections.abc import Mapping
from contextvars import ContextVar
from contextlib import contextmanager
from types import MappingProxyType

_active=ContextVar('settlement_draft',default=False)

class DraftObject(Mapping):
    __slots__=('_values',)
    def __init__(self,values):object.__setattr__(self,'_values',MappingProxyType(values))
    def __setattr__(self,*args):raise TypeError('draft snapshots are read only')
    def __getitem__(self,key):return self._values[key]
    def __iter__(self):return iter(self._values)
    def __len__(self):return len(self._values)
    def items(self):return self._values.items()
    def values(self):return self._values.values()
    def __eq__(self,other):return self._values==dict(other) if isinstance(other,Mapping) else NotImplemented

class Branch(dict):
    """Only touched children become writable. seal detaches them before publication."""
    def __init__(self,source):super().__init__(source)
    def __getitem__(self,key):
        value=super().__getitem__(key)
        if isinstance(value,Mapping) and not isinstance(value,Branch):
            value=Branch(value);super().__setitem__(key,value)
        elif type(value) is tuple:
            value=BranchList(value);super().__setitem__(key,value)
        return value
    def items(self):
        for key in list(dict.keys(self)):yield key,self[key]
    def values(self):
        for key in list(dict.keys(self)):yield self[key]
    def get(self,key,default=None):return self[key] if key in self else default
    def setdefault(self,key,default=None):
        if key not in self:self[key]=default
        return self[key]

class BranchList(list):
    def __getitem__(self,key):
        value=super().__getitem__(key)
        if isinstance(key,slice):return value
        if isinstance(value,Mapping) and not isinstance(value,Branch):
            value=Branch(value);super().__setitem__(key,value)
        elif type(value) is tuple:
            value=BranchList(value);super().__setitem__(key,value)
        return value
    def __iter__(self):
        for i in range(len(self)):yield self[i]

def enabled():return _active.get()

def writable(value):
    if isinstance(value,Mapping):return Branch(value)
    if type(value) is tuple:return BranchList(value)
    # Newly created plain containers retain the original detach semantics.
    return None

@contextmanager
def batch_scope():
    token=_active.set(True)
    try:yield
    finally:_active.reset(token)

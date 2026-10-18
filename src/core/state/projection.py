"""Reuse successful checks of owned immutable partitions during one read projection.
No cache exists while loading or writing saves, and mutable candidates always validate.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from .envelope import _FrozenObject

_checks=ContextVar('projection_checks',default=None)


@contextmanager
def projection_checks():
    token=_checks.set({})
    try:yield
    finally:_checks.reset(token)


def checked_partition(validate):
    @wraps(validate)
    def checked(partition,registry,**options):
        cache=_checks.get()
        if cache is None or type(partition) is not _FrozenObject or not registry.is_sealed:
            return validate(partition,registry,**options)
        key=(validate,id(partition),id(registry),tuple(sorted(options.items())))
        previous=cache.get(key)
        if previous is not None:return previous[2]
        result=validate(partition,registry,**options)
        # Retained inputs prevent object identity reuse within this short scope.
        if len(cache)<512:cache[key]=(partition,registry,result)
        return result
    return checked

"""Test-only baseline: settlement loop and cloning captured before performance changes.
Not a runtime fallback or a second gameplay implementation.
"""
from dataclasses import replace
from time import monotonic
from collections.abc import Mapping
from types import MappingProxyType
import math
from src.core.validation import ValidationError,integer
from src.core.time.world import require_running
from src.core.time.model import Continuation
from src.core.state.envelope import thaw_json
from src.application import equipment as equip

def legacy_advance(self,state,*,max_events,now_ms=None,continuation=None):
        require_running(state.time);self.validate_state(state)
        # Validate caller continuation BEFORE adding new Domain work.
        if state.time['pending']:
            self.core._pending(state,continuation)
        elif continuation is not None:raise ValidationError('unexpected continuation')
        prepared=self.app.prepare_economy_state(state) if not state.time['pending'] else state
        s=self.wake(self.dispatch(equip.automate(self.deliver(prepared),self.registry)));processed=[];result=None;started=monotonic()
        for _ in range(min(max_events,32)):
            c=Continuation.for_state(s) if s.time['pending'] else None
            candidate,result=self.core.advance(s,max_events=1,now_ms=now_ms if c is None else None,continuation=c)
            processed.extend(result.processed_events);s=self.wake(self.dispatch(equip.automate(self.deliver(candidate),self.registry)))
            if result.status=='COMPLETE' or len(processed)>=max_events or monotonic()-started>=.025:break
        s=replace(s,revision=state.revision+1 if s!=state else state.revision)
        if s.time['pending']:
            t=thaw_json(s.time);t['pending']['revision']=s.revision;s=replace(s,time=t)
        self.validate_state(s)
        result=replace(result,from_sim_ms=state.time['sim_time_ms'],processed_events=tuple(processed),continuation=Continuation.for_state(s) if s.time['pending'] else None)
        return s,result


def legacy_freeze_json(value):
    """Detach caller containers; reject cycles/non-JSON/invalid numbers."""
    def freeze(item, active):
        if item is None or type(item) in (str, bool, int):
            return item
        if type(item) is float and math.isfinite(item):
            return item
        if isinstance(item, Mapping) or type(item) in (list, tuple):
            if id(item) in active:
                raise ValidationError('cyclic containers are not JSON values')
            active.add(id(item))
            try:
                if isinstance(item, Mapping):
                    if any(type(key) is not str for key in item):
                        raise ValidationError('JSON object keys must be strings')
                    return MappingProxyType({key: freeze(part, active) for key, part in item.items()})
                return tuple(freeze(part, active) for part in item)
            finally:
                active.remove(id(item))
        raise ValidationError('state/payload must contain only finite JSON values')
    return freeze(value, set())

def legacy_thaw_json(value):
    """Explicit detached conversion, never used for a read-only query."""
    if isinstance(value, Mapping):
        return {key: legacy_thaw_json(item) for key, item in value.items()}
    if type(value) is tuple:
        return [legacy_thaw_json(item) for item in value]
    return value


def timed_advance(self,state,*,max_events,now_ms=None,continuation=None):
        integer(max_events,'max_events',1)
        started=monotonic()
        require_running(state.time);self.validate_state(state)
        # Validate caller continuation BEFORE adding new Domain work.
        if state.time['pending']:
            self.core._pending(state,continuation)
        elif continuation is not None:raise ValidationError('unexpected continuation')
        prepared=self.app.prepare_economy_state(state) if not state.time['pending'] else state
        s=self.wake(self.dispatch(equip.automate(self.deliver(prepared),self.registry)));processed=[];result=None
        for _ in range(max_events):
            c=Continuation.for_state(s) if s.time['pending'] else None
            candidate,result=self.core.advance(s,max_events=1,now_ms=now_ms if c is None else None,continuation=c)
            processed.extend(result.processed_events);s=self.wake(self.dispatch(equip.automate(self.deliver(candidate),self.registry)))
            if result.status=='COMPLETE' or len(processed)>=max_events or monotonic()-started>=self.budget_ms/1000:break
        s=replace(s,revision=state.revision+1 if s!=state else state.revision)
        if s.time['pending']:
            t=thaw_json(s.time);t['pending']['revision']=s.revision;s=replace(s,time=t)
        self.validate_state(s)
        result=replace(result,from_sim_ms=state.time['sim_time_ms'],processed_events=tuple(processed),continuation=Continuation.for_state(s) if s.time['pending'] else None)
        return s,result

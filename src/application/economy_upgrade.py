"""Explicit compatible content upgrade; no automatic GET, resource supply or reset."""
from dataclasses import replace
from src.application.world import WorldApplication
from src.application.economy import EconomyApplication
from src.application.memory import Command,Receipt
from src.data.cultivation.definitions import load_cultivation
from src.data.economy.definitions import load_economy
from src.systems.economy import policy
from src.systems.equipment import items
from src.core.save.codec import StoredReceipt
from src.core.state.envelope import thaw_json
from src.core.validation import ValidationError,ConflictError

def upgrade(store,clock,q):
    if not isinstance(q,Command) or q.name!='economy_content_upgrade' or q.version!=1 or q.payload:raise ValidationError('exact trusted economy upgrade required')
    old=load_cultivation();new=load_economy()
    with store.transaction():
        observed=store.inspect(q.save_id,include_recovery=False)
        if observed.status!='CURRENT_VALID':raise ValidationError('valid existing save required')
        s=observed.current
        if q.generation!=s.generation:raise ConflictError('generation changed')
        r=store.receipt(s.save_id,s.generation,q.request_id)
        if r:
            if r.kind!='command' or r.intent!=q.digest():raise ConflictError('upgrade intent changed')
            return Receipt(r.request_id,r.committed_revision,r.payload)
        if s.content_version==new.content_version:
            EconomyApplication(store,new,clock).foundation.validate_state(s)
            return Receipt(q.request_id,s.revision,{'status':'ALREADY_UPGRADED','content_version':s.content_version})
        if q.expected_revision!=s.revision or s.time['pending'] is not None:raise ConflictError('completed current revision required')
        if s.content_version!=old.content_version or set(s.domains)-{'inventory','sect','production','disciples','combat','cultivation'}:raise ValidationError('only declared Phase15/Framework compatibility allowed')
        WorldApplication(store,old,clock).foundation.validate_state(s)
        candidate=replace(s,content_version=new.content_version,revision=s.revision+1,domains={**s.domains,'equipment':items.initial(),'automation':policy.initial()})
        EconomyApplication(store,new,clock).foundation.validate_state(candidate)
        if s.time!=candidate.time or s.identity!=candidate.identity or any(candidate.domains[k]!=v for k,v in s.domains.items()):raise ValidationError('upgrade must preserve all existing authority')
        receipt=Receipt(q.request_id,candidate.revision,{'status':'UPGRADED','from_content_version':s.content_version,'content_version':candidate.content_version})
        store.checkpoint(s.save_id);store.commit(s,candidate,StoredReceipt(s.save_id,s.generation,q.request_id,q.digest(),candidate.revision,'command',thaw_json(receipt.result)));store.checkpoint(s.save_id)
    return receipt

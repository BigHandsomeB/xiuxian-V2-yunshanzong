"""Explicit Phase14→15 compatible application transaction, not a GET/startup hook."""
from dataclasses import replace
from src.application.game import GameApplication
from src.application.cultivation import CultivationApplication
from src.application.memory import Command,Receipt
from src.data.combat.definitions import load_combat
from src.data.cultivation.definitions import load_cultivation
from src.core.save.codec import StoredReceipt
from src.core.state.envelope import thaw_json
from src.core.validation import ValidationError,ConflictError

def upgrade(store,clock,q):
    if not isinstance(q,Command) or q.name!='cultivation_content_upgrade' or q.version!=1 or q.payload:raise ValidationError('exact trusted growth upgrade required')
    old=load_combat();new=load_cultivation()
    with store.transaction():
        observed=store.inspect(q.save_id,include_recovery=False)
        if observed.status!='CURRENT_VALID':raise ValidationError('valid existing save required')
        s=observed.current
        if q.generation!=s.generation:raise ConflictError('upgrade generation changed')
        r=store.receipt(s.save_id,s.generation,q.request_id)
        if r:
            if r.kind!='command' or r.intent!=q.digest():raise ConflictError('upgrade intent changed')
            return Receipt(r.request_id,r.committed_revision,r.payload)
        if s.content_version==new.content_version:
            CultivationApplication(store,new,clock).foundation.validate_state(s)
            return Receipt(q.request_id,s.revision,{'status':'ALREADY_UPGRADED','content_version':s.content_version})
        if q.expected_revision!=s.revision or s.time['pending'] is not None:raise ConflictError('current completed-settlement revision required')
        if s.content_version!=old.content_version or set(s.domains)-{'inventory','sect','production','disciples','combat'}:raise ValidationError('only declared Phase14 compatibility allowed')
        GameApplication(store,old,clock).foundation.validate_state(s)
        candidate=replace(s,content_version=new.content_version,revision=s.revision+1)
        CultivationApplication(store,new,clock).foundation.validate_state(candidate)
        receipt=Receipt(q.request_id,candidate.revision,{'status':'UPGRADED','from_content_version':s.content_version,'content_version':candidate.content_version})
        store.checkpoint(s.save_id);store.commit(s,candidate,StoredReceipt(s.save_id,s.generation,q.request_id,q.digest(),candidate.revision,'command',thaw_json(receipt.result)))
    return receipt

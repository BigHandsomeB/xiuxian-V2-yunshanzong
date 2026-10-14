"""Explicit additive v1 loot upgrade; preserves clock, stock, battles and IDs."""
from dataclasses import replace
from src.application.memory import Command,Receipt
from src.application.dungeons import DungeonApplication
from src.data.dungeons.definitions import load_dungeons
from src.core.save.codec import StoredReceipt
from src.core.state.envelope import thaw_json
from src.core.validation import ValidationError,ConflictError

def upgrade(store,clock,q):
    if not isinstance(q,Command) or q.name!='dungeon_loot_upgrade' or q.version!=1 or q.payload:raise ValidationError('exact trusted loot upgrade required')
    old=load_dungeons(legacy=True);new=load_dungeons()
    with store.transaction():
        observed=store.inspect(q.save_id,include_recovery=False)
        if observed.status!='CURRENT_VALID':raise ValidationError('valid current save required')
        s=observed.current
        previous=store.receipt(s.save_id,s.generation,q.request_id)
        if previous:
            if previous.kind!='command' or previous.intent!=q.digest():raise ConflictError('upgrade request changed')
            return Receipt(previous.request_id,previous.committed_revision,previous.payload)
        if q.generation!=s.generation:raise ConflictError('generation changed')
        if s.content_version==new.content_version:
            DungeonApplication(store,new,clock).foundation.validate_state(s)
            return Receipt(q.request_id,s.revision,{'status':'ALREADY_UPGRADED'})
        if s.content_version!=old.content_version or q.expected_revision!=s.revision or s.time['pending']:raise ConflictError('current settled dungeon revision required')
        DungeonApplication(store,old,clock).foundation.validate_state(s)
        candidate=replace(s,content_version=new.content_version,revision=s.revision+1)
        DungeonApplication(store,new,clock).foundation.validate_state(candidate)
        if s.time!=candidate.time or s.identity!=candidate.identity or s.domains!=candidate.domains:raise ValidationError('loot upgrade must preserve existing authority')
        receipt=Receipt(q.request_id,candidate.revision,{'status':'UPGRADED','content_version':new.content_version})
        store.checkpoint(s.save_id)
        store.commit(s,candidate,StoredReceipt(s.save_id,s.generation,q.request_id,q.digest(),candidate.revision,'command',thaw_json(receipt.result)))
        store.checkpoint(s.save_id)
    return receipt

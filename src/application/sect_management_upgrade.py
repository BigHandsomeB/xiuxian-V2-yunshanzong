"""Explicit checkpointed content upgrade: preserve every saved partition and clock."""
from dataclasses import replace
from src.application.memory import Command,Receipt
from src.application.dungeons import DungeonApplication
from src.application.sect_management import ManagementApplication
from src.systems.sect import management
from src.data.dungeons.definitions import load_dungeons
from src.core.save.codec import StoredReceipt
from src.core.state.envelope import thaw_json
from src.core.validation import ValidationError,ConflictError

def upgrade(store,clock,q):
    if not isinstance(q,Command) or q.name!='sect_management_content_upgrade' or q.version!=1 or q.payload:raise ValidationError('exact trusted sect management upgrade required')
    old=load_dungeons();new=load_dungeons(management=True)
    with store.transaction():
        observation=store.inspect(q.save_id,include_recovery=False)
        if observation.status!='CURRENT_VALID':raise ValidationError('valid current save required')
        s=observation.current
        if q.generation!=s.generation:raise ConflictError('generation changed')
        previous=store.receipt(s.save_id,s.generation,q.request_id)
        if previous:
            if previous.kind!='command' or previous.intent!=q.digest():raise ConflictError('upgrade request changed')
            return Receipt(previous.request_id,previous.committed_revision,previous.payload)
        if s.content_version==new.content_version:
            ManagementApplication(store,new,clock).foundation.validate_state(s)
            return Receipt(q.request_id,s.revision,{'status':'ALREADY_UPGRADED'})
        if s.content_version!=old.content_version or q.expected_revision!=s.revision:raise ConflictError('current declared expedition revision required')
        DungeonApplication(store,old,clock).foundation.validate_state(s)
        time=thaw_json(s.time)
        if time['pending'] is not None:time['pending']['revision']=s.revision+1
        candidate=replace(s,content_version=new.content_version,revision=s.revision+1,time=time,domains={**s.domains,'sect_management':management.initial(new)})
        ManagementApplication(store,new,clock).foundation.validate_state(candidate)
        preserved=thaw_json(candidate.time)
        if preserved['pending'] is not None:preserved['pending']['revision']=s.time['pending']['revision']
        if {k:v for k,v in candidate.domains.items() if k!='sect_management'}!=dict(s.domains) or candidate.identity!=s.identity or preserved!=thaw_json(s.time):raise ValidationError('management upgrade must preserve existing authority')
        receipt=Receipt(q.request_id,candidate.revision,{'status':'UPGRADED','content_version':new.content_version})
        store.checkpoint(s.save_id)
        store.commit(s,candidate,StoredReceipt(s.save_id,s.generation,q.request_id,q.digest(),candidate.revision,'command',thaw_json(receipt.result)))
        store.checkpoint(s.save_id)
    return receipt

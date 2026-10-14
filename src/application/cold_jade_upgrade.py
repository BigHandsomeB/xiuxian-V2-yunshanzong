"""Explicit additive fourth-dungeon upgrade; all saved authority stays intact."""
from dataclasses import replace
from src.application.memory import Command,Receipt
from src.application.dungeons import DungeonApplication
from src.application.sect_management import ManagementApplication
from src.data.dungeons.definitions import load_dungeons,VERSION,MANAGEMENT_VERSION,COLD_JADE_VERSION,COLD_JADE_MANAGEMENT_VERSION
from src.core.save.codec import StoredReceipt
from src.core.state.envelope import thaw_json
from src.core.validation import ValidationError,ConflictError

def upgrade(store,clock,q):
    if not isinstance(q,Command) or q.name!='cold_jade_content_upgrade' or q.version!=1 or q.payload:raise ValidationError('exact trusted cold jade upgrade required')
    with store.transaction():
        observation=store.inspect(q.save_id,include_recovery=False)
        if observation.status!='CURRENT_VALID':raise ValidationError('valid current save required')
        s=observation.current
        if q.generation!=s.generation:raise ConflictError('generation changed')
        previous=store.receipt(s.save_id,s.generation,q.request_id)
        if previous:
            if previous.kind!='command' or previous.intent!=q.digest():raise ConflictError('upgrade request changed')
            return Receipt(previous.request_id,previous.committed_revision,previous.payload)
        if s.content_version not in (VERSION,MANAGEMENT_VERSION,COLD_JADE_VERSION,COLD_JADE_MANAGEMENT_VERSION):raise ConflictError('current expedition or management content required')
        management=s.content_version in (MANAGEMENT_VERSION,COLD_JADE_MANAGEMENT_VERSION)
        application=ManagementApplication if management else DungeonApplication
        old=load_dungeons(management=management);new=load_dungeons(management=management,cold_jade=True)
        if s.content_version==new.content_version:
            application(store,new,clock).foundation.validate_state(s)
            return Receipt(q.request_id,s.revision,{'status':'ALREADY_UPGRADED'})
        if q.expected_revision!=s.revision:raise ConflictError('current declared revision required')
        application(store,old,clock).foundation.validate_state(s)
        time=thaw_json(s.time)
        if time['pending'] is not None:time['pending']['revision']=s.revision+1
        candidate=replace(s,content_version=new.content_version,revision=s.revision+1,time=time)
        application(store,new,clock).foundation.validate_state(candidate)
        preserved=thaw_json(candidate.time)
        if preserved['pending'] is not None:preserved['pending']['revision']=s.time['pending']['revision']
        if candidate.domains!=s.domains or candidate.identity!=s.identity or preserved!=thaw_json(s.time):raise ValidationError('cold jade upgrade must preserve existing authority')
        receipt=Receipt(q.request_id,candidate.revision,{'status':'UPGRADED','content_version':new.content_version})
        store.checkpoint(s.save_id)
        store.commit(s,candidate,StoredReceipt(s.save_id,s.generation,q.request_id,q.digest(),candidate.revision,'command',thaw_json(receipt.result)))
        store.checkpoint(s.save_id)
    return receipt

"""Explicit artifact content upgrade; GET/startup never migrates a player save."""
from dataclasses import replace
from src.application.ecology import EcologyApplication
from src.application.memory import Command, Receipt
from src.core.save.codec import StoredReceipt
from src.core.state.envelope import thaw_json
from src.core.validation import ValidationError, ConflictError
from src.data.content_loader import load_current
from src.data.dungeons.definitions import load_dungeons
from src.data.combat.skill_timing import CONTENT_VERSION as SOURCE_VERSION
from src.data.artifacts.definitions import CONTENT_VERSION
from src.systems.artifacts.artifacts import initial


def upgrade(store, clock, request):
    if not isinstance(request,Command) or request.name!='artifact_content_upgrade' or request.version!=1 or request.payload:
        raise ValidationError('exact trusted artifact upgrade required')
    target=load_current()
    with store.transaction():
        observation=store.inspect(request.save_id,include_recovery=False)
        if observation.status!='CURRENT_VALID':raise ValidationError('valid current save required')
        state=observation.current
        if request.generation!=state.generation:raise ConflictError('存档已换代')
        previous=store.receipt(state.save_id,state.generation,request.request_id)
        if previous:
            if previous.kind!='command' or previous.intent!=request.digest() or previous.committed_revision>state.revision:raise ConflictError('迁移请求内容不一致')
            return Receipt(previous.request_id,previous.committed_revision,previous.payload)
        if request.expected_revision!=state.revision:raise ConflictError('存档版本已变化')
        if state.content_version==CONTENT_VERSION:
            EcologyApplication(store,target,clock).foundation.validate_state(state)
            return Receipt(request.request_id,state.revision,{'status':'ALREADY_UPGRADED'})
        if state.content_version!=SOURCE_VERSION:raise ConflictError('请先使用对应版本工具升级到法宝前置内容版本')
        if state.time['pending']:raise ConflictError('请先使用旧版本完成离线续算')
        old=load_dungeons(management=True,cold_jade=True,ecology=True,mechanics=True,skill_timing=True)
        EcologyApplication(store,old,clock).foundation.validate_state(state)
        if 'artifacts' in state.domains:raise ValidationError('unexpected artifact partition in legacy save')
        candidate=replace(state,content_version=CONTENT_VERSION,revision=state.revision+1,domains={**state.domains,'artifacts':initial()})
        EcologyApplication(store,target,clock).foundation.validate_state(candidate)
        if any(candidate.domains[k]!=v for k,v in state.domains.items()) or candidate.time!=state.time or candidate.identity!=state.identity:
            raise ValidationError('artifact upgrade must preserve all original facts')
        receipt=Receipt(request.request_id,candidate.revision,{'status':'UPGRADED','content_version':CONTENT_VERSION})
        store.checkpoint(state.save_id)
        store.commit(state,candidate,StoredReceipt(state.save_id,state.generation,request.request_id,request.digest(),candidate.revision,'command',thaw_json(receipt.result)))
        store.checkpoint(state.save_id)
        return receipt

"""Explicit, receipt-protected content upgrade; never invoked by GET or startup."""
from dataclasses import replace
from src.application.ecology import EcologyApplication
from src.application.memory import Command,Receipt
from src.core.save.codec import StoredReceipt
from src.core.state.envelope import thaw_json
from src.core.validation import ValidationError,ConflictError
from src.data.content_loader import load_current
from src.data.dungeons.definitions import load_dungeons
from src.data.economy.ecology import VERSION as SOURCE_VERSION
from src.data.combat.mechanics import CONTENT_VERSION

def upgrade(store,clock,request):
    if not isinstance(request,Command) or request.name!='combat_effect_content_upgrade' or request.version!=1 or request.payload:
        raise ValidationError('exact trusted combat effect upgrade required')
    target=load_current()
    with store.transaction():
        observation=store.inspect(request.save_id,include_recovery=False)
        if observation.status!='CURRENT_VALID':raise ValidationError('valid current save required')
        state=observation.current
        if request.generation!=state.generation:raise ConflictError('存档已换代')
        prior=store.receipt(state.save_id,state.generation,request.request_id)
        if prior:
            if prior.kind!='command' or prior.intent!=request.digest():raise ConflictError('迁移请求内容不一致')
            return Receipt(prior.request_id,prior.committed_revision,prior.payload)
        if request.expected_revision!=state.revision:raise ConflictError('存档版本已变化')
        if state.content_version==CONTENT_VERSION:
            EcologyApplication(store,target,clock).foundation.validate_state(state)
            return Receipt(request.request_id,state.revision,{'status':'ALREADY_UPGRADED'})
        if state.content_version!=SOURCE_VERSION:raise ConflictError('需要当前四副本与150正式功法版本')
        if state.time['pending']:raise ConflictError('请先使用旧版本完成离线续算')
        old=load_dungeons(management=True,cold_jade=True,ecology=True)
        EcologyApplication(store,old,clock).foundation.validate_state(state)
        candidate=replace(state,content_version=CONTENT_VERSION,revision=state.revision+1)
        EcologyApplication(store,target,clock).foundation.validate_state(candidate)
        # No grants, rerolls, clock changes, battle substitutions or policy resets.
        if candidate.domains!=state.domains or candidate.time!=state.time or candidate.identity!=state.identity:
            raise ValidationError('content upgrade must preserve all saved gameplay facts')
        receipt=Receipt(request.request_id,candidate.revision,{'status':'UPGRADED','content_version':CONTENT_VERSION,
            'existing_equipment':'PRESERVED','active_battle':'PRESERVED','new_battles':'five-dungeons-effects-v1'})
        store.checkpoint(state.save_id)
        store.commit(state,candidate,StoredReceipt(state.save_id,state.generation,request.request_id,request.digest(),candidate.revision,'command',thaw_json(receipt.result)))
        store.checkpoint(state.save_id)
        return receipt

"""Explicit compatible content-version upgrade, never invoked by GET or service startup."""
from dataclasses import replace
from src.application.danding import DandingApplication
from src.application.game import GameApplication
from src.application.memory import Command, Receipt
from src.core.save.codec import StoredReceipt
from src.core.state.envelope import thaw_json
from src.core.validation import ValidationError, ConflictError
from src.data.recipes.alchemy import load_alchemy
from src.data.combat.definitions import load_combat


def upgrade(store,clock,request):
    if not isinstance(request,Command) or request.name!='game_content_upgrade' or request.version!=1 or request.payload:raise ValidationError('exact trusted content upgrade intent required')
    old_registry=load_alchemy();new_registry=load_combat()
    with store.transaction():
        observed=store.inspect(request.save_id,include_recovery=False)
        if observed.status!='CURRENT_VALID':raise ValidationError('upgrade requires a valid existing save')
        state=observed.current
        if request.generation!=state.generation:raise ConflictError('upgrade generation changed')
        record=store.receipt(state.save_id,state.generation,request.request_id)
        if record:
            if record.kind!='command' or record.intent!=request.digest():raise ConflictError('upgrade request identity conflict')
            return Receipt(record.request_id,record.committed_revision,record.payload)
        if state.content_version==new_registry.content_version:
            GameApplication(store,new_registry,clock).foundation.validate_state(state)
            return Receipt(request.request_id,state.revision,{'status':'ALREADY_UPGRADED','content_version':state.content_version})
        if request.expected_revision!=state.revision or state.time['pending'] is not None:raise ConflictError('upgrade requires current revision and completed settlement')
        if state.content_version!=old_registry.content_version or set(state.domains)!={'inventory','sect','production','disciples'}:raise ValidationError('only declared Phase13 content compatibility supported')
        old=DandingApplication(store,old_registry,clock);old.foundation.validate_state(state)
        # Existing content comes from the same validated loaders, unchanged quantities,
        # durations/capability/definition IDs. Only add player/monster/encounter content.
        candidate=replace(state,content_version=new_registry.content_version,revision=state.revision+1)
        GameApplication(store,new_registry,clock).foundation.validate_state(candidate)
        receipt=Receipt(request.request_id,candidate.revision,{'status':'UPGRADED','from_content_version':state.content_version,'content_version':candidate.content_version})
        store.checkpoint(state.save_id)  # Pre-upgrade verified source in existing previous table.
        store.commit(state,candidate,StoredReceipt(state.save_id,state.generation,request.request_id,request.digest(),candidate.revision,'command',thaw_json(receipt.result)))
    return receipt

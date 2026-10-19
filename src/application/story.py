"""Read acknowledgements reuse CAS/receipt/SQLite without waking the simulation."""
from dataclasses import replace
from src.application.memory import Receipt
from src.core.save.codec import StoredReceipt
from src.core.state.envelope import thaw_json
from src.core.validation import ConflictError, ValidationError
from src.systems.sect import story

COMMANDS=('story_read',)


def execute(app,q):
    with app.store.transaction():
        before=app.query(q.save_id)
        if q.generation!=before.generation:raise ConflictError('存档已换代，请刷新')
        saved=app.store.receipt(q.save_id,q.generation,q.request_id)
        if saved:
            if saved.kind!='command' or saved.intent!=q.digest() or saved.committed_revision>before.revision:raise ConflictError('重复请求内容不一致')
            return app.foundation._decode_receipt(saved)
        if q.expected_revision!=before.revision or before.time['pending']:raise ConflictError('请先完成续算并刷新剧情记录')
        if q.version!=1:raise ValidationError('未知剧情命令版本')
        candidate=story.mark_read(before,app.registry,q.payload)
        candidate=replace(candidate,revision=before.revision+1 if candidate!=before else before.revision)
        app.foundation.validate_state(candidate)
        receipt=Receipt(q.request_id,candidate.revision,{'operation':q.name,'node_id':q.payload['node_id']})
        app.store.commit(before,candidate,StoredReceipt(q.save_id,q.generation,q.request_id,q.digest(),candidate.revision,'command',thaw_json(receipt.result)))
        return receipt

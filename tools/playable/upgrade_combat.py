"""CLI-only Phase13→14 compatible content upgrade; no setup/reset/resource grants."""
from uuid import uuid4
from tools.playable.game import PROJECT
from src.application.combat_upgrade import upgrade
from src.application.memory import Command
from src.core.time.clock import SystemClock
from src.core.save.sqlite import SQLiteSave
from src.core.validation import uuid4_id

def run():
    root=PROJECT/'.game';pointer=root/'save-id'
    if root.is_symlink() or pointer.is_symlink():raise RuntimeError('routing symlink rejected')
    save_id=pointer.read_text().strip();uuid4_id(save_id,'save id')
    with SQLiteSave(root/'danding.sqlite3',allowed_root=root) as store:
        result=store.inspect(save_id,include_recovery=False)
        if result.status!='CURRENT_VALID':raise RuntimeError('existing save unavailable; no reset')
        state=result.current
        receipt=upgrade(store,SystemClock(),Command(save_id,state.generation,state.revision,str(uuid4()),'game_content_upgrade',{}))
    return dict(receipt.result)

if __name__=='__main__':print(run())

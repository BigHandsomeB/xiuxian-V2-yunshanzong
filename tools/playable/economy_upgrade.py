"""Operator-only explicit Phase16 upgrade using Foundation checkpoint and receipt."""
from dataclasses import replace
import importlib.util,json,os
from pathlib import Path
from uuid import uuid4
from src.application.memory import Command
from src.application.economy_upgrade import upgrade
from src.application.economy import EconomyApplication
from src.data.economy.definitions import load_economy
from src.core.save.sqlite import SQLiteSave
from src.core.time.clock import SystemClock
from tools.playable.game import PROJECT

def run(root=None):
    if root is None:root=PROJECT/'.game'
    elif not Path(root).resolve().is_relative_to(PROJECT/'.tmp'):raise RuntimeError('injected root must be an isolated V2 fixture')
    root=Path(root);pointer=root/'save-id';path=root/'danding.sqlite3'
    if root.is_symlink() or pointer.is_symlink() or path.is_symlink():raise RuntimeError('private path symlink rejected')
    identity=pointer.read_text().strip();clock=SystemClock()
    with SQLiteSave(path,allowed_root=root) as store:
        before=store.inspect(identity,include_recovery=False).current
        if before is None:raise RuntimeError('valid current state required')
        q=Command(identity,before.generation,before.revision,str(uuid4()),'economy_content_upgrade',{})
        spec=importlib.util.spec_from_file_location('guard',PROJECT/'tools/project_paths.py');guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)
        backup=PROJECT/'.tmp'/('phase16-pre-upgrade-'+q.request_id+'.json')
        guard.write(backup,json.dumps(before.to_dict(),ensure_ascii=False));os.chmod(backup,0o600)
        receipt=upgrade(store,clock,q);after=EconomyApplication(store,load_economy(),clock).query(identity)
        if before.time!=after.time or before.identity!=after.identity or any(after.domains[k]!=v for k,v in before.domains.items()):raise RuntimeError('upgrade preservation verification failed')
        print({'status':receipt.result['status'],'resource_changes':'NONE','prior_domains':'PRESERVED','clock':'PRESERVED','pause':'PRESERVED','policies':'DEFAULT_OFF','checkpoint':'EXISTING_FOUNDATION'})
if __name__=='__main__':run()

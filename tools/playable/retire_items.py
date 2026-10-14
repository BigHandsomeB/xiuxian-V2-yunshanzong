"""Explicit CLI-only user-authorized disposal; no reset, supply, or public endpoint."""
import json,os,importlib.util
from pathlib import Path
from uuid import uuid4
from src.application.item_retirement import RetiredEconomyApplication
from src.application.memory import Command
from src.core.save.sqlite import SQLiteSave
from src.core.time.clock import SystemClock
from src.data.economy.definitions import load_economy
from src.core.validation import ConflictError
PROJECT=Path(__file__).resolve().parents[2]

def run(root=None,*,expected_revision=195,expected_dewleaf=3):
    root=Path(root or PROJECT/'.game');pointer=root/'save-id';path=root/'danding.sqlite3'
    if any(p.is_symlink() for p in (root,pointer,path)):raise RuntimeError('symlink forbidden')
    identity=pointer.read_text().strip()
    spec=importlib.util.spec_from_file_location('guard',PROJECT/'tools/project_paths.py');guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)
    with SQLiteSave(path,allowed_root=root) as store:
        app=RetiredEconomyApplication(store,load_economy(),SystemClock());before=app.query(identity)
        e=before.domains['equipment'];rows=list(e['instances'].values())
        if before.revision!=expected_revision or before.domains['inventory']['holdings'].get('dewleaf',0)!=expected_dewleaf or len(rows)!=1 or rows[0]['definition_id']!='basic_head' or any(rows[0][k] for k in ('equipped','locked','favorite')):
            raise ConflictError('正式存档已变化，停止删除并重新审查，不自动扩大范围')
        if before.domains['combat']['battle']['status']!='SETTLED':raise ConflictError('战斗状态已变化')
        q=Command(identity,before.generation,before.revision,str(uuid4()),'retire_three_items',{})
        backup=PROJECT/'.tmp'/('before-item-retirement-'+q.request_id+'.json');guard.write(backup,json.dumps(before.to_dict(),ensure_ascii=False));os.chmod(backup,0o600)
        r=app.retire_owned(q);after=app.query(identity)
        assert after.time==before.time and after.identity==before.identity
        assert {k:v for k,v in before.domains['inventory']['holdings'].items() if k!='dewleaf'}==dict(after.domains['inventory']['holdings'])
        assert not after.domains['equipment']['instances'] and not after.domains['equipment']['slots']
        assert all(after.domains[k]==v for k,v in before.domains.items() if k not in ('inventory','equipment','automation'))
        assert app.retire_owned(q)==r
        print(json.dumps({'status':'REMOVED','dewleaf_removed':expected_dewleaf,'head_removed':1,'sword_removed':0,'compensation':'NONE','other_resources':'EXACTLY_PRESERVED','time_pause':'EXACTLY_PRESERVED','identity_counters':'EXACTLY_PRESERVED','old_receipts_checkpoint':'PRESERVED','revision':after.revision,'replay':'PASS'},ensure_ascii=False))
if __name__=='__main__':run()

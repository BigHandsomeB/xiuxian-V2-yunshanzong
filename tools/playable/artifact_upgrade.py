"""Operator-only artifact content upgrade. --apply is required; no startup migration."""
import argparse
import json
from pathlib import Path
from uuid import uuid4
from src.application.artifact_upgrade import upgrade
from src.application.memory import Command
from src.core.save.sqlite import SQLiteSave
from src.core.time.clock import SystemClock
from tools.playable.game import PROJECT


def run(root, apply=False):
    root = Path(root)
    if root != PROJECT / '.game' and not root.resolve().is_relative_to(PROJECT / '.tmp'):
        raise RuntimeError('use the declared game root or an isolated V2 fixture')
    pointer, path = root / 'save-id', root / 'danding.sqlite3'
    if any(value.is_symlink() for value in (root, pointer, path)):
        raise RuntimeError('private path symlink rejected')
    save_id = pointer.read_text().strip()
    with SQLiteSave(path, allowed_root=root) as store:
        state = store.inspect(save_id, include_recovery=False).current
        if state is None:
            raise RuntimeError('valid current save required')
        if not apply:
            return {'status': 'DRY_RUN', 'content_version': state.content_version,
                    'equipment_count':len(state.domains.get('equipment',{}).get('instances',{})),
                    'active_battle':bool(state.domains.get('combat',{}).get('battle')), 
                    'pending': bool(state.time['pending'])}
        request = Command(save_id, state.generation, state.revision, str(uuid4()), 'artifact_content_upgrade', {})
        backup = PROJECT / '.tmp' / ('artifacts-pre-upgrade-' + request.request_id + '.json')
        backup.parent.mkdir(exist_ok=True)
        with backup.open('x') as output:
            output.write(json.dumps(state.to_dict(), ensure_ascii=False))
        backup.chmod(0o600)
        # SQLite backup includes the original receipts and identity counters.
        import os,sqlite3
        database_backup=backup.with_suffix('.sqlite3')
        descriptor=os.open(database_backup,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        os.close(descriptor)
        with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as source, sqlite3.connect(database_backup) as target:
            source.backup(target)
        receipt = upgrade(store, SystemClock(), request)
        return {**dict(receipt.result), 'backup': str(backup),'database_backup':str(database_backup)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=PROJECT / '.game')
    parser.add_argument('--apply', action='store_true')
    arguments = parser.parse_args()
    print(run(arguments.root, arguments.apply))

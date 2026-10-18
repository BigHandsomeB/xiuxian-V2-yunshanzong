"""Read an explicitly supplied isolated StateEnvelope JSON; never connect to SQLite."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

ROOT = Path(__file__).resolve().parents[2]
if __name__ == '__main__':
    sys.dont_write_bytecode = True
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

from src.application.content_compatibility import inspect_compatibility
from src.core.save.backup import MAX_SAVE_BYTES
from src.core.state.envelope import StateEnvelope
from src.core.validation import ValidationError


def checked_input(path, root=ROOT):
    root = Path(root).resolve()
    path = Path(path)
    if '..' in path.parts:
        raise ValidationError('parent traversal is forbidden')
    path = path if path.is_absolute() else root / path
    try:
        relative = path.relative_to(root)
    except ValueError:
        raise ValidationError('snapshot must be inside the isolated V2 directories') from None
    if not relative.parts or relative.parts[0] not in ('.tmp', 'tests') or path.suffix != '.json':
        raise ValidationError('only explicit .tmp/tests JSON snapshots are allowed')
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValidationError('snapshot symlinks are forbidden')
    if not path.resolve().is_relative_to(root / relative.parts[0]):
        raise ValidationError('snapshot escaped its isolated directory')
    return path


def read_snapshot(path, *, root=ROOT):
    path = checked_input(path, root)
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValidationError('duplicate snapshot JSON key')
            result[key] = value
        return result
    def invalid(_):
        raise ValidationError('nonfinite snapshot JSON value')
    descriptor = os.open(path, os.O_RDONLY | getattr(os,'O_NOFOLLOW',0) | getattr(os,'O_NONBLOCK',0))
    with os.fdopen(descriptor, 'rb') as source:
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_SAVE_BYTES:
            raise ValidationError('snapshot must be a regular file within the backup byte limit')
        raw = source.read(MAX_SAVE_BYTES + 1)
        after = os.fstat(source.fileno())
    checked_input(path, root)
    current = path.stat()
    identity = lambda row: (row.st_dev, row.st_ino, row.st_size, row.st_mtime_ns)
    if len(raw) > MAX_SAVE_BYTES or identity(before) != identity(after) or identity(after) != identity(current):
        raise ValidationError('snapshot changed during read or exceeds the backup byte limit')
    data = json.loads(raw.decode('utf-8'), object_pairs_hook=unique, parse_constant=invalid)
    return StateEnvelope.from_dict(data), hashlib.sha256(raw).hexdigest()


def run(path, target_version):
    state, raw_digest = read_snapshot(path)
    report = inspect_compatibility(state, target_version)
    report['snapshot_file_sha256'] = raw_digest
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--target', required=True)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    try:
        report = run(args.snapshot, args.target)
    except (OSError, ValueError, TypeError, RecursionError):
        report = {'report_schema_version': 1, 'transition': 'BLOCKED',
                  'issues': [{'code': 'INVALID_INPUT', 'message': 'Snapshot path, JSON or schema is invalid.'}]}
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print('Transition:', report['transition'])
        for side in ('source', 'target'):
            if side in report:
                print(side + ':', report[side]['content_version'], report[side]['validation'])
        for issue in report['issues']:
            print(issue['code'] + ':', issue['message'])
        if 'differences' in report:
            print('Differences:', json.dumps(report['differences'], ensure_ascii=False, sort_keys=True))
        print('Not checked:', ', '.join(report.get('not_checked', ())))
    return 0 if (report['transition'] == 'NOT_NEEDED' and
                 report.get('source', {}).get('validation') == 'VALID' and
                 report.get('target', {}).get('validation') == 'VALID') else 1


if __name__ == '__main__':
    raise SystemExit(main())

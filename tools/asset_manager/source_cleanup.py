"""Retain Source provenance, remove original bytes after complete publication."""
import hashlib
import json
from .catalog import now
from .model import AssetError, require


def clean(c, all_originals=False):
    result = dict(deleted=0, bytes_freed=0, errors=[])
    with c.transaction() as conn:
        assets = []
        for row in conn.execute("SELECT body FROM metadata WHERE kind='asset'"):
            asset = json.loads(row[0])
            assets.append(dict(asset_id=asset['asset_id'], versions=[{k: v[k] for k in ('version', 'source_id', 'files', 'runtime', 'plan')} for v in asset['versions']]))
        sources = [json.loads(row[0]) for row in conn.execute("SELECT body FROM metadata WHERE kind='source'")]
        previews = []
        for row in conn.execute("SELECT body FROM metadata WHERE kind='preview'"):
            preview = json.loads(row[0])
            previews.append({k: preview.get(k) for k in ('source_id', 'result', 'lifecycle_status', 'expires_at')})
        manifest = json.loads(c.path('manifest.json').read_text())['assets']
        for source in sources:
            if source.get('file_deleted_at'):
                continue
            sid = source['source_id']
            versions = [(a, v) for a in assets for v in a['versions'] if v['source_id'] == sid or any(f.get('source_id') == sid for f in v['files'])]
            if not all_originals:
                if any(p.get('source_id') == sid and not p.get('result') and p.get('lifecycle_status') != 'retired' and p.get('expires_at', '') > now() for p in previews):
                    continue
                cells = (source.get('frozen_spec') or {}).get('cell_mapping', [])
                expected_cells = {(r.get('asset_id'), r.get('action'), r.get('frame')) for r in cells}
                actual_cells = {(a['asset_id'], r.get('action'), r.get('frame')) for a, v in versions for r in v.get('plan', {}).get('regions', []) if v['source_id'] == sid}
                if expected_cells - actual_cells:
                    continue
                expected = set((source.get('frozen_spec') or {}).get('asset_ids', []))
                if not versions or expected - {a['asset_id'] for a, v in versions}:
                    continue
                # Keep originals for unfinished/excluded versions and Master-only uploads.
                if any(not v.get('runtime') or not v['runtime']['files'] or not v['files'] or a['asset_id'] not in manifest or manifest[a['asset_id']]['version'] != v['version'] for a, v in versions):
                    continue
            try:
                if not all_originals:
                    for a, v in versions:
                        for f in v['files'] + v['runtime']['files']:
                            require(hashlib.sha256(c.path(f['file']).read_bytes()).hexdigest() == f['sha256'], 'Missing or changed output; original retained')
                require(source['file'].startswith('source/files/'), 'Invalid Source file path')
                path = c.path(source['file'])
                size = path.stat().st_size if path.exists() else 0
                # File removal and tombstone are idempotent, including a retry after interruption.
                path.unlink(missing_ok=True)
                source.update(file_deleted_at=now(), file_deleted_reason='operator_cleanup' if all_originals else 'runtime_published')
                c.put('source', sid, source, conn)
                result['deleted'] += 1
                result['bytes_freed'] += size
            except (OSError, AssetError) as exc:
                result['errors'].append(dict(source_id=sid, error=str(exc)))
    return result

"""Small public presentation index; no source images, prompts or private database."""
import json
import re
from pathlib import Path


def read_catalog(root, snapshot):
    root = Path(root).resolve()
    path = root / 'registry/published-catalog.json'
    empty = {'available': False, 'groups': []}
    try:
        if not path.is_file() or path.is_symlink() or path.parent.is_symlink() or path.stat().st_size > 512 * 1024:
            return empty
        data = json.loads(path.read_text())
        if not isinstance(data, dict) or data.get('schema_version') != 1 or not isinstance(data.get('groups'), list):
            return empty
        groups = []
        for value in data['groups']:
            if not isinstance(value, dict) or not isinstance(value.get('items'), list):
                return empty
            if any(not isinstance(value.get(k), str) or len(value[k]) > 128 for k in ('set_id', 'name', 'category')):
                return empty
            items = []
            for row in value['items']:
                if not isinstance(row, dict):
                    return empty
                aid = row.get('asset_id')
                if not isinstance(aid, str) or re.fullmatch('[a-z][a-z0-9_.]*', aid) is None:
                    return empty
                if aid not in snapshot or row.get('version') != snapshot[aid].get('version'):
                    continue
                if any(not isinstance(row.get(k), str) or len(row[k]) > 128 for k in ('name', 'category')):
                    return empty
                items.append({k: row[k] for k in ('asset_id', 'name', 'category')})
            if items:
                groups.append({k: value.get(k) for k in ('set_id', 'name', 'category', 'grade')} | {'items': items})
        return {'available': True, 'groups': groups}
    except (OSError, ValueError, TypeError, AttributeError):
        return empty

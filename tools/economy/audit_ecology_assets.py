"""Read-only Approved Runtime audit with copyable Chinese production lists."""
import argparse
import json
import sqlite3
from hashlib import sha256
from pathlib import Path
from src.data.economy.ecology import content

ROOT = Path(__file__).resolve().parents[2]


def audit():
    data = content()
    assets_root = ROOT / 'assets'
    manifest = json.loads((assets_root / 'manifest.json').read_text())['assets']
    bindings = json.loads((ROOT / 'src/rendering/game-assets.json').read_text())
    catalog_path = assets_root / 'registry/catalog.sqlite3'
    if catalog_path.is_symlink():
        raise RuntimeError('catalog symlink rejected')
    with sqlite3.connect(catalog_path.resolve().as_uri() + '?mode=ro', uri=True) as connection:
        records = [json.loads(row[0]) for row in connection.execute("SELECT body FROM metadata WHERE kind='asset'")]
        sets = {row['set_id']: row.get('name_zh', '') for raw, in connection.execute(
            "SELECT body FROM metadata WHERE kind='set'") for row in [json.loads(raw)]}
    groups = {'crop': '灵植作物', 'meal': '灵膳成品', 'feed': '饲料', 'material': '养殖副产物'}
    rows = [{'id': row['id'], 'name': row['name'], 'group': '营造材料' if row['id'].startswith('sect_') and row['id'] in (
             'sect_lining', 'sect_shell_part', 'sect_bone_frame', 'sect_nurture_agent') else groups[row['category']],
             'binding_map': 'icons'} for row in data['resources']]
    rows += [{'id': row['id'], 'name': row['name'], 'group': '灵兽' if row['building_kind'] == 'pasture' else '水产',
              'binding_map': 'icons'} for row in data['species']]
    rows += [{'id': row['id'], 'name': row['name'], 'group': '营造设施', 'binding_map': 'system_icons'} for row in data['facilities']]
    for row in rows:
        found = []
        for record in records:
            aid = record['asset_id']
            published = manifest.get(aid)
            if record.get('name_zh') != row['name'] or record.get('lifecycle_status', 'active') != 'active' or not published:
                continue
            if not record.get('current_approved_version') or published['version'] != record['current_approved_version']:
                continue
            valid = True
            for item in published['files']:
                file = assets_root / item['file']
                if file.is_symlink() or not file.resolve().is_relative_to((assets_root / 'runtime').resolve()) or not file.is_file():
                    valid = False
                    break
                if sha256(file.read_bytes()).hexdigest() != item['sha256']:
                    valid = False
                    break
            if valid:
                found.append(record)
        row['candidate_asset_ids'] = sorted(record['asset_id'] for record in found)
        # Equal display names can represent different roles (ingredient/live
        # loach). Resolve by the authored set group, never alphabetical asset ID.
        if len(found) > 1:
            bound = bindings.get(row['binding_map'], {}).get(row['id'])
            retained = [record for record in found if record['asset_id'] == bound]
            found = retained or [record for record in found if sets.get(record.get('set_id'), '').startswith(row['group'])]
        selected = found[0] if len(found) == 1 else None
        row['approved_asset_id'] = selected['asset_id'] if selected else None
        row['asset_group'] = sets.get(selected.get('set_id'), '') if selected else None
        row['status'] = '可复用已批准Runtime' if selected else '缺少唯一匹配的已批准Runtime'
    return rows


def write(output, bind=False):
    output = Path(output)
    if not output.resolve().is_relative_to(ROOT) or output.is_symlink():
        raise RuntimeError('audit output must stay inside V2')
    output.mkdir(parents=True, exist_ok=True)
    rows = audit()
    (output / 'asset-audit.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n')
    missing = [row for row in rows if not row['approved_asset_id']]
    (output / 'missing-assets.txt').write_text('\n'.join(row['name'] for row in missing) + '\n')
    lines = ['# 四建筑缺素材清单', '', f'当前缺素材：{len(missing)} 个。已匹配：{len(rows) - len(missing)} / {len(rows)} 个角色。', '', '精确名称、批准版本、当前Manifest及Runtime文件hash均已核对。通用图标不冒充具体物品。原有四建筑图复用，不新增室内场景或逐帧动物动画。', '']
    for group in dict.fromkeys(row['group'] for row in rows):
        names = [row['name'] for row in missing if row['group'] == group]
        for start in range(0, len(names), 25):
            batch = names[start:start + 25]
            lines += [f'## {group} 第{start // 25 + 1}组（{len(batch)}个）', '', '```text', *batch, '```', '']
    lines += ['## 可直接复用', '']
    for row in rows:
        if row['approved_asset_id']:
            lines.append(f'- {row["name"]}：{row["approved_asset_id"]}')
    (output / 'missing-assets.md').write_text('\n'.join(lines))
    if bind:
        path = ROOT / 'src/rendering/game-assets.json'
        bindings = json.loads(path.read_text())
        for row in rows:
            mapping = bindings.setdefault(row['binding_map'], {})
            if mapping.get(row['id']) is None:
                mapping[row['id']] = row['approved_asset_id']
        path.write_text(json.dumps(bindings, ensure_ascii=False, indent=2) + '\n')
    return {'audited': len(rows), 'reused': len(rows) - len(missing), 'missing': len(missing)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/acceptance/TASK0078')
    parser.add_argument('--bind', action='store_true')
    args = parser.parse_args()
    print(write(args.output, args.bind))

"""Isolated real UI fixture with the complete registered material catalog."""
import json
import re
from pathlib import Path
from tests.ecology_ui_fixture import fixture
from src.data.dungeons.definitions import load_dungeons
from src.application.danding import resource_category


def sources():
    result = {}
    def read(path):
        path = Path(path)
        key = path.as_posix()
        if key in result:
            return
        source = path.read_text()
        result[key] = source
        for target in re.findall(r"^import\s+.+?\s+from\s+['\"](.+?)['\"];?\s*$", source, re.M):
            parts = []
            for part in (path.parent / target).parts:
                if part == '..':
                    parts.pop()
                elif part != '.':
                    parts.append(part)
            read(Path(*parts))
    for name in ('screens/inventory.js', 'components/patch.js', 'adapters.js'):
        read(Path('src/ui/pages/game/static') / name)
    result['src/ui/pages/game/static/game.css'] = Path('src/ui/pages/game/static/game.css').read_text()
    return result


if __name__ == '__main__':
    data = fixture()
    registry = load_dungeons(management=True, cold_jade=True, ecology=True)
    # All one-unit rows are test-only view inputs, never persisted stock grants.
    data['view']['inventory'] = {key.machine_id: {'name': row.display_name, 'quantity': 1,
        'category': resource_category(row)} for key, row in registry._definitions.items()
        if key.domain == 'resources'}
    data['view']['holdings'] = {}
    print(json.dumps({'sources': sources(), 'fixture': data,
        'test': Path('tests/warehouse_ui_test.js').read_text(),
        'backpack_test': Path('tests/equipment_bulk_backpack_ui_test.js').read_text()}, ensure_ascii=False))

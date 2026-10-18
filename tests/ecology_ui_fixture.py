"""Generate an isolated, real read-model fixture and its JS dependency graph."""
import json
import re
from pathlib import Path
from src.core.state.envelope import thaw_json
from tests.systems.test_ecology import EcologyTests
from src.rendering.game import present
from src.rendering.game_runtime import GameRuntimeAssets


def fixture():
    EcologyTests.setUpClass()
    case = EcologyTests()
    case.setUp()
    try:
        case.assign('pasture')
        case.buy()
        case.settle(240000)
        view = thaw_json(case.view())
        presentation = present(view, GameRuntimeAssets(Path('assets')))
        return {'protocol_version': 1, 'view': view,
                'presentation': {key: presentation[key] for key in ('icons', 'system_icons')},
                'csrf': 'isolated-only'}
    finally:
        case.doCleanups()


def sources():
    values = {}
    def read(path):
        key = path.as_posix()
        if key in values:
            return
        text = path.read_text()
        values[key] = text
        for target in re.findall(r"^import\s+.+?\s+from\s+['\"](.+?)['\"];?\s*$", text, re.M):
            parts = []
            for part in (path.parent / target).parts:
                if part == '..':
                    parts.pop()
                elif part != '.':
                    parts.append(part)
            read(Path(*parts))
    read(Path('src/ui/pages/game/static/screens/ecology.js'))
    read(Path('src/ui/pages/game/static/screens/sect-management.js'))
    read(Path('src/ui/pages/game/static/components/patch.js'))
    read(Path('src/ui/pages/game/static/adapters.js'))
    values['src/ui/pages/game/static/game.css'] = Path('src/ui/pages/game/static/game.css').read_text()
    return values


if __name__ == '__main__':
    print(json.dumps({'sources': sources(), 'fixture': fixture(), 'test': Path('tests/ecology_ui_test.js').read_text()}, ensure_ascii=False))

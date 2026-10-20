"""Disposable staffing read model and a bounded graph of actual native ES modules."""
import json
import re
from pathlib import Path
from src.core.state.envelope import thaw_json
from tests.test_recipe_staffing import RecipeStaffingTests


def fixture():
    RecipeStaffingTests.setUpClass()
    case = RecipeStaffingTests()
    case.setUp()
    try:
        case.adjust(); case.adjust(); case.adjust('ju_qi_pill')
        full = thaw_json(case.view())
        view = {key: full[key] for key in ('recipe_staffing', 'disciples', 'buildings', 'world', 'time')}
        return {'selectedBuilding': case.alchemy, 'view': view,
            'presentation': {'system_icons': {'disciples': {'asset_id': 'workforce-fixture',
                'asset': {'url': '/game/runtime/workforce-fixture.png', 'width': 48, 'height': 48}}}}}
    finally:
        case.doCleanups()


def sources():
    values = {}
    def read(path):
        path = path.resolve()
        key = path.relative_to(Path.cwd()).as_posix()
        if key in values:return
        values[key] = path.read_text()
        for target in re.findall(r"^import\s+.+?\s+from\s+['\"](.+?)['\"];?\s*$", values[key], re.M):
            read(path.parent/target)
    for name in ('screens/disciple-detail.js', 'screens/disciples.js', 'components/patch.js', 'api-client.js', 'lifecycle.js'):
        read(Path('src/ui/pages/game/static')/name)
    return values


if __name__ == '__main__':
    print(json.dumps({'fixture': fixture(), 'sources': sources(),
        'test': Path('tests/recipe_staffing_ui_test.js').read_text(),
        'styles': {'game': Path('src/ui/pages/game/static/game.css').read_text()}}))

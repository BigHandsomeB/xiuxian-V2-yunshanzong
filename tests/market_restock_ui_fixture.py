"""Real isolated stock policy and the existing recursive native-JS graph loader."""
import json
from pathlib import Path
from tests.test_market_restock import RestockTests
from tests.artifact_ui_fixture import sources
from src.core.state.envelope import thaw_json
from src.rendering.game import present
from src.rendering.game_runtime import GameRuntimeAssets


def fixture():
    RestockTests.setUpClass();case=RestockTests();case.setUp()
    try:
        case.configure();case.assign();case.settle()
        view=thaw_json(case.view())
        return {'protocol_version':1,'view':view,
                'presentation':thaw_json(present(view,GameRuntimeAssets(Path('assets')))),
                'csrf':'isolated-only'}
    finally:case.doCleanups()


if __name__=='__main__':
    print(json.dumps({'fixture':fixture(),'sources':sources(),
          'test':Path('tests/market_restock_ui_test.js').read_text()},ensure_ascii=False))

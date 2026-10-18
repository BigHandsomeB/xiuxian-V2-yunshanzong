"""Current server views and real approved asset bindings from a disposable save."""
import json
import os
from pathlib import Path
import re
from src.application import equipment
from src.core.state.envelope import thaw_json
from src.data.combat.mechanics import ROLL_VERSION
from src.rendering.game import present
from src.rendering.game_runtime import GameRuntimeAssets
from tests.systems.test_combat_mechanics import ApplicationEffectsTests

def fixture():
    ApplicationEffectsTests.setUpClass();case=ApplicationEffectsTests();case.setUp()
    try:
        def grant(state):
            for key in ('thorn_fang_blade','fire_elixir_ruins_equipment_12'):
                state,_=equipment.acquire(state,case.registry,key,'ui-isolation',roll_version=ROLL_VERSION)
            return state
        case.fixture(grant);view=thaw_json(case.view())
        return {'protocol_version':1,'csrf':'isolated-only','view':view,
                'presentation':present(view,GameRuntimeAssets(Path('assets')))}
    finally:case.doCleanups()

def sources():
    result={}
    def visit(path):
        key=path.as_posix()
        if key in result:return
        result[key]=path.read_text()
        for relative in re.findall(r'^import\s+.+?\s+from\s+[\'"](.+?)[\'"]',result[key],re.M):
            visit(Path(os.path.normpath(path.parent/relative)))
    for name in ('screens/battle.js','screens/techniques.js','screens/equipment.js','screens/adventure.js','components/patch.js','api-client.js'):
        visit(Path('src/ui/pages/game/static')/name)
    return result

if __name__=='__main__':
    print(json.dumps({'test':Path('tests/formal_technique_ui_test.js').read_text(),'sources':sources(),'fixture':fixture()},ensure_ascii=False))

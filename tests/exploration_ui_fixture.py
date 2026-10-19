"""Synthetic read-model states for the shipped native exploration UI tests."""
import json
import re
from pathlib import Path
from src.core.state.envelope import thaw_json
from tests.systems.test_exploration import ExplorationTests


def fixture():
    ExplorationTests.setUpClass();case=ExplorationTests();case.setUp()
    try:
        def response():
            all_view=thaw_json(case.view())
            view={k:all_view[k] for k in ('exploration','world','time')}
            view['inventory']={k:v for k,v in all_view['inventory'].items() if k in ('coins','ordinary_wood','wood','spring_water','herb','purple_copper','stone')}
            view['combat']={k:v for k,v in all_view['combat'].items() if k in ('dungeon','dungeons','auto','status','battle_id')}
            return {'protocol_version':1,'view':view,'presentation':{},'csrf':'isolated'}
        states={'idle':response()}
        case.start();states['travelling']=response()
        case.finish();states['ready']=response()
        case.choose();states['resolved']=response()
        case.command('world_pause',{});states['paused']=response()
        return states
    finally:case.doCleanups()


if __name__=='__main__':
    base=Path('src/ui/pages/game/static')
    sources={}
    def collect(path):
        key=str(path)
        if key in sources:return
        sources[key]=path.read_text()
        for name in re.findall(r"from ['\"](.+?)['\"]",sources[key]):
            import os
            collect(Path(os.path.normpath(path.parent/name)))
    for entry in ('screens/exploration.js','screens/adventure.js','components/patch.js','adapters.js','api-client.js','lifecycle.js'):
        collect(base/entry)
    print(json.dumps({'states':fixture(),'sources':sources,
                     'test':Path('tests/exploration_ui_test.js').read_text(),
                     'client_test':Path('tests/exploration_client_test.js').read_text()}))

"""Real artifact read-model fixture and recursive native ES-module source graph."""
import json
import re
from pathlib import Path
from src.core.state.envelope import thaw_json
from tests.systems.test_artifacts import ArtifactTests
from src.application.ecology import EcologyApplication
from src.core.save.sqlite import SQLiteSave
from src.rendering.game import present
from src.rendering.game_runtime import GameRuntimeAssets


def fixture():
    ArtifactTests.setUpClass();case=ArtifactTests();case.setUp()
    try:
        case.craft();case.execute('artifact_equip',{'artifact_id':case.key})
        with SQLiteSave(case.path,allowed_root=case.root) as store:
            view=thaw_json(EcologyApplication(store,case.registry,case.clock).view(case.sid))
        presentation=present(view,GameRuntimeAssets(Path('assets')))
        return {'protocol_version':1,'view':view,'presentation':thaw_json(presentation),'csrf':'isolated-only'}
    finally:case.doCleanups()


def sources():
    values={}
    def read(path):
        path=Path(path);key=path.as_posix()
        if key in values:return
        values[key]=path.read_text()
        for target in re.findall(r"^import\s+.+?\s+from\s+['\"](.+?)['\"];?\s*$",values[key],re.M):
            parts=[]
            for part in (path.parent/target).parts:
                if part=='..':parts.pop()
                elif part!='.':parts.append(part)
            read(Path(*parts))
    for name in ['screens/artifacts.js','components/patch.js','adapters.js','building-adapters.js','battle/renderer.js','api-client.js']:
        read('src/ui/pages/game/static/'+name)
    return values

if __name__=='__main__':
    print(json.dumps({'fixture':fixture(),'sources':sources(),'test':Path('tests/artifact_ui_test.js').read_text()},ensure_ascii=False))

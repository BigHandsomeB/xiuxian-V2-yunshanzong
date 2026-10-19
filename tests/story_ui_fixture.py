"""Small real read models and only the ES modules used by the story UI harness."""
import json
import os
import re
from pathlib import Path
from dataclasses import replace
from tests.test_story import StoryTests
from src.core.state.envelope import thaw_json
from src.systems.sect import story


def fixture():
    StoryTests.setUpClass();case=StoryTests();case.setUp()
    try:
        def response():
            v=thaw_json(case.view())
            return {'protocol_version':1,'view':{k:v[k] for k in ('story','world','time')},'presentation':{},'csrf':'isolated'}
        states={'fresh':response()};case.complete();states['complete']=response()
        case.command('story_read',{'node_id':'chapter_1_01'});states['after_intro']=response()
        s=case.read();grown=thaw_json(s.domains['cultivation']);grown.update(current_realm='realm_1',progress=0,growth_revision=1)
        states['foundation']=response();states['foundation']['view']['story']=story.projection(replace(s,domains={**s.domains,'cultivation':grown}),case.registry)
        return thaw_json(states)
    finally:case.doCleanups()


if __name__=='__main__':
    base=Path('src/ui/pages/game/static');sources={}
    def collect(path):
        key=str(path)
        if key in sources:return
        sources[key]=path.read_text()
        for name in re.findall(r"from ['\"](.+?)['\"]",sources[key]):collect(Path(os.path.normpath(path.parent/name)))
    for name in ['screens/story.js','components/patch.js','api-client.js','router.js','lifecycle.js']:collect(base/name)
    print(json.dumps({'states':fixture(),'sources':sources,'test':Path('tests/story_ui_test.js').read_text()},ensure_ascii=False))

"""Build declared synthetic UI exports in isolated temporary storage, never .game."""
import json,tempfile
from dataclasses import replace
from pathlib import Path
from src.application.danding import initial_slice,target
from src.application.dungeons import DungeonApplication
from src.application import equipment as equip
from src.core.save.sqlite import SQLiteSave
from src.core.state.envelope import thaw_json
from src.data.dungeons.definitions import load_dungeons
from src.data.dungeons import loot
from src.rendering.game import present,manifest
from src.rendering.game_runtime import GameRuntimeAssets
from src.systems.cultivation import growth
from src.systems.dungeons import progress
from src.systems.economy import policy
from tools.playable.game import PROJECT
from src.application.memory import Command
from src.core.time.clock import SystemClock
from uuid import uuid4

def build(project=PROJECT):
    project=Path(project);registry=load_dungeons();assets=GameRuntimeAssets(project/'assets');views={}
    (project/'.tmp').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=project/'.tmp',prefix='ui-review-') as temporary:
        root=Path(temporary)
        for case,floor in [('normal',9),('elite',40),('boss',100),('production',9)]:
            state=initial_slice(registry,last_settled_at_ms=1000)
            stock=thaw_json(state.domains['inventory']);stock['holdings'].update(coins=1200,pill=6,wood=8,ore=4,ingot=4,grain=3)
            stock['holdings'].update({m['id']:1 for m in loot.content()['materials']})
            g=thaw_json(growth.initial(state.save_id));g.update(current_realm='realm_1',growth_revision=1) if case=='boss' else g.update(progress=1600 if case=='elite' else 800)
            state=replace(state,domains={**state.domains,'inventory':stock,'cultivation':g,'dungeon':{**progress.initial(),'cleared_floor':floor-1},'automation':policy.initial()})
            chosen={'thorn_fang_blade','thorn_vine_gloves','thorn_travel_belt','thorn_scale_shirt','thorn_moss_boots','thorn_feather_hood'}
            for definition in loot.content()['equipment']:
                state,identity=equip.acquire(state,registry,definition['id'],'UI_REVIEW_SYNTHETIC',roll_version='thorn-roll-v2')
                if definition['id'] in chosen:state=equip.command(state,registry,'equipment_equip',{'instance_id':identity})
            path=root/(case+'.sqlite3')
            with SQLiteSave.initialize(path,allowed_root=root) as store:
                app=DungeonApplication(store,registry,SystemClock());app.create(state)
                if case=='production':
                    current=app.query(state.save_id)
                    app.execute(Command(current.save_id,current.generation,current.revision,str(uuid4()),'alchemy_start',{'building_id':target(current),'recipe_id':'pill'}))
                else:
                    current=app.query(state.save_id)
                    app.execute(Command(current.save_id,current.generation,current.revision,str(uuid4()),'combat_start',{'encounter_id':progress.definition(registry).encounters[floor-1]}))
                view=thaw_json(app.view(state.save_id))
                views[case]={'protocol_version':1,'save_schema_version':view['save_schema_version'],'data_schema_version':view['data_schema_version'],'content_version':view['content_version'],'save_id':view['save_id'],'generation':view['generation'],'revision':view['revision'],'time':view['time'],'view':view,'presentation':present(view,assets),'csrf':'','review':{'read_only':True,'synthetic':True,'case':case}}
    bundle={'schema_version':1,'views':views,'assets':manifest(assets)}
    def rewrite(value):
        if isinstance(value,str):return value.replace('/game/runtime/','/game/review/runtime/').replace('/play/runtime/','/game/review/runtime/')
        if isinstance(value,dict):return {k:rewrite(v) for k,v in value.items()}
        if isinstance(value,list):return [rewrite(v) for v in value]
        return value
    return rewrite(bundle)

def run():
    output=PROJECT/'.ui-review.json';data=json.dumps(build(),ensure_ascii=False,separators=(',',':'))
    if output.is_symlink():raise ValueError('review output symlink rejected')
    pending=PROJECT/'.ui-review.json.new'
    if pending.is_symlink():raise ValueError('review temporary symlink rejected')
    pending.write_text(data);pending.replace(output)
    print({'synthetic_views':4,'bytes':len(data.encode()),'production_save_access':'NONE'})
if __name__=='__main__':
    import argparse
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()

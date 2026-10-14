"""Usage: PYTHONPATH=. .venv/bin/python -B tests/settlement_performance.py before|after.
Frozen baseline 20ae81d, identical detached fixture, isolated SQLite/WSGI.
Counts settle, view and one full-save read per complete view; no network RTT or periodic uploads."""
import contextlib,json,time,tempfile,sys,gzip,subprocess
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from dataclasses import replace
from src.application.economy_settlement import EconomySettlement
from src.application.dungeon_settlement import DungeonSettlement
from src.application.sect_management_settlement import ManagementSettlement
from src.application.sect_management import ManagementApplication
from src.transport.danding import create_app
from src.transport.save import register as register_save
from tools.playable.game import backup_application
from src.rendering.game import present
from src.rendering.game_runtime import GameRuntimeAssets
from src.core.save.sqlite import SQLiteSave,V2_ROOT
from tests.fixtures.time import ManualClock
from tests.systems.test_settlement_batch import SettlementBatchTests
from src.core.state.envelope import thaw_json
from src.systems.economy import policy
from src.core.time.config import SETTLEMENT_MAX_EVENTS,SETTLEMENT_BUDGET_MS

ROOT=V2_ROOT/'.tmp/settlement-optimization'
ROOT.mkdir(parents=True,exist_ok=True)
def original(name):
    namespace={'__name__':'benchmark_'+name.removesuffix('.py'),'__file__':str(V2_ROOT/'src'/('transport' if name=='danding.py' else 'application')/name)}
    classes={'economy_settlement.py':EconomySettlement,'dungeon_settlement.py':DungeonSettlement,'sect_management_settlement.py':ManagementSettlement,'sect_management.py':ManagementApplication}
    if name in classes:namespace['_benchmark_base_cls']=classes[name]
    source=subprocess.check_output(['git','show','20ae81d:src/'+('transport/' if name=='danding.py' else 'application/')+name],cwd=V2_ROOT,text=True)
    if name in classes:source=source.replace('super()','super(_benchmark_base_cls,self)')
    exec(source,namespace)
    return namespace
old_e=original('economy_settlement.py')['EconomySettlement'];old_d=original('dungeon_settlement.py')['DungeonSettlement'];old_m=original('sect_management_settlement.py')['ManagementSettlement'];old_app=original('sect_management.py')['ManagementApplication'];old_transport=original('danding.py')['create_app']
@contextlib.contextmanager
def baseline(enabled):
    with contextlib.ExitStack() as stack:
        if enabled:
            for cls,old,names in [(EconomySettlement,old_e,('advance','deliver','dispatch','wake')),(DungeonSettlement,old_d,('dispatch','wake')),(ManagementSettlement,old_m,('dispatch','wake','meals')),(ManagementApplication,old_app,('project_world',))]:
                for name in names:stack.enter_context(patch.object(cls,name,getattr(old,name)))
        yield
f=SettlementBatchTests();f.setUp()
try:
    s=f.state
    auto=thaw_json(s.domains['automation']);auto['production']={k:{**r,'enabled':False} for k,r in auto['production'].items()};s=replace(s,domains={**s.domains,'automation':auto})
    for kind,recipe in (('garden','grain'),('forest','wood')):
        b=next(k for k,r in s.domains['sect']['buildings'].items() if r['definition_id']==kind)
        s=f.app.start_candidate(s,b,recipe)
        auto=policy.set_production(s.domains['automation'],f.registry,b,{'enabled':True,'recipe_id':recipe,'target':10000,'reserves':{},'max_consumption':10000});s=replace(s,domains={**s.domains,'automation':auto})
    s=f.app.engine.wake(s)
    from src.core.state.envelope import StateEnvelope
    seed=ROOT/'benchmark-seed.json'
    if seed.exists():s=StateEnvelope.from_dict(json.loads(seed.read_text()))
    else:seed.write_text(json.dumps(s.to_dict()))
    rows=json.loads((ROOT/'benchmark-results.json').read_text()) if (ROOT/'benchmark-results.json').exists() else [];assets=GameRuntimeAssets(V2_ROOT/'assets')
    for mode in (sys.argv[1:] or ('before','after')):
        for hours in (1,8):
            with baseline(mode=='before'),tempfile.TemporaryDirectory(dir=V2_ROOT/'.tmp') as temp:
                root=Path(temp);db=root/'bench.sqlite3';clock=ManualClock(1000+hours*3600000);engine_ms=0;events=0
                with SQLiteSave.initialize(db,allowed_root=root) as store:ManagementApplication(store,f.registry,clock).create(s)
                @contextlib.contextmanager
                def application():
                    global engine_ms,events
                    with SQLiteSave(db,allowed_root=root) as store:
                        app=ManagementApplication(store,f.registry,clock)
                        app.settlement_max_events=SETTLEMENT_MAX_EVENTS;app.engine.budget_ms=SETTLEMENT_BUDGET_MS
                        if hasattr(app.engine,'result_path'):app.engine.result_path=mode!='before'
                        advance=app.engine.advance
                        def measured(*args,**kwargs):
                            global engine_ms,events
                            t=time.perf_counter();result=advance(*args,**kwargs);engine_ms+=(time.perf_counter()-t)*1000;events+=len(result[1].processed_events);return result
                        app.engine.advance=measured
                        yield app
                web=(old_transport if mode=='before' else create_app)(application,s.save_id,lambda v:present(v,assets),assets.file,'isolated-settlement-benchmark-00000000',secure=False,cookie_path='/')
                register_save(web,backup_application(application,s.save_id,root))
                client=web.test_client()
                with client.session_transaction() as session:session['authenticated']=True;session['csrf']='bench'
                requests=0;server_ms=0;download=0
                def request(method,path,**kwargs):
                    global requests,server_ms,download
                    kwargs['headers']={'Accept-Encoding':'gzip',**kwargs.get('headers',{})}
                    t=time.perf_counter();reply=getattr(client,method)(path,**kwargs);server_ms+=(time.perf_counter()-t)*1000;requests+=1;download+=len(reply.data);assert reply.status_code==200,(reply.status_code,reply.data[:200]);return json.loads(gzip.decompress(reply.data) if reply.headers.get('Content-Encoding')=='gzip' else reply.data)
                request('get','/api/view');request('get','/api/save');revision=s.revision;continuation=None
                while True:
                    p=request('post','/api/settle',json={'protocol_version':1,'save_id':s.save_id,'generation':s.generation,'expected_revision':revision,'request_id':str(uuid4()),'continuation':continuation},headers={'X-CSRF-Token':'bench'})
                    r=p['receipt'];revision=r['committed_revision'];continuation=r['result']['continuation']
                    if mode=='before':
                        request('get','/api/view');request('get','/api/save')
                    elif not continuation:request('get','/api/save')
                    if not continuation:break
                row=dict(mode=mode,hours=hours,requests=requests,server_ms=round(server_ms,3),download_bytes=download,engine_ms=round(engine_ms,3),processed_events=events,event_ms=round(engine_ms/events,4) if events else 0)
                rows.append(row);(ROOT/'benchmark-results.json').write_text(json.dumps(rows,indent=2));print(json.dumps(row),flush=True)
finally:f.doCleanups()

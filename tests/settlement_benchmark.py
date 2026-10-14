"""Opt-in isolated HTTP benchmark. Reads a detached fixture; never a live database.
Usage: PYTHONPATH=. .venv/bin/python tests/settlement_benchmark.py before|after --fixture FILE
Before samples five rounds and is an estimate, after drains the fixed one-hour target.
All SQLite writes use an automatically deleted V2 .tmp directory. No network/phone RTT.
"""
import sys,json,time,tempfile,statistics,sqlite3,types
from pathlib import Path
from contextlib import contextmanager,ExitStack
from unittest.mock import patch
from src.core.state.envelope import StateEnvelope
from src.data.dungeons.definitions import load_dungeons
from src.core.save.sqlite import SQLiteSave
from src.core.time.model import Continuation
from src.application.economy_settlement import EconomySettlement
from tests.fixtures.settlement_legacy import legacy_advance,legacy_freeze_json,legacy_thaw_json
from tests.fixtures.time import ManualClock
from tools.playable.game import PROJECT,game_factory
from src.transport.danding import create_app
from src.rendering.game import present
from src.rendering.game_runtime import GameRuntimeAssets
import argparse
parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('mode',choices=('before','after'));parser.add_argument('--fixture',type=Path,required=True);parser.add_argument('--historical-loot',action='store_true',help='Use the frozen loot pointers from the original 1980-event benchmark');args=parser.parse_args();mode=args.mode;legacy=mode=='before';fixture=args.fixture;registry=load_dungeons(management=True)
if args.historical_loot:
 from dataclasses import replace
 from types import MappingProxyType
 registry._definitions=MappingProxyType({k:replace(d,display_name='thorn-loot-v2' if k.machine_id=='thorn_path' else k.machine_id+'-loot-v1') if k.domain=='loot' else d for k,d in registry._definitions.items()})
@contextmanager
def baseline():
 with ExitStack() as stack:
  if legacy:
   oldfreeze=legacy_freeze_json;oldthaw=legacy_thaw_json
   from src.core.state import envelope
   oldfreezeref=envelope.freeze_json;oldthawref=envelope.thaw_json
   for module in list(sys.modules.values()):
    if not getattr(module,'__name__','').startswith('src.'):continue
    for name,value in list(vars(module).items()):
     if value is oldfreezeref:stack.enter_context(patch.object(module,name,oldfreeze))
     elif value is oldthawref:stack.enter_context(patch.object(module,name,oldthaw))
   stack.enter_context(patch.object(EconomySettlement,'advance',legacy_advance))
  yield
with baseline():
 state=StateEnvelope.from_dict(json.loads(fixture.read_text()));clock=ManualClock(state.time['last_settled_at_ms']+3600000)
 with tempfile.TemporaryDirectory(prefix='http-benchmark-',dir=PROJECT/'.tmp') as directory:
  root=Path(directory);db=root/'benchmark.sqlite3';base=game_factory(db,root,clock,registry=registry);engine=[]
  with SQLiteSave.initialize(db,allowed_root=root):pass
  with base() as game:game.create(state)
  @contextmanager
  def measured():
   with base() as game:
    if legacy:game.settlement_max_events=32
    advance=game.engine.advance
    def timed(*args,**kwargs):
     start=time.perf_counter();result=advance(*args,**kwargs);engine.append((time.perf_counter()-start)*1000);return result
    game.engine.advance=timed;yield game
  assets=GameRuntimeAssets(PROJECT/'assets');web=create_app(measured,state.save_id,lambda v:present(v,assets),assets.file,'isolated-benchmark-token-00000000',secure=False,cookie_path='/');client=web.test_client()
  with client.session_transaction() as session:session['authenticated']=True;session['csrf']='benchmark-csrf'
  revision=state.revision;continuation=None;settles=[];views=[];events=[];sim=[];complete=False;started=time.perf_counter()
  import uuid
  while not complete:
   body={'protocol_version':1,'save_id':state.save_id,'generation':state.generation,'expected_revision':revision,'request_id':str(uuid.uuid4()),'continuation':continuation}
   start=time.perf_counter();reply=client.post('/api/settle',json=body,headers={'X-CSRF-Token':'benchmark-csrf'});settles.append((time.perf_counter()-start)*1000);assert reply.status_code==200,reply.status_code
   data=reply.get_json();receipt=data['receipt'];result=receipt['result'];revision=receipt['committed_revision'];continuation=result['continuation'];events.append(len(result['processed_events']));sim.append((result['to_sim_ms']-result['from_sim_ms'])/1000);complete=result['status']=='COMPLETE'
   if legacy or complete:
    start=time.perf_counter();reply=client.get('/api/view');views.append((time.perf_counter()-start)*1000);assert reply.status_code==200,reply.status_code
   if len(settles)%10==0:print('progress',mode,len(settles),sum(sim),flush=True)
   if legacy and len(settles)>=5:break
  wall=time.perf_counter()-started
  with base() as game:final=game.query(state.save_id).to_dict()

  def summary(values):return {'min':round(min(values),2),'median':round(statistics.median(values),2),'max':round(max(values),2)} if values else None
  report={'mode':mode,'rounds':len(settles),'total_wall_seconds':round(wall,3),'events':sum(events),'complete':complete,'engine_ms':summary(engine),'settle_ms':summary(settles),'view_ms':summary(views),'events_per_round':summary(events),'simulation_seconds_per_round':summary(sim),'view_requests':len(views),'amortized_engine_ms':round(sum(engine)/sum(events),3) if sum(events) else 0,'amortized_http_ms':round(sum(settles)/sum(events),3) if sum(events) else 0}
  print(json.dumps(report),flush=True)

"""One actual wall-clock pause/restart/resume acceptance, isolated V2 Save only."""
import unittest,tempfile,time,sys,subprocess,json
from pathlib import Path
from uuid import uuid4
from src.application.world import WorldApplication
from src.application.danding import initial_slice,target
from src.application.memory import Command
from src.application.settlement import SettlementRequest
from src.core.time.clock import SystemClock
from src.core.save.sqlite import SQLiteSave,V2_ROOT
from src.data.cultivation.definitions import load_cultivation
class WorldRealtimeTests(unittest.TestCase):
 def test_actual30second_pause_subprocess_and_exact_resume_delivery(self):
  with tempfile.TemporaryDirectory(dir=V2_ROOT/'.tmp') as tmp:
   root=Path(tmp);path=root/'test.sqlite3';r=load_cultivation();clock=SystemClock();s=initial_slice(r,last_settled_at_ms=clock.now_ms())
   with SQLiteSave.initialize(path,allowed_root=root) as store:
    a=WorldApplication(store,r,clock);a.create(s)
    def command(name,payload={}):
     st=a.query(s.save_id);return a.execute(Command(st.save_id,st.generation,st.revision,str(uuid4()),name,payload))
    command('alchemy_start',{'building_id':target(s),'recipe_id':'pill'});time.sleep(10);command('world_pause');remaining=a.view(s.save_id)['alchemy']['current']['remaining_ms'];self.assertGreater(remaining,17000);self.assertLessEqual(remaining,20000);paused=a.query(s.save_id);time.sleep(30);self.assertEqual(a.query(s.save_id),paused)
    script="""from pathlib import Path
import sys,json
from src.core.save.sqlite import SQLiteSave
from src.application.world import WorldApplication
from src.data.cultivation.definitions import load_cultivation
from src.core.time.clock import SystemClock
p=Path(sys.argv[1])
with SQLiteSave(p,allowed_root=p.parent) as store:
 v=WorldApplication(store,load_cultivation(),SystemClock()).view(sys.argv[2]);print(json.dumps({'paused':v['world']['paused'],'remaining':v['alchemy']['current']['remaining_ms']}))
"""
    result=json.loads(subprocess.check_output([sys.executable,'-B','-c',script,str(path),s.save_id],cwd=V2_ROOT));self.assertEqual(result,{'paused':True,'remaining':remaining});command('world_resume');self.assertEqual(a.view(s.save_id)['alchemy']['current']['remaining_ms'],remaining);time.sleep(remaining/1000+.05)
    before=a.view(s.save_id)['holdings'].get('pill',{}).get('quantity',0)
    for _ in range(2):
     st=a.query(s.save_id);a.settle(SettlementRequest(st.save_id,st.generation,st.revision,str(uuid4()),32,None))
    self.assertEqual(a.view(s.save_id)['holdings']['pill']['quantity'],before+1)

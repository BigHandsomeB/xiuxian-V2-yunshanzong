"""Explicit content upgrade compatibility on isolated SQLite, never a live save."""
import unittest,tempfile
from pathlib import Path
from dataclasses import replace
from uuid import uuid4
from unittest.mock import patch
from src.application.danding import initial_slice
from src.application.dungeons import DungeonApplication
from src.application.sect_management import ManagementApplication
from src.application.sect_management_upgrade import upgrade
from src.application.memory import Command
from src.application.settlement import SettlementRequest
from src.application import equipment as equip
from src.core.save.sqlite import SQLiteSave,V2_ROOT
from src.core.state.envelope import thaw_json
from src.core.time.model import Continuation
from src.data.dungeons.definitions import load_dungeons
from src.systems.sect import management
from tests.fixtures.time import ManualClock

class UpgradeTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(dir=V2_ROOT/'tests');self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.path=self.root/'test.sqlite3';self.old=load_dungeons();self.new=load_dungeons(management=True);self.clock=ManualClock()
 def create(self,paused=False):
  s=initial_slice(self.old,last_settled_at_ms=self.clock.now_ms());self.sid=s.save_id
  s,i=equip.acquire(s,self.old,'thorn_fang_blade','old-frozen-roll',roll_version='thorn-roll-v2');s=replace(s,time={**s.time,'world_paused':paused})
  with SQLiteSave.initialize(self.path,allowed_root=self.root) as store:DungeonApplication(store,self.old,self.clock).create(s)
 def q(self,s):return Command(s.save_id,s.generation,s.revision,str(uuid4()),'sect_management_content_upgrade',{})
 def preserved(self,before,after):
  self.assertEqual(before.domains,{k:v for k,v in after.domains.items() if k!='sect_management'});self.assertEqual(before.identity,after.identity)
  bt=thaw_json(before.time);at=thaw_json(after.time)
  if at['pending']:at['pending']['revision']=bt['pending']['revision']
  self.assertEqual(bt,at);self.assertEqual(after.domains['sect_management'],management.initial(self.new))
 def test_paused_upgrade_existing_jobs_gear_people_no_changes(self):
  self.create(paused=True)
  with SQLiteSave(self.path,allowed_root=self.root) as store:
   old=DungeonApplication(store,self.old,self.clock);before=old.query(self.sid);base=old.player_projection(before);r=upgrade(store,self.clock,self.q(before));new=ManagementApplication(store,self.new,self.clock);after=new.query(self.sid);self.preserved(before,after);self.assertEqual(base,new.player_projection(after));self.assertTrue(after.time['world_paused']);new.view(self.sid);self.assertEqual(after,new.query(self.sid));self.assertEqual(r.result['status'],'UPGRADED')
 def test_pending_upgrade_rollback_replay_and_settlement(self):
  self.create()
  with SQLiteSave(self.path,allowed_root=self.root) as store:
   old=DungeonApplication(store,self.old,self.clock);self.clock.advance(120000);s=old.query(self.sid);old.settle(SettlementRequest(self.sid,s.generation,s.revision,str(uuid4()),1,None));before=old.query(self.sid);self.assertIsNotNone(before.time['pending']);q=self.q(before)
   with patch.object(store,'commit',side_effect=RuntimeError('rollback')):
    with self.assertRaises(RuntimeError):upgrade(store,self.clock,q)
   self.assertEqual(store.inspect(self.sid,include_recovery=False).current,before);r=upgrade(store,self.clock,q);self.assertEqual(upgrade(store,self.clock,q),r);new=ManagementApplication(store,self.new,self.clock);after=new.query(self.sid);self.preserved(before,after)
   for _ in range(50):
    s=new.query(self.sid)
    if not s.time['pending']:break
    new.settle(SettlementRequest(self.sid,s.generation,s.revision,str(uuid4()),32,Continuation.for_state(s)))
   self.assertIsNone(new.query(self.sid).time['pending']);new.view(self.sid)
 def test_monsters_equipment_ranges_and_drops_frozen(self):
  for key,row in self.old._definitions.items():
   if key.domain in ('encounters','equipment','equipment_rolls','dungeons','dungeon_loot'):self.assertEqual(row,self.new.lookup(key))
  from src.data.dungeons import loot,expeditions
  from src.systems.dungeons import progress
  for did in ('thorn_path',*expeditions.IDS):
   for floor in (1,10,100):
    eid=progress.definition(self.old,did).encounters[floor-1];b={'encounter_id':eid,'battle_id':'preserved-drop-salt'}
    if did!='thorn_path':b['loot_version']=expeditions.content(did)['loot']['version']
    else:b['loot_version']='thorn-loot-v2'
    self.assertEqual(loot.plan(self.old,b),loot.plan(self.new,b))

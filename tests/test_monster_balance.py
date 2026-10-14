"""Versioned scaling, old battle compatibility and pending-safe explicit migration."""
import tempfile,unittest
from pathlib import Path
from uuid import uuid4
from dataclasses import replace
from unittest.mock import patch
from src.application.danding import initial_slice
from src.application.dungeons import DungeonApplication
from src.application.dungeon_balance_upgrade import upgrade,preserved_time
from src.application.memory import Command
from src.application.settlement import SettlementRequest
from src.core.time.model import Continuation
from src.core.save.sqlite import SQLiteSave,V2_ROOT
from src.core.validation import ConflictError
from src.data.dungeons.definitions import load_dungeons
from src.data.dungeons import balance,loot
from src.data.registry import DefinitionKey
from src.systems.dungeons import progress
from src.systems.combat import battle
from tests.fixtures.time import ManualClock

class BalanceTests(unittest.TestCase):
 def test_curve_and_historical_definitions(self):
  new=load_dungeons();old=load_dungeons(balance_legacy=True);package=balance.content()
  for key,v in old._definitions.items():
   if key.domain!='dungeons':self.assertEqual(new.lookup(key),v)
  for name in package['profiles']:
   for tier in package['tiers']:
    values=[balance.stats(package,f,tier,name) for f in range(1,101)]
    for a,b in zip(values,values[1:]):self.assertTrue(all(x<=y for x,y in zip(a,b)))
  d=progress.definition(new)
  for f,eid in enumerate(d.encounters,1):
   e=battle.encounter(new,eid);m=battle.monster(new,e.monster_id);oe=battle.encounter(old,d.legacy_encounters[f-1]);om=battle.monster(old,oe.monster_id)
   self.assertEqual((m.display_name,m.asset_id,m.reward,m.poison_milli),(om.display_name,om.asset_id,om.reward,om.poison_milli))
   b={'battle_id':'fixed','encounter_id':eid,'loot_version':'thorn-loot-v2'}
   self.assertEqual(loot.plan(new,b),loot.plan(old,{**b,'encounter_id':oe.machine_id}))
  boss=battle.monster(new,battle.encounter(new,d.encounters[-1]).monster_id)
  self.assertEqual((boss.base_hp_milli,boss.attack_milli,boss.armor_milli),(377000,26600,5000))
  self.assertEqual(balance.stats(package,1,'normal','荆棘鼠'),(29000,4000,0))
 def test_pending_upgrade_preserves_world_and_continuation(self):
  with tempfile.TemporaryDirectory(dir=V2_ROOT/'tests') as directory:
   root=Path(directory);path=root/'test.sqlite3';clock=ManualClock();old=load_dungeons(balance_legacy=True);new=load_dungeons();s=initial_slice(old,last_settled_at_ms=clock.now_ms())
   with SQLiteSave.initialize(path,allowed_root=root) as st:
    app=DungeonApplication(st,old,clock);app.create(s)
    def command(name,payload):
     state=app.query(s.save_id);return Command(s.save_id,state.generation,state.revision,str(uuid4()),name,payload)
    app.execute(command('dungeon_auto',{'enabled':True,'mode':'farm','floor':1}));clock.advance(20000)
    state=app.query(s.save_id);app.settle(SettlementRequest(s.save_id,state.generation,state.revision,str(uuid4()),1,None))
    before=app.query(s.save_id);self.assertIsNotNone(before.time['pending']);self.assertTrue(before.domains['dungeon']['auto']['enabled'])
    q=Command(s.save_id,before.generation,before.revision,str(uuid4()),'dungeon_balance_upgrade',{})
    with patch.object(st,'commit',side_effect=RuntimeError('injected rollback')):
     with self.assertRaises(RuntimeError):upgrade(st,clock,q)
    self.assertEqual(st.inspect(s.save_id,include_recovery=False).current,before)
    result=upgrade(st,clock,q);self.assertEqual(upgrade(st,clock,q),result)
    app=DungeonApplication(st,new,clock);after=app.query(s.save_id)
    self.assertEqual(preserved_time(before.time),preserved_time(after.time));self.assertEqual(after.time['pending']['revision'],after.revision);self.assertEqual(before.identity,after.identity)
    for k,v in before.domains.items():
     if k!='dungeon':self.assertEqual(v,after.domains[k])
    expected=dict(before.domains['dungeon']);expected['auto']={**expected['auto'],'enabled':False,'wake':None,'tick_ready':False};self.assertEqual(expected,after.domains['dungeon'])
    for _ in range(100):
     state=app.query(s.save_id)
     if not state.time['pending']:break
     app.settle(SettlementRequest(s.save_id,state.generation,state.revision,str(uuid4()),32,Continuation.for_state(state)))
    self.assertIsNone(app.query(s.save_id).time['pending']);self.assertEqual(before.domains['combat'],app.query(s.save_id).domains['combat'])
    with self.assertRaises(ConflictError):app.execute(command('combat_start',{'encounter_id':'thorn_path_001'}))
    bid=after.domains['combat']['battle']['battle_id'];app.execute(command('combat_abandon',{'battle_id':bid}))
    app.execute(command('combat_start',{'encounter_id':'thorn_path_v2_001'}));self.assertEqual(app.query(s.save_id).domains['combat']['battle']['encounter_id'],'thorn_path_v2_001')
if __name__=='__main__':unittest.main()

"""True floor progression, reward atomicity and compatible save preservation."""
import tempfile,unittest
from pathlib import Path
from uuid import uuid4
from dataclasses import replace
from unittest.mock import patch
from src.application.danding import initial_slice
from src.application.dungeons import DungeonApplication
from src.application.item_retirement import RetiredEconomyApplication
from src.application.dungeon_upgrade import upgrade
from src.application.memory import Command
from src.core.save.sqlite import SQLiteSave,V2_ROOT
from src.core.validation import ValidationError,ConflictError
from src.core.state.envelope import thaw_json
from src.data.dungeons.definitions import load_dungeons
from src.data.economy.definitions import load_economy
from src.data.registry import DefinitionKey
from src.systems.dungeons import progress
from src.systems.combat import battle
from src.data.dungeons import durability
from math import ceil
from tests.fixtures.time import ManualClock

class DungeonTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(dir=V2_ROOT/'tests');self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.path=self.root/'save.sqlite3';self.r=load_dungeons();self.clock=ManualClock();s=initial_slice(self.r,last_settled_at_ms=self.clock.now_ms());self.sid=s.save_id
  with SQLiteSave.initialize(self.path,allowed_root=self.root) as st:DungeonApplication(st,self.r,self.clock).create(s)
 def read(self):
  with SQLiteSave(self.path,allowed_root=self.root) as st:return DungeonApplication(st,self.r,self.clock).query(self.sid)
 def q(self,name,payload):
  s=self.read();return Command(s.save_id,s.generation,s.revision,str(uuid4()),name,payload)
 def execute(self,q):
  with SQLiteSave(self.path,allowed_root=self.root) as st:return DungeonApplication(st,self.r,self.clock).execute(q)
 def start(self,f=1):
  r=self.execute(self.q('combat_start',{'encounter_id':progress.definition(self.r).encounters[f-1]}));return r.result['combat']['battle_id']
 def win(self,bid):
  for _ in range(100):
   if self.read().domains['combat']['battle']['status']!='ACTIVE':break
   self.execute(self.q('combat_attack',{'battle_id':bid}))
  self.assertEqual(self.read().domains['combat']['battle']['status'],'PLAYER_WIN')
 def test_all_100_content_floors_and_all_16_assets(self):
  d=progress.definition(self.r);self.assertEqual(len(d.encounters),100);self.assertEqual([d.tiers.count(k) for k in ('normal','elite','boss')],[90,9,1]);assets=set()
  for f,eid in enumerate(d.encounters,1):
   e=battle.encounter(self.r,eid);m=battle.monster(self.r,e.monster_id);assets.add(m.asset_id);self.assertEqual(e.display_name,f'荆棘古道 · 第{f}层');self.assertNotIn('dewleaf',dict(m.reward))
  self.assertEqual(len(assets),16)
 def test_all_old_definitions_identical(self):
  old=load_economy()
  for k,v in old._definitions.items():self.assertEqual(self.r.lookup(k),v)
 def test_ready_get_is_pure_and_defaults_to_first_floor(self):
  before=self.read()
  with SQLiteSave(self.path,allowed_root=self.root) as st:
   g=DungeonApplication(st,self.r,self.clock);v=g.view(self.sid);self.assertEqual(v['combat']['encounter']['id'],'thorn_path_v2_001');self.assertEqual(v['combat']['dungeon']['cleared_floor'],0)
  self.assertEqual(before,self.read())
 def test_future_floor_rejected_and_no_identity_consumed(self):
  before=self.read()
  with self.assertRaises(ConflictError):self.start(2)
  self.assertEqual(before,self.read())
 def test_win_without_claim_does_not_unlock(self):
  b=self.start();self.win(b);self.assertEqual(self.read().domains['dungeon']['cleared_floor'],0)
  with self.assertRaises(ConflictError):self.start(2)
 def test_claim_atomically_grants_unlocks_and_replays(self):
  b=self.start();self.win(b);before=self.read();q=self.q('combat_reward',{'battle_id':b});r=self.execute(q);self.assertEqual(self.execute(q),r);after=self.read()
  self.assertEqual(after.domains['dungeon']['cleared_floor'],1);self.assertEqual(after.domains['inventory']['holdings']['coins']-before.domains['inventory']['holdings'].get('coins',0),before.domains['combat']['battle']['reward']['coins']);self.assertEqual(r.result['combat']['start_encounter_id'],'thorn_path_v2_002')
  q2=self.q('combat_reward',{'battle_id':b});self.execute(q2);self.assertEqual(after,self.read());self.start(2)
 def test_failed_claim_rolls_back_progress_stock_and_receipt(self):
  b=self.start();self.win(b);before=self.read();q=self.q('combat_reward',{'battle_id':b})
  with patch('src.application.economy.operations.grant',side_effect=ValidationError('test failure')):
   with self.assertRaises(ValidationError):self.execute(q)
  self.assertEqual(before,self.read())
  with SQLiteSave(self.path,allowed_root=self.root) as st:self.assertIsNone(st.receipt(self.sid,before.generation,q.request_id))
 def test_quit_does_not_unlock_and_same_floor_retry(self):
  b=self.start();self.execute(self.q('combat_abandon',{'battle_id':b}));self.assertEqual(self.read().domains['dungeon']['cleared_floor'],0);self.start()
 def test_world_pause_blocks_attack_and_start(self):
  self.execute(self.q('world_pause',{}));before=self.read()
  with self.assertRaises(ValidationError):self.start()
  self.assertEqual(before,self.read())
 def test_domain_full_100_clear_with_strong_isolated_snapshot(self):
  p=progress.initial();part=battle.initial();hero=thaw_json(battle.player(self.r,self.sid));hero.update(max_hp_milli=1000000,attack_milli=260000,armor_milli=1000)
  for f,eid in enumerate(progress.definition(self.r).encounters,1):
   part=battle.start(part,self.r,self.sid,'test:'+str(f),eid,player_snapshot=hero)
   for _ in range(100):
    if part['battle']['status']!='ACTIVE':break
    part=battle.attack(part,self.r,self.sid,'test:'+str(f))
   self.assertEqual(part['battle']['status'],'PLAYER_WIN',(f,part['battle']['player_hp_milli']))
   part=battle.reward_settled(part,self.r,self.sid,'test:'+str(f));p=progress.claimed(p,self.r,part['battle']);self.assertEqual(p['cleared_floor'],f)
  self.assertTrue(progress.view(p,self.r)['completed']);self.assertEqual(progress.next_encounter(p,self.r),'thorn_path_v2_100')
 def test_invalid_progress_rejected(self):
  for value in [{'cleared_floor':101},{'cleared_floor':True},{'cleared_floor':-1},{'cleared_floor':0,'extra':1}]:
   with self.assertRaises(ValidationError):progress.validate(value,self.r)
 def test_completed_floor_replay_never_regresses_high_water(self):
  p={**progress.initial(),'cleared_floor':50};b={'encounter_id':'thorn_path_001','status':'SETTLED'};self.assertEqual(progress.claimed(p,self.r,b)['cleared_floor'],50)

 def auto(self,enabled=True,mode='push',floor=1):return self.execute(self.q('dungeon_auto',{'enabled':enabled,'mode':mode,'floor':floor}))
 def settle(self,budget=32):
  from src.application.settlement import SettlementRequest
  from src.core.time.model import Continuation
  with SQLiteSave(self.path,allowed_root=self.root) as st:
   app=DungeonApplication(st,self.r,self.clock);s=app.query(self.sid);q=SettlementRequest(s.save_id,s.generation,s.revision,str(uuid4()),budget,Continuation.for_state(s) if s.time['pending'] else None)
   return app.settle(q),q
 def drain(self,budget=32):
  for _ in range(1000):
   receipt,q=self.settle(budget)
   if receipt.result.status=='COMPLETE':return receipt,q
  self.fail('settlement did not drain')
 def test_auto_policy_is_off_and_get_does_not_farm(self):
  self.assertFalse(self.read().domains['dungeon']['auto']['enabled']);self.auto();before=self.read();self.clock.advance(10000)
  with SQLiteSave(self.path,allowed_root=self.root) as st:DungeonApplication(st,self.r,self.clock).view(self.sid)
  self.assertEqual(before,self.read());self.assertEqual(before.domains['dungeon']['auto']['steps'],0)
 def test_auto_attacks_claims_and_advances_without_manual_commands(self):
  elapsed=20000*ceil(durability.scale(durability.settings()['monster_hp_scale']['normal'],1));self.auto();self.clock.advance(elapsed);receipt,q=self.drain();after=self.read();self.assertEqual(after.domains['dungeon']['auto']['steps'],elapsed//2000);self.assertGreater(after.domains['dungeon']['cleared_floor'],0);self.assertGreater(after.domains['inventory']['holdings']['coins'],0)
  with SQLiteSave(self.path,allowed_root=self.root) as st:self.assertEqual(DungeonApplication(st,self.r,self.clock).settle(q),receipt)
  self.assertEqual(after,self.read())
 def test_pending_one_event_budget_preserves_all_offline_rounds(self):
  self.auto();self.clock.advance(20000);receipt,q=self.settle(1);self.assertEqual(receipt.result.status,'PENDING');self.assertEqual(self.read().domains['dungeon']['auto']['steps'],1);self.drain(1);s=self.read();self.assertEqual(s.domains['dungeon']['auto']['steps'],10);self.assertEqual(s.time['sim_time_ms'],20000)
 def test_repeat_floor_farms_without_unlocking_new_floor(self):
  self.auto(mode='farm');self.clock.advance(40000*ceil(durability.scale(durability.settings()['monster_hp_scale']['normal'],1)));self.drain();s=self.read();self.assertEqual(s.domains['dungeon']['cleared_floor'],1);self.assertGreater(s.domains['dungeon']['auto']['wins'],1);self.assertEqual(s.domains['combat']['battle']['encounter_id'],'thorn_path_v2_001')
 def prepare_range(self):
  for floor in range(1,5):
   bid=self.start(floor);self.win(bid);self.execute(self.q('combat_reward',{'battle_id':bid}))
 def test_farm_range_starts_at_selected_floor_and_wraps_after_claim(self):
  self.prepare_range()
  q=self.q('dungeon_auto',{'enabled':True,'mode':'farm','floor':2,'floor_count':3})
  receipt=self.execute(q);self.assertEqual(self.execute(q),receipt)
  seen=[];last=None
  for _ in range(80):
   self.clock.advance(2000);self.drain(1);s=self.read();b=s.domains['combat']['battle']
   if b['battle_id']!=last:seen.append(progress.floor_of(self.r,b['encounter_id']));last=b['battle_id']
   if len(seen)==7:break
  self.assertEqual(seen,[2,3,4,2,3,4,2]);self.assertEqual(s.domains['dungeon']['cleared_floor'],4)
 def test_farm_range_rejects_uncleared_end_and_invalid_count_atomically(self):
  self.prepare_range();before=self.read()
  for start,count in [(3,3),(2,0),(2,True),(2,1.5),(0,1)]:
   with self.assertRaises(ValidationError):self.execute(self.q('dungeon_auto',{'enabled':True,'mode':'farm','floor':start,'floor_count':count}))
   self.assertEqual(before,self.read())
 def test_farm_range_chunked_and_offline_match_after_restart(self):
  self.prepare_range();self.execute(self.q('dungeon_auto',{'enabled':True,'mode':'farm','floor':2,'floor_count':3}));before=self.read()
  self.clock.advance(40000);self.drain(1);one=self.read()
  path=self.root/'range-clone.sqlite3'
  with SQLiteSave.initialize(path,allowed_root=self.root) as st:DungeonApplication(st,self.r,self.clock).create(before)
  original=self.path;self.path=path
  try:self.drain(32);many=self.read()
  finally:self.path=original
  self.assertEqual(one.domains,many.domains);self.assertEqual(one.identity,many.identity);self.assertEqual(one.time,many.time)

 def test_farm_range_one_layer_repeats_selected_start(self):
  self.prepare_range();self.execute(self.q('dungeon_auto',{'enabled':True,'mode':'farm','floor':3,'floor_count':1}))
  self.clock.advance(40000*ceil(durability.scale(durability.settings()['monster_hp_scale']['normal'],3)));self.drain();s=self.read()
  self.assertEqual(progress.floor_of(self.r,s.domains['combat']['battle']['encounter_id']),3)
  self.assertGreater(s.domains['dungeon']['auto']['wins'],1)

 def test_manual_combat_blocked_while_auto_and_disable_preserves_battle(self):
  self.auto();before=self.read()
  with self.assertRaises(ConflictError):self.start()
  self.assertEqual(before,self.read());self.clock.advance(2000);self.drain();before=self.read();self.auto(False);self.assertEqual(before.domains['combat'],self.read().domains['combat']);self.clock.advance(20000);self.drain();self.assertEqual(before.domains['combat'],self.read().domains['combat'])
 def test_full_storage_stops_with_unclaimed_victory(self):
  self.auto();self.clock.advance(20000*ceil(durability.scale(durability.settings()['monster_hp_scale']['normal'],1)))
  with patch.object(DungeonApplication,'settle_combat_candidate',side_effect=ValidationError('仓库空间不足，战利品等待领取')):self.drain()
  s=self.read();self.assertFalse(s.domains['dungeon']['auto']['enabled']);self.assertEqual(s.domains['dungeon']['auto']['reason'],'STORAGE_FULL');self.assertEqual(s.domains['combat']['battle']['status'],'PLAYER_WIN');self.assertEqual(s.domains['dungeon']['cleared_floor'],0)
  self.auto();self.clock.advance(2000);self.drain();self.assertGreater(self.read().domains['dungeon']['cleared_floor'],0)
 def test_unexpected_reward_failure_rolls_back_entire_settlement(self):
  # Prepare the victory so the injected failure occurs in the first event/transaction.
  bid=self.start();self.win(bid);self.auto();self.clock.advance(2000);before=self.read()
  with patch('src.application.economy.operations.grant',side_effect=ValidationError('unexpected failure')):
   with self.assertRaises(ValidationError):self.settle()
  self.assertEqual(before,self.read())
 def test_pause_freezes_auto_and_resume_ignores_paused_wall_time(self):
  self.auto();self.execute(self.q('world_pause',{}));before=self.read();self.clock.advance(20000)
  with self.assertRaises(ValidationError):self.settle()
  self.assertEqual(before,self.read());self.execute(self.q('world_resume',{}));self.clock.advance(2000);self.drain();self.assertEqual(self.read().domains['dungeon']['auto']['steps'],1)

 def test_enable_after_old_wall_anchor_does_not_retroactively_farm(self):
  self.clock.advance(40000);self.auto();self.drain();self.assertEqual(self.read().domains['dungeon']['auto']['steps'],0);self.clock.advance(2000);self.drain();self.assertEqual(self.read().domains['dungeon']['auto']['steps'],1)
 def test_invalid_policy_and_malformed_envelope_fail_closed(self):
  before=self.read()
  for payload in [{'enabled':True,'mode':'push','floor':2},{'enabled':1,'mode':'push','floor':1},{'enabled':True,'mode':'unknown','floor':1}]:
   with self.assertRaises(ValidationError):self.execute(self.q('dungeon_auto',payload))
  self.assertEqual(before,self.read())
 def test_defeat_stops_and_explicit_restart_allows_retry(self):
  self.auto();self.clock.advance(600000);self.drain();s=self.read();self.assertEqual(s.domains['dungeon']['auto']['reason'],'DEFEATED');self.assertFalse(s.domains['dungeon']['auto']['enabled']);before=s.domains['dungeon']['auto']['steps'];self.clock.advance(20000);self.drain();self.assertEqual(self.read().domains['dungeon']['auto']['steps'],before);self.auto();self.assertIsNone(self.read().domains['combat']['battle'])
 def test_chunked_and_offline_settlement_have_identical_world_content(self):
  self.auto(mode='farm');before=self.read();self.clock.advance(20000);self.drain(1);one=self.read()
  # Isolated clone starts from the exact same identity and auto event allocation.
  path=self.root/'clone.sqlite3'
  with SQLiteSave.initialize(path,allowed_root=self.root) as st:DungeonApplication(st,self.r,self.clock).create(before)
  original=self.path;self.path=path
  try:self.drain(32);many=self.read()
  finally:self.path=original
  self.assertEqual(one.domains,many.domains);self.assertEqual(one.identity,many.identity);self.assertEqual(one.time,many.time)

 def test_server_auto_advanced_realm_requires_gear_at_80_elite(self):
  from src.systems.cultivation import growth
  s=self.read();g=thaw_json(s.domains.get('cultivation',growth.initial(s.save_id)));g.update(current_realm=growth.realm(self.r,g['current_realm']).next_realm_id,growth_revision=1,progress=0)
  path=self.root/'advanced.sqlite3'
  with SQLiteSave.initialize(path,allowed_root=self.root) as st:DungeonApplication(st,self.r,self.clock).create(replace(s,domains={**s.domains,'cultivation':g}))
  original=self.path;self.path=path
  try:
   self.auto();self.clock.advance(2000000);self.drain();after=self.read();self.assertEqual(after.domains['dungeon']['cleared_floor'],79);self.assertEqual(after.domains['dungeon']['auto']['wins'],79);self.assertEqual(after.domains['dungeon']['auto']['reason'],'DEFEATED');self.assertFalse(after.domains['dungeon']['auto']['enabled']);self.assertEqual(after.domains['combat']['battle']['encounter_id'],'thorn_path_v2_080');self.assertEqual(after.domains['combat']['battle']['status'],'PLAYER_LOSE')
  finally:self.path=original

class DungeonUpgradeTests(unittest.TestCase):
 def test_upgrade_preserves_old_battle_world_stock_identity_and_receipts(self):
  with tempfile.TemporaryDirectory(dir=V2_ROOT/'tests') as tmp:
   root=Path(tmp);path=root/'save.sqlite3';old=load_economy();clock=ManualClock();s=initial_slice(old,last_settled_at_ms=clock.now_ms())
   with SQLiteSave.initialize(path,allowed_root=root) as store:
    app=RetiredEconomyApplication(store,old,clock);app.create(s);s=app.query(s.save_id);start=Command(s.save_id,s.generation,s.revision,str(uuid4()),'combat_start',{'encounter_id':'thorn_first'});app.execute(start);before=app.query(s.save_id)
    q=Command(before.save_id,before.generation,before.revision,str(uuid4()),'dungeon_content_upgrade',{});r=upgrade(store,clock,q);self.assertEqual(upgrade(store,clock,q),r)
    app=DungeonApplication(store,load_dungeons(),clock);after=app.query(s.save_id);self.assertEqual(before.time,after.time);self.assertEqual(before.identity,after.identity)
    for k,v in before.domains.items():self.assertEqual(v,after.domains[k])
    self.assertEqual(app.execute(start).result['combat']['battle_id'],before.domains['combat']['battle']['battle_id'])
    self.assertIsNone(app.view(s.save_id)['combat']['dungeon']['current_floor'])

"""Fourth-dungeon gates/rewards/Runtime and additive old-save upgrades, isolated SQLite."""
import hashlib,json,tempfile,unittest
from dataclasses import replace
from pathlib import Path
from uuid import UUID,uuid4
from unittest.mock import patch
from src.application.danding import initial_slice
from src.application.dungeons import DungeonApplication
from src.application.sect_management import ManagementApplication
from src.application.cold_jade_upgrade import upgrade
from src.application.memory import Command
from src.application.settlement import SettlementRequest
from src.application.dungeon_balance_upgrade import preserved_time
from src.application import equipment as equip
from src.core.save.sqlite import SQLiteSave,V2_ROOT
from src.core.save.codec import StoredReceipt
from src.core.state.envelope import thaw_json
from src.core.validation import ValidationError,ConflictError
from src.data.dungeons.definitions import load_dungeons
from src.data.dungeons import expeditions,loot
from src.data.registry import DefinitionKey
from src.systems.dungeons import progress
from src.systems.combat import battle
from src.systems.equipment import items
from src.systems.cultivation import leveling
from tests.fixtures.time import ManualClock
from tests.systems import test_expeditions as helper_module

DID='cold_jade_cave'
class ColdJadeTests(unittest.TestCase):
 create_base=helper_module.ExpeditionTests.create
 read=helper_module.ExpeditionTests.read
 view=helper_module.ExpeditionTests.view
 command=helper_module.ExpeditionTests.command
 execute=helper_module.ExpeditionTests.execute
 select=helper_module.ExpeditionTests.select
 start=helper_module.ExpeditionTests.start
 win=helper_module.ExpeditionTests.win
 settle=helper_module.ExpeditionTests.settle
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(dir=V2_ROOT/'tests');self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.path=self.root/'test.sqlite3';self.r=load_dungeons(cold_jade=True);self.clock=ManualClock();self.sid=None
 def create(self,marsh=100,cold=0,**kwargs):
  self.create_base(mine=100,**kwargs)
  with SQLiteSave(self.path,allowed_root=self.root) as st:
   s=st.inspect(self.sid,include_recovery=False).current
   p=thaw_json(s.domains['dungeon']);p['progress'].update(mist_marsh=marsh)
   if cold:p['progress'][DID]=cold
   candidate=replace(s,revision=s.revision+1,domains={**s.domains,'dungeon':p})
   with st.transaction():st.commit(s,candidate,StoredReceipt(s.save_id,s.generation,str(uuid4()),'0'*64,candidate.revision,'command',{}))
 def test_old_registries_and_rewards_unchanged(self):
  for management in (False,True):
   old=load_dungeons(management=management);new=load_dungeons(management=management,cold_jade=True)
   for key,row in old._definitions.items():self.assertEqual(new.lookup(key),row)
   for did in ('thorn_path',*expeditions.IDS):
    for f in (1,10,100):
     b={'encounter_id':progress.definition(old,did).encounters[f-1],'battle_id':'frozen-old','loot_version':'thorn-loot-v2' if did=='thorn_path' else expeditions.content(did)['loot']['version']}
     self.assertEqual(loot.plan(old,b),loot.plan(new,b))
   self.assertFalse(old.contains(DefinitionKey('dungeons',DID)))
 def test_gate_99_100_and_pure_four_dungeon_directory(self):
  for n in (99,100):
   p={**progress.initial(),'cleared_floor':100,'progress':{'red_copper_mine':100,'mist_marsh':n}}
   self.assertEqual(progress.unlocked(p,self.r,DID),n==100)
  self.create(marsh=99);before=self.read();v=self.view()['combat'];self.assertEqual(len(v['dungeons']),4);self.assertEqual(v['dungeons'][-1]['unlock_condition'],{'dungeon_id':'mist_marsh','cleared_floor':100});self.assertEqual(self.read(),before)
  with self.assertRaises(ConflictError):self.select(DID)
  with self.assertRaises(ConflictError):self.start(DID)
 def test_claim_replay_preserves_other_progress_and_next_preview(self):
  self.create();self.select(DID);bid=self.start(DID);self.win(bid);q=self.command('combat_reward',{'battle_id':bid});receipt=self.execute(q);after=self.read()
  self.assertEqual(self.execute(q),receipt);self.assertEqual(self.read(),after);self.assertEqual(after.domains['dungeon']['progress'],{'red_copper_mine':100,'mist_marsh':100,DID:1});self.assertEqual(after.domains['dungeon']['cleared_floor'],100)
  self.assertEqual(self.view()['combat']['start_encounter_id'],'cold_jade_cave_v1_002');self.select('mist_marsh');self.select(DID);self.assertEqual(self.view()['combat']['dungeon']['cleared_floor'],1)
 def test_active_unclaimed_and_auto_switch_gates(self):
  self.create();self.select(DID);bid=self.start(DID)
  with self.assertRaises(ConflictError):self.select('mist_marsh')
  self.win(bid)
  with self.assertRaises(ConflictError):self.select('mist_marsh')
  self.execute(self.command('combat_reward',{'battle_id':bid}));self.execute(self.command('dungeon_auto',{'enabled':True,'mode':'farm','floor':1}))
  with self.assertRaises(ConflictError):self.select('mist_marsh')
 def test_no_unearned_floor_or_cross_dungeon_roll(self):
  self.create();self.select(DID)
  with self.assertRaises(ConflictError):self.start(DID,2)
  with self.assertRaises(ValidationError):self.execute(self.command('dungeon_auto',{'enabled':True,'mode':'farm','floor':100}))
  with self.assertRaises(ValidationError):items.add(items.initial(),self.r,'unit','cold_jade_cave_equipment_01','frozen',0,False,roll_version='mist_marsh-roll-v1')
 def test_boss_rewards_and_all_equipment_rolls(self):
  d=progress.definition(self.r,DID);p=expeditions.content(DID)
  self.assertEqual(len(d.encounters),100);self.assertEqual(d.tiers.count('elite'),9);self.assertEqual(d.tiers[-1],'boss')
  for i in range(64):
   b={'encounter_id':d.encounters[-1],'battle_id':f'boss:{i}','loot_version':p['loot']['version']};drop=loot.plan(self.r,b)
   for row in p['materials'][-2:]:self.assertEqual(drop['amounts'][row['id']],1)
   self.assertIn(drop['equipment'],[r['id'] for r in p['equipment'][-2:]]);self.assertEqual(drop,loot.plan(self.r,b))
  for row in p['equipment']:
   part=items.add(items.initial(),self.r,'unit',row['id'],'frozen',0,False,roll_version=p['loot']['roll_version']);items.validate(part,self.r,'unit');self.assertFalse(items.unknown(part['instances']['unit'],self.r))
 def test_full_storage_reward_rollback_and_retry(self):
  self.create();self.select(DID);bid=self.start(DID);self.win(bid);before=self.read();q=self.command('combat_reward',{'battle_id':bid})
  with patch('src.application.economy.operations.grant',side_effect=ValidationError('仓库空间不足，战利品等待领取')):
   with self.assertRaises(ValidationError):self.execute(q)
  self.assertEqual(self.read(),before);self.execute(q);self.assertEqual(progress.cleared(self.read().domains['dungeon'],DID),1)
 def test_full_storage_victory_can_exit_without_touching_owned_items(self):
  from src.application import sect
  from src.systems.inventory import holdings,operations
  self.create(gear=True);self.select('red_copper_mine');bid=self.start('red_copper_mine');self.win(bid)
  with SQLiteSave(self.path,allowed_root=self.root) as st:
   s=st.inspect(self.sid,include_recovery=False).current;capacity=sect.capacity_source(s,self.r)['effective'];stock,_=operations.grant(s.domains['inventory'],self.r,{'stone':capacity-holdings.stock_size(s.domains['inventory'],self.r)},capacity=capacity);candidate=replace(s,revision=s.revision+1,domains={**s.domains,'inventory':stock})
   with st.transaction():st.commit(s,candidate,StoredReceipt(s.save_id,s.generation,str(uuid4()),'0'*64,candidate.revision,'command',{}))
  before=self.read()
  with patch('src.data.dungeons.loot.roll',return_value=0):
   with self.assertRaises(ValidationError):self.execute(self.command('combat_reward',{'battle_id':bid}))
  self.assertEqual(self.read(),before);self.assertIn('combat_abandon',self.view()['combat']['available_commands'])
  q=self.command('combat_abandon',{'battle_id':bid});receipt=self.execute(q);after=self.read();self.assertEqual(self.execute(q),receipt);self.assertEqual(self.read(),after)
  b=after.domains['combat']['battle'];self.assertEqual((b['status'],b['reward_state'],dict(b['reward'])),('ABANDONED','NONE',{}));self.assertEqual(after.identity,before.identity);self.assertEqual(after.time,before.time)
  self.assertEqual({k:v for k,v in after.domains.items() if k!='combat'},{k:v for k,v in before.domains.items() if k!='combat'});self.assertFalse(self.view()['combat']['reward'])
  with self.assertRaises(ValidationError):self.execute(self.command('combat_reward',{'battle_id':bid}))
  self.assertEqual(self.read(),after);self.select('mist_marsh');self.assertEqual(self.view()['combat']['dungeon']['id'],'mist_marsh')
 def test_unclaimed_exit_rollback_stale_request_and_claimed_rejection(self):
  self.create();self.select(DID);bid=self.start(DID);self.win(bid);before=self.read();q=self.command('combat_abandon',{'battle_id':bid})
  with SQLiteSave(self.path,allowed_root=self.root) as st:
   with patch.object(st,'commit',side_effect=RuntimeError('injected rollback')):
    with self.assertRaises(RuntimeError):DungeonApplication(st,self.r,self.clock).execute(q)
  self.assertEqual(self.read(),before)
  with self.assertRaises(ConflictError):self.execute(replace(q,expected_revision=q.expected_revision-1))
  self.assertEqual(self.read(),before);self.execute(self.command('combat_reward',{'battle_id':bid}));settled=self.read()
  self.assertNotIn('combat_abandon',self.view()['combat']['available_commands'])
  with self.assertRaises(ValidationError):self.execute(self.command('combat_abandon',{'battle_id':bid}))
  self.assertEqual(self.read(),settled)
 def test_auto_push_and_last_floor_stop(self):
  # Fixed legal win/loss fixtures test auto termination, not Boss balance.
  original=(self.path,self.clock,self.sid)
  try:
   cases=(('00000000-0000-4000-8000-000000000002',100,'COMPLETED','SETTLED',1),
          ('00000000-0000-4000-8000-000000000001',99,'DEFEATED','PLAYER_LOSE',0))
   for seed,floor,reason,status,wins in cases:
    with self.subTest(seed=seed,reason=reason):
     self.path=self.root/(seed+'.sqlite3');self.clock=ManualClock()
     with patch('src.core.state.envelope.uuid4',return_value=UUID(seed)):
      self.create(cold=99,gear=True)
     self.select(DID)
     with SQLiteSave(self.path,allowed_root=self.root) as st:
      app=DungeonApplication(st,self.r,self.clock);before=app.query(self.sid);candidate=before
      for index in (11,3,5,12,9,10):
       candidate,identity=equip.acquire(candidate,self.r,f'cold_jade_cave_equipment_{index:02d}','auto-boss-fixture',roll_version='cold_jade_cave-roll-v1')
       candidate=replace(candidate,domains={**candidate.domains,'equipment':items.equip(equip.equipment(candidate),self.r,identity,False)})
      c=leveling.config(self.r);grown=leveling.normalized(candidate.domains['cultivation'],self.r,self.sid)
      grown['total_xp']=leveling.table(c)[1000]
      # Unrelated production must not allocate Job IDs ahead of the seeded battle.
      automatic=thaw_json(candidate.domains['automation'])
      for row in automatic['production'].values():row['enabled']=False
      candidate=replace(candidate,revision=before.revision+1,domains={**candidate.domains,'cultivation':grown,'automation':automatic})
      candidate=app.engine.wake(candidate)
      app.foundation.validate_state(candidate)
      self.assertFalse(candidate.domains['production']['jobs'])
      self.assertEqual(leveling.level(grown,c),1000)
      saved=thaw_json(candidate.domains['equipment']['instances'])
      with st.transaction():st.commit(before,candidate,StoredReceipt(before.save_id,before.generation,str(uuid4()),'0'*64,candidate.revision,'command',{}))
     self.execute(self.command('dungeon_auto',{'enabled':True,'mode':'push','floor':1}))
     self.clock.advance(120000);self.settle();after=self.read();auto=after.domains['dungeon']['auto']
     self.assertEqual(progress.cleared(after.domains['dungeon'],DID),floor)
     self.assertEqual((auto['reason'],auto['wins']),(reason,wins))
     self.assertFalse(auto['enabled']);self.assertIsNone(auto['wake'])
     self.assertEqual(after.domains['combat']['battle']['encounter_id'],'cold_jade_cave_v1_100')
     self.assertEqual(after.domains['combat']['battle']['battle_id'],f"{seed}:1:i:{candidate.identity['instance_counter']+1}")
     self.assertFalse(after.domains['production']['jobs'])
     self.assertEqual(after.domains['combat']['battle']['status'],status)
     for identity,row in saved.items():
      self.assertEqual(after.domains['equipment']['instances'][identity]['stats'],row['stats'])
      self.assertEqual(after.domains['equipment']['instances'][identity].get('roll_version'),row.get('roll_version'))
     self.view();self.assertEqual(self.read(),after)
  finally:self.path,self.clock,self.sid=original
 def test_runtime_and_bindings_no_missing_assets(self):
  from src.rendering.game import _battle,bindings,_icon
  from src.rendering.game_runtime import GameRuntimeAssets
  assets=GameRuntimeAssets(V2_ROOT/'assets');snapshot=assets.snapshot();p=expeditions.content(DID);b=bindings()
  for row in (*p['materials'],*p['equipment']):self.assertEqual(b['icons'][row['id']],row['asset_id']);self.assertFalse(_icon(row['asset_id'],assets,snapshot)['fallback'])
  for identity in ('cold_jade_ore','ice_crystal_ore'):self.assertFalse(_icon(b['icons'][identity],assets,snapshot)['fallback'])
  self.assertFalse(_icon(b['system_icons']['dungeon_'+DID],assets,snapshot)['fallback'])
  for row in p['monsters']:
   v={'player':{'asset_id':'player.combat.hero'},'enemy':{'asset_id':row['asset_id']},'encounter':{'background_asset_id':p['background_asset_id']}};rendered=_battle(assets,snapshot,v,b)
   self.assertIsNotNone(rendered['background']);self.assertFalse(rendered['enemy']['fallback']);self.assertTrue(rendered['sprites'][row['asset_id']]['static'])
   for f in snapshot[row['asset_id']]['files']:self.assertEqual(hashlib.sha256((V2_ROOT/'assets'/f['file']).read_bytes()).hexdigest(),f['sha256'])
 def test_authenticated_http_gate_selection_and_replay(self):
  from contextlib import contextmanager
  from src.transport.danding import create_app
  self.create(marsh=99)
  @contextmanager
  def application():
   with SQLiteSave(self.path,allowed_root=self.root) as st:yield DungeonApplication(st,self.r,self.clock)
  app=create_app(application,self.sid,lambda v:{},lambda *args:None,'test-only-cold-jade-token',secure=False,cookie_path='/');client=app.test_client();client.post('/login',data={'token':'test-only-cold-jade-token'});v=client.get('/api/view').json;s=v['view']
  body={'protocol_version':1,'save_id':self.sid,'generation':s['generation'],'expected_revision':s['revision'],'request_id':str(uuid4()),'command':{'name':'dungeon_select','version':1,'payload':{'dungeon_id':DID}}};headers={'X-CSRF-Token':v['csrf'],'Origin':'http://localhost'}
  self.assertEqual(client.post('/api/command',json=body).status_code,403)
  self.assertEqual(client.post('/api/command',json=body,headers=headers).status_code,409)
  body['command']['payload']['dungeon_id']='mist_marsh';body['request_id']=str(uuid4());r=client.post('/api/command',json=body,headers=headers);self.assertEqual(r.status_code,200);self.assertEqual(client.post('/api/command',json=body,headers=headers).json,r.json)
  with SQLiteSave(self.path,allowed_root=self.root) as st:
   before=st.inspect(self.sid,include_recovery=False).current;p=thaw_json(before.domains['dungeon']);p['progress']['mist_marsh']=100;candidate=replace(before,revision=before.revision+1,domains={**before.domains,'dungeon':p})
   with st.transaction():st.commit(before,candidate,StoredReceipt(before.save_id,before.generation,str(uuid4()),'0'*64,candidate.revision,'command',{}))
  body.update(expected_revision=candidate.revision,request_id=str(uuid4()));body['command']['payload']['dungeon_id']=DID;r=client.post('/api/command',json=body,headers=headers);self.assertEqual(r.status_code,200);self.assertEqual(client.get('/api/view').json['view']['combat']['dungeon']['id'],DID);self.assertEqual(client.post('/api/command',json=body,headers=headers).json,r.json)

class ColdJadeUpgradeTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(dir=V2_ROOT/'tests');self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.path=self.root/'test.sqlite3';self.clock=ManualClock()
 def check_upgrade(self,management=False,pending=False,paused=False,active=False):
  old=load_dungeons(management=management);new=load_dungeons(management=management,cold_jade=True);app_class=ManagementApplication if management else DungeonApplication
  s=initial_slice(old,last_settled_at_ms=self.clock.now_ms());s=replace(s,time={**s.time,'world_paused':paused})
  s,identity=equip.acquire(s,old,'mist_marsh_equipment_01','saved-old-roll',roll_version='mist_marsh-roll-v1')
  with SQLiteSave.initialize(self.path,allowed_root=self.root) as st:
   app=app_class(st,old,self.clock);app.create(s)
   if active:
    s=app.query(s.save_id);d={**s.domains['dungeon'],'cleared_floor':100,'progress':{'red_copper_mine':100,'mist_marsh':1},'selected_id':'mist_marsh'};candidate=replace(s,revision=s.revision+1,domains={**s.domains,'dungeon':d})
    with st.transaction():st.commit(s,candidate,StoredReceipt(s.save_id,s.generation,str(uuid4()),'0'*64,candidate.revision,'command',{}))
    app.execute(Command(s.save_id,s.generation,candidate.revision,str(uuid4()),'combat_start',{'encounter_id':'mist_marsh_v1_002'}))
   if pending:
    self.clock.advance(120000);s=app.query(s.save_id);app.settle(SettlementRequest(s.save_id,s.generation,s.revision,str(uuid4()),1,None))
   before=app.query(s.save_id);q=Command(s.save_id,s.generation,before.revision,str(uuid4()),'cold_jade_content_upgrade',{})
   if pending:self.assertIsNotNone(before.time['pending'])
   with patch.object(st,'commit',side_effect=RuntimeError('rollback')):
    with self.assertRaises(RuntimeError):upgrade(st,self.clock,q)
   self.assertEqual(st.inspect(s.save_id,include_recovery=False).current,before)
   receipt=upgrade(st,self.clock,q);self.assertEqual(upgrade(st,self.clock,q),receipt);after=app_class(st,new,self.clock).query(s.save_id)
   self.assertEqual(after.domains,before.domains);self.assertEqual(after.identity,before.identity);self.assertEqual(preserved_time(after.time),preserved_time(before.time));self.assertEqual(after.content_version,new.content_version)
   self.assertEqual(dict(after.domains['equipment']['instances'][identity]),dict(before.domains['equipment']['instances'][identity]))
   if pending:self.assertEqual(after.time['pending']['revision'],after.revision)
   fresh=Command(s.save_id,s.generation,after.revision,str(uuid4()),'cold_jade_content_upgrade',{});self.assertEqual(upgrade(st,self.clock,fresh).result['status'],'ALREADY_UPGRADED')
   app_class(st,new,self.clock).view(s.save_id)
   if pending:
    from src.core.time.model import Continuation
    app=app_class(st,new,self.clock)
    for _ in range(50):
     current=app.query(s.save_id)
     if not current.time['pending']:break
     app.settle(SettlementRequest(s.save_id,s.generation,current.revision,str(uuid4()),32,Continuation.for_state(current)))
    self.assertIsNone(app.query(s.save_id).time['pending'])
 def test_expedition_upgrade_paused_and_frozen_gear(self):self.check_upgrade(paused=True)
 def test_management_upgrade_paused_and_frozen_gear(self):self.check_upgrade(management=True,paused=True)
 def test_management_upgrade_pending_rollback_and_replay(self):self.check_upgrade(management=True,pending=True)
 def test_management_upgrade_preserves_active_third_battle(self):self.check_upgrade(management=True,active=True)
 def test_reject_stale_generation_revision_and_wrong_intent(self):
  r=load_dungeons(management=True);s=initial_slice(r,last_settled_at_ms=self.clock.now_ms())
  with SQLiteSave.initialize(self.path,allowed_root=self.root) as st:
   app=ManagementApplication(st,r,self.clock);app.create(s);s=app.query(s.save_id)
   for generation,revision in ((s.generation+1,s.revision),(s.generation,s.revision+1)):
    with self.assertRaises(ConflictError):upgrade(st,self.clock,Command(s.save_id,generation,revision,str(uuid4()),'cold_jade_content_upgrade',{}))
   with self.assertRaises(ValidationError):upgrade(st,self.clock,Command(s.save_id,s.generation,s.revision,str(uuid4()),'cold_jade_content_upgrade',{'unexpected':True}))
   self.assertEqual(app.query(s.save_id),s)

"""Real SQLite multi-dungeon gates, transactions, compatible snapshots and bounded auto."""
import json,tempfile,unittest,time
from math import ceil
from src.data.dungeons import durability
from pathlib import Path
from dataclasses import replace
from uuid import uuid4
from unittest.mock import patch
from src.application.danding import initial_slice
from src.application.dungeons import DungeonApplication
from src.application.memory import Command
from src.application.settlement import SettlementRequest
from src.application.expedition_upgrade import upgrade
from src.application import equipment as equip
from src.core.save.sqlite import SQLiteSave,V2_ROOT
from src.core.state.envelope import thaw_json
from src.core.validation import ValidationError,ConflictError
from src.data.dungeons.definitions import load_dungeons
from src.data.dungeons import expeditions,loot
from src.data.registry import DefinitionKey
from src.systems.dungeons import progress
from src.systems.combat import battle
from src.systems.equipment import items
from src.systems.cultivation import growth
from tests.fixtures.time import ManualClock

class ExpeditionTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(dir=V2_ROOT/'tests');self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.path=self.root/'test.sqlite3';self.r=load_dungeons();self.clock=ManualClock();self.sid=None
 def create(self,*,registry=None,thorn=100,mine=0,paused=False,gear=False):
  r=registry or self.r;s=initial_slice(r,last_settled_at_ms=self.clock.now_ms());self.sid=s.save_id
  g=s.domains.get('cultivation',growth.initial(s.save_id))
  g={**g,'current_realm':'realm_1','progress':0,'growth_revision':1}
  p={**progress.initial(),'cleared_floor':thorn}
  if mine:p['progress']={'red_copper_mine':mine}
  s=replace(s,domains={**s.domains,'dungeon':p,'cultivation':g},time={**s.time,'world_paused':paused})
  if gear:
   for row in loot.content()['equipment']:
    if not row['boss_only']:continue
    s,identity=equip.acquire(s,r,row['id'],'fixture-old-boss',roll_version='thorn-roll-v2');e=items.equip(equip.equipment(s),r,identity,False);s=replace(s,domains={**s.domains,'equipment':e})
  with SQLiteSave.initialize(self.path,allowed_root=self.root) as st:DungeonApplication(st,r,self.clock).create(s)
  return s
 def read(self):
  with SQLiteSave(self.path,allowed_root=self.root) as st:return DungeonApplication(st,self.r,self.clock).query(self.sid)
 def view(self):
  with SQLiteSave(self.path,allowed_root=self.root) as st:return DungeonApplication(st,self.r,self.clock).view(self.sid)
 def command(self,name,payload):
  s=self.read();return Command(s.save_id,s.generation,s.revision,str(uuid4()),name,payload)
 def execute(self,q):
  with SQLiteSave(self.path,allowed_root=self.root) as st:return DungeonApplication(st,self.r,self.clock).execute(q)
 def select(self,did):return self.execute(self.command('dungeon_select',{'dungeon_id':did}))
 def start(self,did='red_copper_mine',floor=1):return self.execute(self.command('combat_start',{'encounter_id':progress.definition(self.r,did).encounters[floor-1]})).result['combat']['battle_id']
 def win(self,bid):
  for _ in range(100):
   if self.read().domains['combat']['battle']['status']!='ACTIVE':break
   self.execute(self.command('combat_attack',{'battle_id':bid}))
  self.assertEqual(self.read().domains['combat']['battle']['status'],'PLAYER_WIN')
 def settle(self,budget=32):
  with SQLiteSave(self.path,allowed_root=self.root) as st:
   app=DungeonApplication(st,self.r,self.clock);s=app.query(self.sid)
   from src.core.time.model import Continuation
   return app.settle(SettlementRequest(s.save_id,s.generation,s.revision,str(uuid4()),budget,Continuation.for_state(s) if s.time['pending'] else None))
 def test_all_thorn_definitions_and_old_drop_salts_unchanged(self):
  old=load_dungeons(expansion_legacy=True)
  for key,d in old._definitions.items():
   if key==DefinitionKey('loot','thorn_path'):
    self.assertEqual(self.r.lookup(key).references,d.references);self.assertEqual(self.r.lookup(key).display_name,'thorn-loot-v2')
   else:self.assertEqual(self.r.lookup(key),d)
  for floor in (1,10,99,100):
   b={'encounter_id':progress.definition(old).encounters[floor-1],'battle_id':'frozen','loot_version':'thorn-loot-v2'};self.assertEqual(loot.plan(old,b),loot.plan(self.r,b))
 def test_unlock_99_100_and_directory_read_defaults(self):
  for floor in (99,100):
   p={**progress.initial(),'cleared_floor':floor};self.assertEqual(progress.unlocked(p,self.r,'red_copper_mine'),floor==100)
   for mine in (99,100):
    q={**p,'cleared_floor':100,'progress':{'red_copper_mine':mine}};self.assertEqual(progress.unlocked(q,self.r,'mist_marsh'),mine==100)
  self.create(thorn=99);before=self.read();v=self.view()['combat'];self.assertEqual([d['cleared_floor'] for d in v['dungeons']],[99,0,0]);self.assertEqual(before,self.read())
  with self.assertRaises(ConflictError):self.select('red_copper_mine')
 def test_manual_claim_advances_only_selected_dungeon_and_replays(self):
  self.create();q=self.command('dungeon_select',{'dungeon_id':'red_copper_mine'});receipt=self.execute(q);self.assertEqual(self.execute(q),receipt)
  bid=self.start();self.win(bid);q=self.command('combat_reward',{'battle_id':bid});receipt=self.execute(q);after=self.read();self.assertEqual(self.execute(q),receipt);self.assertEqual(self.read(),after)
  self.assertEqual(after.domains['dungeon']['cleared_floor'],100);self.assertEqual(after.domains['dungeon']['progress']['red_copper_mine'],1);self.assertNotIn('mist_marsh',after.domains['dungeon']['progress'])
 def test_third_dungeon_claim_and_next_floor_preview(self):
  self.create(mine=100);self.select('mist_marsh');bid=self.start('mist_marsh');self.win(bid);self.execute(self.command('combat_reward',{'battle_id':bid}));v=self.view()['combat'];self.assertEqual(v['dungeon']['cleared_floor'],1);self.assertTrue(v['start_encounter_id'].startswith('mist_marsh_'))
  self.select('red_copper_mine');v=self.view()['combat'];self.assertEqual(v['status'],'READY');self.assertEqual(v['dungeon']['cleared_floor'],100);self.assertTrue(v['encounter']['id'].startswith('red_copper_mine_'))
 def test_start_cannot_bypass_selected_or_floor_gate(self):
  self.create()
  with self.assertRaises(ConflictError):self.start()
  self.select('red_copper_mine')
  with self.assertRaises(ConflictError):self.start(floor=2)
  with self.assertRaises(ConflictError):self.start('mist_marsh')
 def test_switch_blocks_active_unclaimed_and_auto(self):
  self.create(mine=100);self.select('red_copper_mine');bid=self.start()
  with self.assertRaises(ConflictError):self.select('mist_marsh')
  self.win(bid)
  with self.assertRaises(ConflictError):self.select('mist_marsh')
  self.execute(self.command('combat_reward',{'battle_id':bid}));self.execute(self.command('dungeon_auto',{'enabled':True,'mode':'farm','floor':1}))
  with self.assertRaises(ConflictError):self.select('mist_marsh')
 def test_selected_auto_claims_only_its_progress_and_pauses(self):
  self.create();self.select('red_copper_mine');self.execute(self.command('dungeon_auto',{'enabled':True,'mode':'push','floor':1}));self.clock.advance(12000*ceil(durability.scale(durability.settings()['monster_hp_scale']['normal'],1)));self.settle();s=self.read();self.assertGreater(s.domains['dungeon']['progress'].get('red_copper_mine',0),0);self.assertEqual(s.domains['dungeon']['cleared_floor'],100);self.assertTrue(s.domains['combat']['battle']['encounter_id'].startswith('red_copper_mine_'))
  
  while self.read().time['pending']:self.settle()
  self.execute(self.command('world_pause',{}));before=self.read();self.clock.advance(60000)
  with self.assertRaises(ValidationError):self.settle()
  self.assertEqual(self.read(),before)
  with self.assertRaises(ValidationError):self.select('thorn_path')
 def test_farm_floor_uses_selected_high_water(self):
  self.create();self.select('red_copper_mine')
  with self.assertRaises(ValidationError):self.execute(self.command('dungeon_auto',{'enabled':True,'mode':'farm','floor':100}))
 def test_claim_rolls_back_if_equipment_acquisition_fails(self):
  self.create(mine=100,gear=True);self.select('red_copper_mine')
  # All Bosses necessarily include one of the registered exclusive equipment items.
  with SQLiteSave(self.path,allowed_root=self.root) as st:
   app=DungeonApplication(st,self.r,self.clock);s=app.query(self.sid);eid=progress.definition(self.r,'red_copper_mine').encounters[-1]
   part=battle.start(battle.initial(),self.r,self.sid,f'{self.sid}:1:i:{s.identity["instance_counter"]+1}',eid,player_snapshot=app.player_projection(s));b=thaw_json(part['battle']);b.update(status='PLAYER_WIN',enemy_hp_milli=0,reward_state='READY',reward=dict(battle.monster(self.r,b['enemy_id']).reward))
   candidate=replace(s,revision=s.revision+1,identity={**s.identity,'instance_counter':s.identity['instance_counter']+1},domains={**s.domains,'combat':{'battle':b}});app.foundation.validate_state(candidate)
   from src.core.save.codec import StoredReceipt
   with st.transaction():st.commit(s,candidate,StoredReceipt(s.save_id,s.generation,str(uuid4()),'0'*64,candidate.revision,'command',{}))
  q=self.command('combat_reward',{'battle_id':b['battle_id']});before=self.read()
  with patch('src.application.equipment.acquire',side_effect=ValidationError('injected acquire failure')):
   with self.assertRaises(ValidationError):self.execute(q)
  self.assertEqual(self.read(),before)
  self.execute(q);self.assertEqual(self.read().domains['dungeon']['progress']['red_copper_mine'],100)
 def test_full_storage_stops_auto_without_granting_or_advancing(self):
  self.create();self.select('red_copper_mine');bid=self.start();self.win(bid);before=self.read()
  with patch('src.application.economy.operations.grant',side_effect=ValidationError('仓库空间不足，战利品等待领取')):
   with self.assertRaises(ValidationError):self.execute(self.command('combat_reward',{'battle_id':bid}))
  self.assertEqual(self.read(),before);self.execute(self.command('dungeon_auto',{'enabled':True,'mode':'push','floor':1}));self.clock.advance(2000)
  with patch('src.application.economy.operations.grant',side_effect=ValidationError('仓库空间不足，战利品等待领取')):self.settle()
  state=self.read();self.assertEqual(state.domains['dungeon']['auto']['reason'],'STORAGE_FULL');self.assertEqual(state.domains['combat']['battle']['status'],'PLAYER_WIN');self.assertEqual(progress.cleared(state.domains['dungeon'],'red_copper_mine'),0)
 def test_http_selection_csrf_replay_and_server_only_gate(self):
  self.create();from contextlib import contextmanager
  from src.transport.danding import create_app
  @contextmanager
  def application():
   with SQLiteSave(self.path,allowed_root=self.root) as store:yield DungeonApplication(store,self.r,self.clock)
  app=create_app(application,self.sid,lambda v:{},lambda *args:None,'test-only-expeditions-auth-token',secure=False,cookie_path='/game/');app.config['SESSION_COOKIE_PATH']='/';client=app.test_client();client.post('/login',data={'token':'test-only-expeditions-auth-token'})
  view=client.get('/api/view').json;s=view['view'];body={'protocol_version':1,'save_id':self.sid,'generation':s['generation'],'expected_revision':s['revision'],'request_id':str(uuid4()),'command':{'name':'dungeon_select','version':1,'payload':{'dungeon_id':'red_copper_mine'}}}
  self.assertEqual(client.post('/api/command',json=body).status_code,403)
  headers={'X-CSRF-Token':view['csrf'],'Origin':'http://localhost'};r=client.post('/api/command',json=body,headers=headers);self.assertEqual(r.status_code,200);self.assertEqual(client.post('/api/command',json=body,headers=headers).json,r.json)
  body['request_id']=str(uuid4());body['expected_revision']=self.read().revision;body['command']['payload']['dungeon_id']='mist_marsh';self.assertEqual(client.post('/api/command',json=body,headers=headers).status_code,409)
  self.assertEqual(client.get('/api/view').json['view']['combat']['dungeon']['id'],'red_copper_mine')
 def test_background_and_static_runtime_resolution_for_both_dungeons(self):
  from src.rendering.game_runtime import GameRuntimeAssets
  from src.rendering.game import _battle,bindings
  assets=GameRuntimeAssets(V2_ROOT/'assets');snapshot=assets.snapshot()
  for did in expeditions.IDS:
   p=expeditions.content(did)
   for m in p['monsters']:
    v={'player':{'asset_id':'player.combat.hero'},'enemy':{'asset_id':m['asset_id']},'encounter':{'background_asset_id':p['background_asset_id']}}
    rendered=_battle(assets,snapshot,v,bindings());self.assertIsNotNone(rendered['background']);self.assertFalse(rendered['enemy']['fallback']);self.assertTrue(rendered['sprites'][m['asset_id']]['static'])
 def test_registered_equipment_rolls_and_protection(self):
  for did in expeditions.IDS:
   for row in expeditions.content(did)['equipment']:
    version=expeditions.content(did)['loot']['roll_version'];p=items.add(items.initial(),self.r,'unit',row['id'],'fixed',0,False,roll_version=version);items.validate(p,self.r,'unit');self.assertFalse(items.unknown(p['instances']['unit'],self.r));self.assertEqual(p['instances']['unit']['stats'],items.rolled_stats(items.definition(self.r,row['id']),'fixed',version))
    protected=items.flag(p,'unit','locked',True)
    with self.assertRaises(ValidationError):items.remove(protected,self.r,'unit')
 def test_version_is_bound_to_dungeon_and_roll_pool(self):
  hero=battle.player(self.r,'unit');eid=progress.definition(self.r,'red_copper_mine').encounters[0];part=battle.start(battle.initial(),self.r,'unit','fixed',eid,player_snapshot=hero)
  for version in (None,'thorn-loot-v2','mist_marsh-loot-v1'):
   b=thaw_json(part['battle']);b.pop('loot_version') if version is None else b.update(loot_version=version)
   with self.assertRaises(ValidationError):battle.validate({'battle':b},self.r,'unit')
  with self.assertRaises(ValidationError):items.add(items.initial(),self.r,'unit','red_copper_mine_equipment_01','fixed',0,False,roll_version='mist_marsh-roll-v1')
 def test_pending_upgrade_preserves_all_authority_and_replay(self):
  old=load_dungeons(expansion_legacy=True);self.create(registry=old,gear=True)
  with SQLiteSave(self.path,allowed_root=self.root) as st:
   app=DungeonApplication(st,old,self.clock);s=app.query(self.sid);app.execute(Command(self.sid,s.generation,s.revision,str(uuid4()),'dungeon_auto',{'enabled':True,'mode':'farm','floor':1}));self.clock.advance(12000);s=app.query(self.sid);app.settle(SettlementRequest(self.sid,s.generation,s.revision,str(uuid4()),1,None));before=app.query(self.sid);self.assertIsNotNone(before.time['pending']);q=Command(self.sid,before.generation,before.revision,str(uuid4()),'expedition_content_upgrade',{})
   with patch.object(st,'commit',side_effect=RuntimeError('rollback')):
    with self.assertRaises(RuntimeError):upgrade(st,self.clock,q)
   self.assertEqual(st.inspect(self.sid,include_recovery=False).current,before)
   result=upgrade(st,self.clock,q);self.assertEqual(upgrade(st,self.clock,q),result);after=DungeonApplication(st,self.r,self.clock).query(self.sid);self.assertEqual(after.domains,before.domains);self.assertEqual(after.identity,before.identity);self.assertEqual(after.time['pending']['revision'],after.revision)
  self.settle();self.assertEqual(self.read().content_version,self.r.content_version)
 def test_mixed_old_and_new_equipment_snapshots_survive_later_growth(self):
  self.create(mine=100,gear=True)
  with SQLiteSave(self.path,allowed_root=self.root) as st:
   app=DungeonApplication(st,self.r,self.clock);old=app.query(self.sid);saved_old=thaw_json(equip.equipment(old)['instances'])
   for did in expeditions.IDS:
    s=old
    for row in expeditions.content(did)['equipment']:
     if row['boss_only'] or row['slot']=='left':continue
     s,identity=equip.acquire(s,self.r,row['id'],'mixed-fixture',roll_version=expeditions.content(did)['loot']['roll_version']);s=replace(s,domains={**s.domains,'equipment':items.equip(equip.equipment(s),self.r,identity,False)})
    p=progress.choose(s.domains['dungeon'],self.r,did);counter=s.identity['instance_counter']+1
    part=battle.start(battle.initial(),self.r,self.sid,f'{self.sid}:1:i:{counter}',progress.definition(self.r,did).encounters[0],player_snapshot=app.player_projection(s));candidate=replace(s,identity={**s.identity,'instance_counter':counter},domains={**s.domains,'dungeon':p,'combat':part});app.foundation.validate_state(candidate)
    later={**candidate.domains['cultivation'],'progress':4000};app.foundation.validate_state(replace(candidate,domains={**candidate.domains,'cultivation':later}))
    for identity,row in saved_old.items():self.assertEqual(candidate.domains['equipment']['instances'][identity]['stats'],row['stats'])
 def test_persisted_active_battle_cannot_be_from_another_selected_dungeon(self):
  self.create();self.start('thorn_path');s=self.read();p=progress.choose(s.domains['dungeon'],self.r,'red_copper_mine')
  with SQLiteSave(self.path,allowed_root=self.root) as st:
   with self.assertRaises(ValidationError):DungeonApplication(st,self.r,self.clock).foundation.validate_state(replace(s,domains={**s.domains,'dungeon':p}))
  self.assertEqual(self.read(),s)
 def test_same_selection_new_request_is_a_receipted_noop(self):
  self.create();self.select('red_copper_mine');before=self.read();q=self.command('dungeon_select',{'dungeon_id':'red_copper_mine'});receipt=self.execute(q);self.assertEqual(self.read(),before);self.assertEqual(self.execute(q),receipt)
 def test_new_content_assets_exist_and_thorn_snapshot_validator_is_bounded(self):
  root=V2_ROOT/'assets';manifest=json.loads((root/'manifest.json').read_text())['assets']
  for did in expeditions.IDS:
   p=expeditions.content(did)
   for aid in [p['background_asset_id'],*[r['asset_id'] for r in (*p['monsters'],*p['materials'],*p['equipment'])]]:
    self.assertIn(aid,manifest);self.assertTrue(all((root/f['file']).is_file() for f in manifest[aid]['files']))
  self.create(gear=True);s=self.read();defs=tuple((d.slot,d.stats,d.stat_ranges) for d in self.r._definitions.values() if isinstance(d,equip.EquipmentDefinition));self.assertLess(len(equip.projection_groups(defs)),7)
 def test_invalid_progress_and_commands_fail_without_mutation(self):
  self.create();before=self.read()
  for p in [{'progress':{'red_copper_mine':101}},{'progress':{'mist_marsh':1}},{'selected_id':'mist_marsh'},{'progress':{'unknown':0}}]:
   with self.assertRaises((ValidationError,ConflictError)):progress.validate({**before.domains['dungeon'],**p},self.r)
  for value in (None,[],False,1):
   with self.assertRaises(ValidationError):self.execute(self.command('dungeon_select',{'dungeon_id':value}))
  self.assertEqual(self.read(),before)

if __name__=='__main__':unittest.main()

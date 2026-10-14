"""Hard parity gates against frozen pre-compression battle and original event scheduler."""
import csv,hashlib,json,tempfile,unittest,os
from contextlib import nullcontext
from tests.fixtures.settlement_work_reference import original_work
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from src.core.state.envelope import thaw_json
from src.core.time.model import Continuation
from src.core.save.sqlite import SQLiteSave,V2_ROOT
from src.application.sect_management import ManagementApplication
from src.application.settlement import SettlementRequest
from src.systems.combat import battle
from src.systems.equipment import items
from src.systems.economy import policy
from src.data.dungeons import loot
from src.data.dungeons.definitions import load_dungeons
from tests.fixtures import combat_original
from tests.systems.test_settlement_batch import SettlementBatchTests


def digest(state):
    d=state.to_dict();d.pop('revision')
    def clean(v):
        if isinstance(v,dict):return {k:clean(x) for k,x in v.items() if k not in ('latest_events','completed_revision')}
        if isinstance(v,list):return [clean(x) for x in v]
        return v
    return hashlib.sha256(json.dumps(clean(d),sort_keys=True).encode()).hexdigest()

class CompressionGateTests(unittest.TestCase):
    def test_6528_fights_outcomes_loot_rewards_and_random_equipment(self):
        registry=load_dungeons(management=True)
        spec=(V2_ROOT/'docs/economy-export/baseline-spec.md').read_text()
        players=json.loads(spec.split('```json\n')[1].split('```')[0])
        cases=list(csv.DictReader((V2_ROOT/'docs/economy-export/combat-baseline-cases.csv').read_text().splitlines()[1:]))
        self.assertEqual(len(cases),6528)
        mismatches=0
        for row in cases:
            seed=battle.start(battle.initial(),registry,'design',row['battle_id'],f"thorn_path_v2_{int(row['floor']):03}",player_snapshot=players[row['loadout']])
            old=seed
            while old['battle']['status']=='ACTIVE':old=combat_original.attack(old,registry,'design',row['battle_id'])
            new,_,_=battle.result_only(seed,registry,'design')
            a=thaw_json(old['battle']);b=thaw_json(new['battle']);a.pop('latest_events');b.pop('latest_events')
            x=loot.plan(registry,a) if a['status']=='PLAYER_WIN' else None;y=loot.plan(registry,b) if b['status']=='PLAYER_WIN' else None
            if x and x['equipment']:
                da=items.definition(registry,x['equipment']);db=items.definition(registry,y['equipment'])
                x={**x,'stats':items.rolled_stats(da,a['battle_id']),'affixes':items.rolled_affixes(da,a['battle_id'])}
                y={**y,'stats':items.rolled_stats(db,b['battle_id']),'affixes':items.rolled_affixes(db,b['battle_id'])}
            mismatches+=int(a!=b or x!=y)
        print(f'GATE fights=6528 mismatches={mismatches}',flush=True)
        self.assertEqual(mismatches,0)

    def fixture(self):
        f=SettlementBatchTests();f.setUp();self.addCleanup(f.doCleanups);return f

    def scenario(self,f,mode):
        s=f.state
        auto=thaw_json(s.domains['automation']);auto['production']={k:{**r,'enabled':False} for k,r in auto['production'].items()};auto['wake']=None
        s=replace(s,domains={**s.domains,'automation':auto})
        if mode=='production':
            d=thaw_json(s.domains['dungeon']);d['auto'].update(enabled=False,wake=None,tick_ready=False);s=replace(s,domains={**s.domains,'dungeon':d})
        if mode in ('production','both'):
            for kind,recipe in (('garden','grain'),('forest','wood')):
                building=next(k for k,r in s.domains['sect']['buildings'].items() if r['definition_id']==kind)
                s=f.app.start_candidate(s,building,recipe)
                a=policy.set_production(s.domains['automation'],f.registry,building,{'enabled':True,'recipe_id':recipe,'target':10000,'reserves':{},'max_consumption':10000})
                s=replace(s,domains={**s.domains,'automation':a})
        if mode in ('overflow_on','overflow_off'):
            from src.data.economy.sect_rules import settings
            inv=thaw_json(s.domains['inventory']);inv['holdings'].update({k:v for k,v in settings(f.registry)['material_caps'].items() if k.startswith('thorn_')})
            auto=thaw_json(s.domains['automation']);auto['material_overflow']=mode=='overflow_on'
            s=replace(s,domains={**s.domains,'inventory':inv,'automation':auto})
        if mode=='full':
            inv=thaw_json(s.domains['inventory']);inv['holdings']={'grain':f.app._capacity(s)}
            s=replace(s,domains={**s.domains,'inventory':inv})
        if mode=='defeat':
            d=thaw_json(s.domains['dungeon']);d['cleared_floor']=100;d['auto'].update(floor=100,floor_count=1,next_floor=100)
            s=replace(s,domains={**s.domains,'dungeon':d})
        return f.app.engine.wake(s)

    def drain(self,f,s,hours,compressed,batch=4096):
        f.app.engine.result_path=compressed
        target=s.time['last_settled_at_ms']+hours*3600000
        with patch.object(battle,'attack',combat_original.attack), (original_work() if not compressed and os.environ.get('SETTLEMENT_REFERENCE_WORK')=='1' else nullcontext()):
            for _ in range(10000):
                s,r=f.app.engine.advance(s,max_events=batch,now_ms=None if s.time['pending'] else target,continuation=Continuation.for_state(s) if s.time['pending'] else None)
                if not s.time['pending']:return s
        self.fail('not drained')

    def test_1h_8h_final_state_hashes_and_chunk_resume(self):
        f=self.fixture();count=0
        for mode in ('production','both','full','defeat','overflow_on','overflow_off'):
            start=self.scenario(f,mode)
            for hours in (1,8):
                a=self.drain(f,start,hours,False);b=self.drain(f,start,hours,True)
                count+=1
                print(f'GATE {mode} {hours}h {digest(a)} {digest(b)}',flush=True)
                self.assertEqual(digest(a),digest(b),(mode,hours))
                if mode=='defeat':self.assertEqual(b.domains['dungeon']['auto']['reason'],'DEFEATED')
                if mode=='full':self.assertEqual(b.domains['dungeon']['auto']['reason'],'STORAGE_FULL')
                if mode=='overflow_on':self.assertTrue(b.domains['automation']['overflow_log'])
                if mode=='overflow_off':self.assertFalse(b.domains['automation']['overflow_log'])
        start=self.scenario(f,'both');a=self.drain(f,start,1,True);b=self.drain(f,start,1,True,batch=3)
        self.assertEqual(digest(a),digest(b));print(f'GATE windows={count} mismatches=0 resume=PASS',flush=True)

    def test_old_wake_without_interval_preserves_speed_and_time(self):
        f=self.fixture();s=self.scenario(f,'combat');n=s.identity['instance_counter']+1;identity=f'{s.save_id}:1:i:{n}'
        eq=thaw_json(items.add(s.domains['equipment'],f.registry,identity,'thorn_moss_boots','legacy-fixture',0,False))
        eq['instances'][identity]['equipped']=True;eq['slots']['feet']=identity
        dungeon=thaw_json(s.domains['dungeon']);dungeon['auto']['wake'].pop('interval_ms',None)
        start=replace(s,identity={**s.identity,'instance_counter':n},domains={**s.domains,'equipment':eq,'dungeon':dungeon})
        f.app.engine.result_path=False
        a,r=f.app.engine.advance(start,max_events=4096,now_ms=121000)
        f.app.engine.result_path=True
        b,r=f.app.engine.advance(start,max_events=4096,now_ms=121000)
        self.assertEqual(digest(a),digest(b))

    def test_pause_resume_1h_8h(self):
        from src.core.time import world
        f=self.fixture()
        for hours in (1,8):
            start=self.scenario(f,'both');paused=replace(start,time=world.pause(start.time))
            for compressed in (False,True):
                f.app.engine.result_path=compressed
                with self.assertRaises(world.WorldPaused):f.app.engine.advance(paused,max_events=4096,now_ms=1000+hours*3600000)
                self.assertEqual(digest(paused),digest(replace(start,time=world.pause(start.time))))
            resumed=replace(paused,time=world.resume(paused.time,1000+hours*3600000))
            a=self.drain(f,resumed,hours,False);b=self.drain(f,resumed,hours,True)
            print(f'GATE pause_resume {hours}h {digest(a)} {digest(b)}',flush=True)
            self.assertEqual(digest(a),digest(b))

    def test_compressed_replay_restart_and_atomic_rollback(self):
        f=self.fixture()
        for hours in (1,8):
            start=self.scenario(f,'both');target=start.time['last_settled_at_ms']+hours*3600000
            f.clock.advance(target-f.clock.now_ms())
            expected=self.drain(f,start,hours,False);once=self.drain(f,start,hours,True)
            self.assertEqual(digest(expected),digest(once))
            with tempfile.TemporaryDirectory(dir=V2_ROOT/'.tmp') as directory:
                root=Path(directory);path=root/'gate.sqlite3'
                with SQLiteSave.initialize(path,allowed_root=root) as store:ManagementApplication(store,f.registry,f.clock).create(start)
                replay_count=0
                for _ in range(10000):
                    with SQLiteSave(path,allowed_root=root) as store:
                        app=ManagementApplication(store,f.registry,f.clock);s=app.query(start.save_id)
                        q=SettlementRequest(s.save_id,s.generation,s.revision,str(uuid4()),128,Continuation.for_state(s) if s.time['pending'] else None)
                        if replay_count==0:
                            with patch.object(store,'_insert_receipt',side_effect=RuntimeError('rollback')):
                                with self.assertRaises(RuntimeError):app.settle(q)
                            self.assertEqual(app.query(s.save_id),s)
                        receipt=app.settle(q);after=app.query(s.save_id)
                        self.assertEqual(app.settle(q),receipt);self.assertEqual(app.query(s.save_id),after);replay_count+=1
                    if not after.time['pending']:break
                else:self.fail('restart did not complete')
                print(f'GATE replay_restart {hours}h replays={replay_count} {digest(once)} {digest(after)}',flush=True)
                self.assertEqual(digest(after),digest(once))

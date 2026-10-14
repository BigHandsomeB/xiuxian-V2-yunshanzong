"""New loot transactions, combat effects, historical compatibility and upgrade."""
import unittest,tempfile
from pathlib import Path
from dataclasses import replace
from uuid import uuid4
from unittest.mock import patch
from src.application.danding import initial_slice
from src.application.dungeons import DungeonApplication
from src.application.dungeon_loot_upgrade import upgrade
from src.application import equipment as equip
from src.application.memory import Command
from src.data.dungeons.definitions import load_dungeons
from src.data.dungeons import loot
from src.data.registry import DefinitionKey
from src.core.save.sqlite import SQLiteSave,V2_ROOT
from src.core.state.envelope import thaw_json,freeze_json
from src.core.validation import ValidationError
from src.systems.combat import battle,equipment_effects as effects
from src.systems.equipment import items
from src.systems.economy import policy
from src.systems.dungeons import progress
from src.application.dungeon_settlement import DungeonSettlement
from tests.fixtures.time import ManualClock
from tests.systems import test_dungeons as dungeon_fixtures

class LootTests(unittest.TestCase):
    setUp=dungeon_fixtures.DungeonTests.setUp
    read=dungeon_fixtures.DungeonTests.read
    q=dungeon_fixtures.DungeonTests.q
    execute=dungeon_fixtures.DungeonTests.execute
    start=dungeon_fixtures.DungeonTests.start
    win=dungeon_fixtures.DungeonTests.win
    def test_drop_pools_and_replay(self):
        normal_ids={r['id'] for r in loot.content()['equipment'] if not r['boss_only']}
        boss_ids={r['id'] for r in loot.content()['equipment'] if r['boss_only']}
        counts={'normal':0,'elite':0}
        for index in range(2000):
            for tier,floor in [('normal',1),('elite',10),('boss',100)]:
                b={'battle_id':f'fixture:1:i:{index}','encounter_id':f'thorn_path_{floor:03d}','loot_version':'thorn-loot-v1'}
                a=loot.plan(self.r,b);self.assertEqual(a,loot.plan(self.r,b))
                if tier=='boss':
                    self.assertIn(a['equipment'],boss_ids);self.assertEqual(a['amounts'],{'thorn_king_tusk':1,'thorn_king_core':1})
                elif a['equipment']:
                    self.assertIn(a['equipment'],normal_ids);counts[tier]+=1
        self.assertTrue(230<counts['normal']<370)
        self.assertTrue(900<counts['elite']<1100)
        self.assertEqual(loot.plan(self.r,{'battle_id':'old','encounter_id':'thorn_path_100'})['equipment'],None)

    def test_reward_atomic_storage_retry_and_unique_instance(self):
        found=False
        for _ in range(30):
            bid=self.start();self.win(bid);before=self.read();drop=loot.plan(self.r,before.domains['combat']['battle'])
            if not drop['equipment']:
                self.execute(self.q('combat_reward',{'battle_id':bid}));continue
            found=True;q=self.q('combat_reward',{'battle_id':bid})
            with patch('src.application.dungeons.sect.capacity_source',return_value={'effective':0}):
                with self.assertRaises(ValidationError):self.execute(q)
            self.assertEqual(self.read(),before)
            with patch('src.application.dungeons.equip.acquire',side_effect=ValidationError('isolated acquire failure')):
                with self.assertRaises(ValidationError):self.execute(q)
            self.assertEqual(self.read(),before)
            receipt=self.execute(q);after=self.read()
            self.assertEqual(receipt,self.execute(q));self.assertEqual(after,self.read())
            self.assertEqual(equip.count(after),equip.count(before)+1)
            marker=equip.equipment(after)['latest_reward'];self.assertEqual(marker['definition_id'],drop['equipment'])
            for key,n in drop['amounts'].items():self.assertEqual(after.domains['inventory']['holdings'].get(key,0)-before.domains['inventory']['holdings'].get(key,0),n)
            self.execute(self.q('equipment_equip',{'instance_id':marker['instance_id']}))
            self.start();self.read() # Snapshot validation accepts real new gear.
            break
        self.assertTrue(found)

    def test_special_effects_and_caps(self):
        base=dict(battle.player(self.r,'effects'))
        base.update(crit_bps=3000,pierce_milli=2000,reflect_bps=3500,poison_resist_bps=7500,accuracy_bps=1000,evasion_bps=2500)
        part=battle.start(battle.initial(),self.r,'effects','effects:1:i:1','thorn_path_009',player_snapshot=base)
        # Deterministic forced critical/no evasion to check armor piercing and poison.
        with patch('src.systems.combat.equipment_effects.roll',side_effect=lambda b,s:9000 if s=='enemy_hit' else 0):
            out=battle.attack(part,self.r,'effects','effects:1:i:1')
        events=out['battle']['latest_events'];self.assertIn('critical',[e['kind'] for e in events])
        self.assertEqual(next(e['formula_damage_milli'] for e in events if e['kind']=='damage' and e['actor']=='player'),15000)
        self.assertIn('miss',[e['kind'] for e in events])
        poison_part=battle.start(battle.initial(),self.r,'effects','effects:1:i:2','thorn_path_008',player_snapshot=base)
        with patch('src.systems.combat.equipment_effects.roll',side_effect=lambda b,s:0 if s=='critical' else 5000):
            out=battle.attack(poison_part,self.r,'effects','effects:1:i:2')
        events=out['battle']['latest_events'];self.assertIn('reflect',[e['kind'] for e in events]);self.assertEqual(next(e['formula_damage_milli'] for e in events if e['kind']=='poison'),500)
        self.assertEqual(effects.interval({'speed_bps':1000}),1818)
        with self.assertRaises(ValidationError):battle.validate_player_input({**base,'evasion_bps':2600},self.r,'effects')

    def test_explicit_upgrade_preserves_existing_battle(self):
        old=load_dungeons(legacy=True)
        with tempfile.TemporaryDirectory(dir=V2_ROOT/'tests') as directory:
            root=Path(directory);path=root/'old.sqlite3';clock=ManualClock();s=initial_slice(old,last_settled_at_ms=clock.now_ms())
            with SQLiteSave.initialize(path,allowed_root=root) as store:
                app=DungeonApplication(store,old,clock);app.create(s)
                app.execute(Command(s.save_id,s.generation,s.revision,str(uuid4()),'combat_start',{'encounter_id':'thorn_path_001'}))
                before=app.query(s.save_id);q=Command(s.save_id,before.generation,before.revision,str(uuid4()),'dungeon_loot_upgrade',{})
                r=upgrade(store,clock,q);after=DungeonApplication(store,self.r,clock).query(s.save_id)
                self.assertEqual(before.domains,after.domains);self.assertEqual(before.time,after.time);self.assertEqual(before.identity,after.identity)
                self.assertEqual(r,upgrade(store,clock,q));self.assertEqual(loot.plan(self.r,after.domains['combat']['battle'])['equipment'],None)

    def test_speed_and_offline_budget_independent(self):
        with SQLiteSave(self.path,allowed_root=self.root) as store:
            app=DungeonApplication(store,self.r,self.clock);s=app.query(self.sid)
            s,i=equip.acquire(s,self.r,'thorn_moss_boots','isolated fixture')
            s=equip.command(s,self.r,'equipment_equip',{'instance_id':i})
            p=progress.set_auto(s.domains['dungeon'],self.r,True,'farm',1)
            s=replace(s,domains={**s.domains,'dungeon':p})
            engine=DungeonSettlement(app);s=engine.wake(s)
            self.assertEqual(s.domains['dungeon']['auto']['wake']['due_ms']-s.time['sim_time_ms'],1818)
            def run(budget):
                result=s
                for _ in range(100):
                    from src.core.time.model import Continuation
                    result,receipt=engine.advance(result,max_events=budget,now_ms=self.clock.now_ms()+20000,continuation=Continuation.for_state(result) if result.time['pending'] else None)
                    if receipt.status=='COMPLETE':return result
                self.fail('offline fixture did not finish')
            one,many=run(1),run(32)
            self.assertEqual(one.domains,many.domains)
            self.assertEqual(one.identity,many.identity)
            self.assertEqual(one.domains['dungeon']['auto']['steps'],11)

if __name__=='__main__':unittest.main()

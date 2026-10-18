"""Forging guarantees use isolated SQLite and actual command/HTTP paths."""
import tempfile
import unittest
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from src.application.danding import initial_slice
from src.application.ecology import EcologyApplication
from src.application.memory import Command
from src.application.sect_economy import craft_cost,craft_gate
from src.core.save.sqlite import SQLiteSave,V2_ROOT
from src.core.state.envelope import thaw_json
from src.core.validation import ValidationError
from src.data.dungeons.definitions import load_dungeons
from src.systems.equipment import items
from tests.fixtures.time import ManualClock


class ForgedBladeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=V2_ROOT/'tests')
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.db=self.root/'forge.sqlite3'
        self.r=load_dungeons(management=True,cold_jade=True,ecology=True)
        self.clock=ManualClock();self.counter=0
        self.store=SQLiteSave.initialize(self.db,allowed_root=self.root)
        self.addCleanup(self.store.close)
        self.app=EcologyApplication(self.store,self.r,self.clock)
        s=initial_slice(self.r,last_settled_at_ms=1000);self.sid=s.save_id
        stock=thaw_json(s.domains['inventory'])
        stock['holdings'].update(coins=3000,ingot=100,thorn_boar_bone=100)
        self.app.create(replace(s,domains={**s.domains,'inventory':stock}))

    def state(self):return self.app.query(self.sid)
    def request(self,name,payload):
        s=self.state();self.counter+=1
        return Command(self.sid,s.generation,s.revision,str(UUID(int=self.counter,version=4)),name,payload)
    def craft(self):
        q=self.request('equipment_craft',{'equipment_id':'thorn_fang_blade'})
        return q,self.app.execute(q)

    def test_only_blade_fee_changes_and_sale_stays_180(self):
        self.assertEqual(craft_cost(self.r,'thorn_fang_blade'),{'ingot':15,'thorn_boar_bone':15,'coins':300})
        self.assertEqual(craft_cost(self.r,'thorn_rock_staff')['coins'],1500)
        self.assertEqual(items.sale_price(self.r,'thorn_fang_blade'),180)

    def test_forging_uses_guaranteed_ranges_and_existing_affixes(self):
        d=items.definition(self.r,'thorn_fang_blade')
        version=craft_gate(self.state(),self.r,d.machine_id)
        self.assertEqual(version,'thorn-forge-v1')
        outcomes=set()
        for n in range(64):
            p=items.add(items.initial(),self.r,'save:1:i:1',d.machine_id,f'forge:{n}',0,False,roll_version=version,combat_affix=True)
            row=p['instances']['save:1:i:1'];items.validate(p,self.r,'save')
            self.assertIn(row['stats']['attack_milli'],(6000,7000))
            self.assertIn(row['stats']['crit_bps'],(500,600))
            self.assertTrue(items.known_affixes(row,d));self.assertFalse(items.unknown(row,self.r))
            outcomes.add(tuple(sorted(row['stats'].items())))
        self.assertEqual(len(outcomes),4)

    def test_drop_and_old_rolls_stay_byte_for_byte(self):
        import hashlib
        d=items.definition(self.r,'thorn_fang_blade');seen=set()
        for n in range(64):
            provenance=f'old-drop:{n}';expected={}
            for key,low,high,step in d.stat_ranges:
                seed=f'{provenance}|{d.machine_id}|thorn-roll-v2|{key}'
                value=int.from_bytes(hashlib.sha256(seed.encode()).digest()[:8],'big')
                expected[key]=low+value%((high-low)//step+1)*step
            old=items.add(items.initial(),self.r,'save:1:i:1',d.machine_id,provenance,0,False,roll_version='thorn-roll-v2')
            self.assertEqual(dict(old['instances']['save:1:i:1']['stats']),expected)
            items.validate(old,self.r,'save');seen.add(expected['attack_milli'])
        self.assertIn(5000,seen)
        legacy=items.add(items.initial(),self.r,'save:1:i:1',d.machine_id,'legacy',0,False)
        items.validate(legacy,self.r,'save');self.assertNotIn('roll_version',legacy['instances']['save:1:i:1'])

    def test_receipt_replay_and_restart_preserve_single_charge(self):
        before=self.state();q,receipt=self.craft();after=self.state()
        for rid,amount in [('coins',300),('ingot',15),('thorn_boar_bone',15)]:
            self.assertEqual(before.domains['inventory']['holdings'][rid]-after.domains['inventory']['holdings'][rid],amount)
        self.assertEqual(after.identity['instance_counter'],before.identity['instance_counter']+1)
        self.assertEqual(self.app.execute(q),receipt);self.assertEqual(self.state(),after)
        with SQLiteSave(self.db,allowed_root=self.root) as store:
            restarted=EcologyApplication(store,self.r,self.clock)
            self.assertEqual(restarted.query(self.sid),after)
            self.assertEqual(restarted.execute(q),receipt)
        row=after.domains['equipment']['instances'][receipt.result['instance_id']]
        self.assertEqual(row['roll_version'],'thorn-forge-v1')

    def test_receipt_failure_rolls_back_materials_and_identity(self):
        before=self.state();q=self.request('equipment_craft',{'equipment_id':'thorn_fang_blade'})
        with patch.object(self.store,'_insert_receipt',side_effect=RuntimeError('injected failure')):
            with self.assertRaises(RuntimeError):self.app.execute(q)
        self.assertEqual(before,self.state())
        self.assertIsNone(self.store.receipt(self.sid,before.generation,q.request_id))
        receipt=self.app.execute(q)
        self.assertEqual(self.app.execute(q),receipt)

    def test_preview_reports_forging_ranges_without_changing_drop_definition(self):
        preview=self.app.crafting_equipment_preview('thorn_fang_blade',1)
        self.assertEqual(preview['stat_ranges'],{'attack':[6,7],'crit':[5,6]})
        self.assertEqual(items.definition(self.r,'thorn_fang_blade').stat_ranges,(('attack_milli',5000,7000,1000),('crit_bps',400,600,100)))
        before=self.state();view=self.app.view(self.sid);self.assertEqual(before,self.state())
        self.assertIn('economy',view)

    def test_invalid_forging_profile_and_wrong_equipment_version_rejected(self):
        d=items.definition(self.r,'thorn_fang_blade')
        with self.assertRaises(ValidationError):replace(d,craft_fee_coins=0)
        with self.assertRaises(ValidationError):replace(d,craft_stat_ranges=(('attack_milli',6000,8000,1000),('crit_bps',500,600,100)))
        with self.assertRaises(ValidationError):replace(d,craft_stat_ranges=(('attack_milli',6500,7000,500),('crit_bps',500,600,100)))
        with self.assertRaises(ValidationError):
            items.add(items.initial(),self.r,'save:1:i:1','thorn_rock_staff','wrong',0,False,roll_version='thorn-forge-v1')
        good=items.add(items.initial(),self.r,'save:1:i:1',d.machine_id,'good',0,False,roll_version='thorn-forge-v1')
        bad=thaw_json(good);bad['instances']['save:1:i:1']['stats']['attack_milli']+=1000
        with self.assertRaises(ValidationError):items.validate(bad,self.r,'save')

    def fixture(self,change):
        from src.core.save.codec import StoredReceipt
        with self.store.transaction():
            original=self.state();changed=change(original)
            candidate=replace(changed,revision=original.revision+1)
            self.app.foundation.validate_state(candidate)
            self.counter+=1
            self.store.commit(original,candidate,StoredReceipt(self.sid,candidate.generation,str(UUID(int=2000+self.counter,version=4)),'0'*64,candidate.revision,'command',{}))

    def test_insufficient_fee_or_material_is_atomic_and_exact_fee_succeeds(self):
        def stock(coins,bone):
            self.fixture(lambda state:replace(state,domains={**state.domains,'inventory':{**state.domains['inventory'],'holdings':{**state.domains['inventory']['holdings'],'coins':coins,'thorn_boar_bone':bone}}}))
        for coins,bone in [(299,15),(300,14)]:
            stock(coins,bone);before=self.state()
            with self.assertRaises(ValidationError):self.craft()
            self.assertEqual(self.state(),before)
        stock(300,15);self.craft()
        self.assertEqual(self.state().domains['inventory']['holdings'].get('coins',0),0)
        self.assertEqual(self.state().domains['inventory']['holdings'].get('thorn_boar_bone',0),0)

    def test_old_item_and_active_battle_stay_valid_after_new_craft(self):
        from src.application import equipment as equip
        from src.systems.combat import battle
        self.fixture(lambda state:equip.acquire(state,self.r,'thorn_fang_blade','old-save',roll_version='thorn-roll-v2')[0])
        before=self.state();old_id=next(iter(before.domains['equipment']['instances']))
        old=before.domains['equipment']['instances'][old_id]
        _,receipt=self.craft()
        self.assertEqual(self.state().domains['equipment']['instances'][old_id],old)
        new_id=receipt.result['instance_id']
        self.app.execute(self.request('equipment_equip',{'instance_id':new_id}))
        self.app.execute(self.request('combat_start',{'encounter_id':'thorn_path_v2_001'}))
        snapshot=self.state().domains['combat']
        battle.validate(snapshot,self.r,self.sid)
        self.app.foundation.validate_state(self.state())
        self.assertEqual(snapshot,self.state().domains['combat'])
        with SQLiteSave(self.db,allowed_root=self.root) as store:
            restarted=EcologyApplication(store,self.r,self.clock)
            self.assertEqual(restarted.query(self.sid).domains['combat'],snapshot)

    def test_forged_item_can_be_sold_without_losing_base_stats_first(self):
        _,receipt=self.craft();identity=receipt.result['instance_id']
        before=self.state();row=before.domains['equipment']['instances'][identity]
        self.assertFalse(items.unknown(row,self.r))
        q=self.request('equipment_sell',{'instance_id':identity});self.app.execute(q)
        after=self.state();self.assertNotIn(identity,after.domains['equipment']['instances'])
        self.assertEqual(after.domains['inventory']['holdings']['coins']-before.domains['inventory']['holdings']['coins'],180)
        self.app.execute(q);self.assertEqual(after,self.state())

    def test_historical_registry_keeps_old_crafting_profile(self):
        old=load_dungeons(balance_legacy=True)
        with self.assertRaises(ValidationError):craft_cost(old,'thorn_fang_blade')
        self.assertIsNone(items.definition(old,'thorn_fang_blade').craft_roll_version)

    def test_http_preview_command_replay_and_csrf(self):
        from werkzeug.test import Client
        from werkzeug.wrappers import Response
        from src.transport.danding import create_app
        @contextmanager
        def factory():
            with SQLiteSave(self.db,allowed_root=self.root) as store:
                yield EcologyApplication(store,self.r,self.clock)
        http=create_app(factory,self.sid,lambda v:{},lambda _:None,'isolated-forge-token-123',secure=False,ui_root=Path('src/ui/pages/game').resolve(),cookie_path='/')
        http.testing=True;client=Client(http,Response)
        self.assertEqual(client.post('/login',data={'token':'isolated-forge-token-123'}).status_code,302)
        read=client.get('/api/view');self.assertEqual(read.status_code,200,read.json)
        v=read.json
        row=next(x for x in v['view']['economy']['crafting'] if x['equipment_id']=='thorn_fang_blade')
        costs={x['resource_id']:x['quantity'] for x in row['requirements']}
        self.assertEqual(costs,{'ingot':15,'thorn_boar_bone':15,'coins':300})
        self.assertEqual(row['stat_ranges'],{'attack':[6,7],'crit':[5,6]})
        body={'protocol_version':1,'save_id':self.sid,'generation':v['generation'],'expected_revision':v['revision'],'request_id':str(UUID(int=1000,version=4)),'command':{'name':'equipment_craft','version':1,'payload':{'equipment_id':'thorn_fang_blade'}}}
        self.assertEqual(client.post('/api/command',json=body).status_code,403)
        headers={'X-CSRF-Token':v['csrf']}
        response=client.post('/api/command',json=body,headers=headers)
        self.assertEqual(response.status_code,200,response.json)
        after=self.state();self.assertEqual(client.post('/api/command',json=body,headers=headers).status_code,200)
        self.assertEqual(after,self.state())

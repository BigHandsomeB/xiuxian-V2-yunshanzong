"""Loadout changes preserve ongoing combat and take effect at the next auto battle."""
import unittest
from dataclasses import replace
from uuid import uuid4
from src.application import equipment
from src.application.ecology import EcologyApplication
from src.application.cultivation import partition
from src.core.validation import ConflictError
from tests.systems import test_ecology as fixtures

class LiveLoadoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):fixtures.EcologyTests.setUpClass.__func__(cls)
    setUp=fixtures.EcologyTests.setUp
    read=fixtures.EcologyTests.read
    view=fixtures.EcologyTests.view
    fixture=fixtures.EcologyTests.fixture
    request=fixtures.EcologyTests.request
    execute=fixtures.EcologyTests.execute
    command=fixtures.EcologyTests.command
    settle=fixtures.EcologyTests.settle
    def test_auto_loadouts_keep_snapshot_receipt_and_next_battle(self):
        self.fixture(lambda state:equipment.acquire(state,self.registry,'thorn_fang_blade','fixture',roll_version='thorn-roll-v2')[0])
        identity=next(iter(self.read().domains['equipment']['instances']))
        self.command('combat_start',{'encounter_id':'thorn_path_v2_001'})
        self.command('dungeon_auto',{'enabled':True,'mode':'push','floor':1,'floor_count':1})
        before=self.read();battle=before.domains['combat'];old_id=battle['battle']['battle_id']
        self.assertTrue(self.view()['equipment']['instances'][0]['can_equip'])
        request=self.request('equipment_equip',{'instance_id':identity});receipt=self.execute(request)
        equipped=self.read()
        self.assertEqual(equipped.domains['combat'],battle)
        self.assertTrue(equipped.domains['dungeon']['auto']['enabled'])
        self.assertEqual(self.execute(request),receipt);self.assertEqual(self.read(),equipped)
        stale=replace(request,request_id=str(uuid4()))
        with self.assertRaises(ConflictError):self.execute(stale)
        slots=partition(equipped)['techniques']['slots'];slot,manual=next(iter(slots.items()))
        self.command('technique_unequip',{'slot':slot})
        self.assertEqual(self.read().domains['combat'],battle)
        self.assertTrue(self.view()['techniques']['can_change'])
        self.command('technique_equip',{'slot':slot,'technique_id':manual})
        self.assertEqual(self.read().domains['combat'],battle)
        self.command('equipment_unequip',{'instance_id':identity})
        self.assertEqual(self.read().domains['combat'],battle)
        self.command('equipment_equip',{'instance_id':identity})
        expected=EcologyApplication(None,self.registry,self.clock).player_projection(self.read())
        for _ in range(6):
            self.settle(10000)
            if self.read().domains['combat']['battle']['battle_id']!=old_id:break
        after=self.read();next_battle=after.domains['combat']['battle']
        self.assertNotEqual(next_battle['battle_id'],old_id)
        self.assertGreaterEqual(next_battle['player_snapshot']['attack_milli'],expected['attack_milli'])
        self.assertTrue(after.domains['dungeon']['auto']['enabled'])

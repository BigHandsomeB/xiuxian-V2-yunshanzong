"""Six-slot ownership/projection and legacy key compatibility; isolated fixtures only."""
import unittest
from dataclasses import replace
from src.data.economy.definitions import load_economy,EQUIPMENT_SLOTS
from src.data.registry import DefinitionKey
from src.core.state.envelope import thaw_json
from src.core.validation import ValidationError
from src.systems.equipment import items

class SixSlotsTest(unittest.TestCase):
    def setUp(self):
        self.registry=load_economy(seal=False)
        base=load_economy().lookup(DefinitionKey('equipment','basic_head'))
        for slot,_ in EQUIPMENT_SLOTS:
            self.registry.register(replace(base,machine_id='fixture_'+slot,slot=slot))
        self.registry.seal()

    def test_all_six_slots_and_replacement(self):
        p=items.initial()
        for index,(slot,_) in enumerate(EQUIPMENT_SLOTS):
            identity='six:1:i:'+str(index+1)
            p=items.add(p,self.registry,identity,'fixture_'+slot,'fixture',0,False)
            p=items.equip(p,self.registry,identity,False)
        items.validate(p,self.registry,'six')
        self.assertEqual(len(p['slots']),6)
        base={'max_hp_milli':80000,'attack_milli':10000,'armor_milli':500}
        projected=items.projection(p,base)
        self.assertEqual(projected['max_hp_milli'],128000)
        self.assertEqual(projected['armor_milli'],12500)
        p=items.add(p,self.registry,'six:1:i:7','fixture_gloves','fixture',0,False)
        p=items.equip(p,self.registry,'six:1:i:7',False)
        items.validate(p,self.registry,'six')
        self.assertEqual(len(p['slots']),6)
        self.assertEqual(sum(r['equipped'] for r in p['instances'].values()),6)
        self.assertEqual(items.projection(p,base),projected)
        with self.assertRaises(ValidationError):
            items.equip(p,self.registry,'six:1:i:1',True)

    def test_legacy_slots_and_unknown_slot(self):
        p=items.add(items.initial(),self.registry,'six:1:i:1','basic_head','fixture',0,False)
        p=items.equip(p,self.registry,'six:1:i:1',False)
        items.validate(thaw_json(p),self.registry,'six')
        self.assertEqual(p['slots']['head'],'six:1:i:1')
        d=items.definition(self.registry,'basic_head')
        with self.assertRaises(ValidationError):replace(d,slot='amulet')

if __name__=='__main__':unittest.main()

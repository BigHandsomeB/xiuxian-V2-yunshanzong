"""Equipment snapshot caps must include Growth/technique contributions."""
import unittest
from src.application.equipment import matches_projection
from src.systems.equipment import items

class EquipmentGrowthCapsTests(unittest.TestCase):
    def vector(self,**values):return tuple(values.get(k,0) for k in items.STATS)
    def test_growth_uses_part_of_rate_cap_before_equipment(self):
        definitions=(('left',(('attack_milli',10000),('speed_bps',1000)),()),)
        self.assertTrue(matches_projection(self.vector(attack_milli=10000,speed_bps=500),definitions,self.vector(speed_bps=2500)))
    def test_saturated_growth_retains_other_equipment_constraints(self):
        definitions=(('left',(('attack_milli',10000),('evasion_bps',1000)),()),)
        self.assertTrue(matches_projection(self.vector(attack_milli=10000),definitions,self.vector(evasion_bps=2500)))
        self.assertFalse(matches_projection(self.vector(attack_milli=10001),definitions,self.vector(evasion_bps=2500)))
    def test_uncapped_and_historical_callers_unchanged(self):
        definitions=(('left',(('attack_milli',10000),('speed_bps',1000)),()),)
        self.assertTrue(matches_projection(self.vector(attack_milli=10000,speed_bps=1000),definitions))
        self.assertFalse(matches_projection(self.vector(attack_milli=10000,speed_bps=500),definitions))

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

    def test_legacy_six_slot_snapshot_has_bounded_search(self):
        """A historical snapshot without an equipment witness must validate on cold start."""
        from unittest.mock import patch
        from math import gcd
        from src.application.equipment import matches_random_projection
        from src.data.content_loader import load_current
        target=self.vector(max_hp_milli=138000,attack_milli=25500,armor_milli=5200,
            crit_bps=1500,accuracy_bps=1950,evasion_bps=1867,speed_bps=2180,
            reflect_bps=3500,crit_damage_bps=300,crit_resist_bps=400,
            lifesteal_bps=200,damage_bonus_bps=300,damage_reduction_bps=100)
        base=dict(accuracy_bps=89,evasion_bps=633,speed_bps=820,crit_resist_bps=107,
            lifesteal_bps=71,damage_bonus_bps=60,damage_reduction_bps=142)
        operations=0
        def bounded_gcd(a,b):
            nonlocal operations
            operations+=1
            if operations>200000:self.fail('Legacy search exceeded its operation budget')
            return gcd(a,b)
        matches_projection.cache_clear()
        with patch('src.application.equipment.gcd',bounded_gcd):
            self.assertTrue(matches_random_projection(target,load_current(),base))

    def test_pruning_preserves_exhaustive_interval_and_cap_semantics(self):
        from itertools import product
        from math import gcd
        from random import Random
        from src.application.equipment import projection_groups
        from src.data.economy.definitions import EQUIPMENT_SLOTS
        rng=Random(71020)
        keys=('attack_milli','speed_bps','evasion_bps')
        for case in range(48):
            definitions=tuple((slot,(),tuple((k,a,a+step*2,step)
                for k in keys for a,step in [(rng.randrange(0,4)*100,rng.choice((100,200)))]))
                for slot,_ in EQUIPMENT_SLOTS[:3] for _ in range(2))
            base=self.vector(speed_bps=rng.choice((0,2500,3000)),evasion_bps=rng.choice((0,2200,2500)))
            groups=projection_groups(definitions)
            chosen=[rng.choice(g) for g in groups]
            target={}
            for k in keys:
                j=items.STATS.index(k)
                value=sum(r[j][0] for r in chosen)+(rng.choice((0,100,151)) if case%2 else 0)
                target[k]=min(value,max(0,items.RATE_CAPS[k]-base[j])) if k in items.RATE_CAPS else value
            bonuses=self.vector(**target)
            def fits(rows):
                for j,n in enumerate(bonuses):
                    low=sum(r[j][0] for r in rows);high=sum(r[j][1] for r in rows);step=0
                    for r in rows:step=gcd(step,r[j][2])
                    cap=max(0,items.RATE_CAPS[items.STATS[j]]-base[j]) if items.STATS[j] in items.RATE_CAPS else None
                    if cap is not None:low=min(low,cap);high=min(high,cap)
                    if not low<=n<=high or (n!=cap and step and (n-low)%step):return False
                return True
            expected=any(fits(rows) for rows in product(*groups))
            self.assertEqual(matches_projection(bonuses,definitions,base),expected,case)

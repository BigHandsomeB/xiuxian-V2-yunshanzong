import unittest
from src.data.dungeons.definitions import load_dungeons
from src.systems.equipment import items
from src.core.state.envelope import thaw_json

class RandomEquipmentTests(unittest.TestCase):
    def test_new_same_definition_has_varied_actual_stats(self):
        r=load_dungeons();p=items.initial()
        for n in range(40):p=items.add(p,r,f'save:1:i:{n+1}','thorn_fang_blade',f'new-battle:{n}',0,False,roll_version='thorn-roll-v2')
        values={tuple(sorted(row['stats'].items())) for row in p['instances'].values()}
        self.assertGreater(len(values),1)

    def test_ranges_independent_replay_and_protection(self):
        from src.core.validation import ValidationError
        r=load_dungeons()
        for d in r._definitions.values():
            if not getattr(d,'stat_ranges',()):continue
            values=[]
            for n in range(60):
                p=items.add(items.initial(),r,'save:1:i:1',d.machine_id,f'battle:{n}',0,False,roll_version='thorn-roll-v2')
                row=p['instances']['save:1:i:1'];self.assertFalse(items.unknown(row,r));values.append(dict(row['stats']))
                for key,low,high,step in d.stat_ranges:self.assertTrue(low<=row['stats'][key]<=high and (row['stats'][key]-low)%step==0)
                items.validate(p,r,'save')
            self.assertGreater(len({tuple(sorted(v.items())) for v in values}),1)
            a=items.add(items.initial(),r,'save:1:i:1',d.machine_id,'same-battle',0,False,roll_version='thorn-roll-v2')
            b=items.add(items.initial(),r,'save:1:i:9',d.machine_id,'same-battle',0,False,roll_version='thorn-roll-v2')
            self.assertEqual(a['instances']['save:1:i:1']['stats'],b['instances']['save:1:i:9']['stats'])
            p=items.equip(a,r,'save:1:i:1',False)
            with self.assertRaises(ValidationError):items.remove(p,r,'save:1:i:1')
            p=items.unequip(p,r,'save:1:i:1',False);p=items.remove(p,r,'save:1:i:1');self.assertFalse(p['instances'])

    def test_legacy_values_and_tampered_random_roll(self):
        from src.core.validation import ValidationError
        r=load_dungeons();old=items.add(items.initial(),r,'save:1:i:1','thorn_fang_blade','old',0,False)
        self.assertEqual(dict(old['instances']['save:1:i:1']['stats']),{'attack_milli':6000,'crit_bps':500})
        self.assertNotIn('roll_version',old['instances']['save:1:i:1']);self.assertFalse(items.unknown(old['instances']['save:1:i:1'],r))
        new=items.add(items.initial(),r,'save:1:i:1','thorn_fang_blade','new',0,False,roll_version='thorn-roll-v2')
        altered=thaw_json(new);altered['instances']['save:1:i:1']['stats']['attack_milli']+=1000
        with self.assertRaises(ValidationError):items.validate(altered,r,'save')

    def test_random_battle_snapshot_survives_equipment_disposal(self):
        from dataclasses import replace
        from src.application.danding import initial_slice
        from src.application import equipment as eq
        from src.systems.cultivation import growth
        from src.systems.combat import battle
        r=load_dungeons();s=initial_slice(r,last_settled_at_ms=1000)
        from src.systems.economy import policy
        s=replace(s,domains={**s.domains,'automation':policy.initial()})
        for key in ('thorn_fang_blade','thorn_vine_gloves','thorn_travel_belt','thorn_scale_shirt','thorn_moss_boots','thorn_feather_hood'):
            s,identity=eq.acquire(s,r,key,'battle:'+key,roll_version='thorn-roll-v2')
            s=eq.command(s,r,'equipment_equip',{'instance_id':identity})
        projected=items.projection(eq.equipment(s),growth.projection(eq.partition(s),r,s.save_id))
        n=s.identity['instance_counter']+1;bid=f'{s.save_id}:{s.generation}:i:{n}'
        combat=battle.start(battle.initial(),r,s.save_id,bid,'thorn_path_001',player_snapshot=projected)
        s=replace(s,identity={**s.identity,'instance_counter':n},domains={**s.domains,'combat':combat})
        eq.validate(s,r)
        s=replace(s,domains={**s.domains,'combat':battle.abandon(combat,r,s.save_id,bid)})
        for identity in list(eq.equipment(s)['instances']):
            s=eq.command(s,r,'equipment_unequip',{'instance_id':identity});s=eq.process(s,r,identity,'SELL')
        eq.validate(s,r)
        b=thaw_json(s.domains['combat']);b['battle']['player_snapshot']['attack_milli']=999999
        from src.core.validation import ValidationError
        with self.assertRaises(ValidationError):eq.validate(replace(s,domains={**s.domains,'combat':b}),r)

    def test_old_battle_keeps_v1_new_battle_uses_v2(self):
        from src.data.dungeons import loot
        from src.systems.combat import battle
        r=load_dungeons();p=battle.start(battle.initial(),r,'save','save:1:i:1','thorn_path_100')
        self.assertEqual(p['battle']['loot_version'],'thorn-loot-v2')
        old=thaw_json(p);old['battle']['loot_version']='thorn-loot-v1';battle.validate(old,r,'save')
        self.assertEqual(loot.plan(r,old['battle']),loot.plan(r,old['battle']))

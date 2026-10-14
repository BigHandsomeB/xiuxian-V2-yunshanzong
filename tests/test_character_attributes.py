"""Real combat/ownership seams for the sixteen character attributes."""
import unittest
from unittest.mock import patch
from src.core.state.envelope import thaw_json, freeze_json
from src.core.validation import ValidationError
from src.data.dungeons.definitions import load_dungeons
from src.data.registry import DefinitionKey
from src.systems.combat import battle, equipment_effects as effects
from src.systems.equipment import items
from src.application.equipment import attribute_rows
from tests.systems.test_equipment_economy import EquipmentFixture


class AttributeCombatTests(unittest.TestCase):
    def setUp(self):
        self.registry = load_dungeons()
        self.dungeon = self.registry.lookup(DefinitionKey('dungeons', 'thorn_path'))

    def start(self, extra=None, floor=1):
        actor = {**battle.player(self.registry, 'design'), **(extra or {})}
        return battle.start(battle.initial(), self.registry, 'design', 'attributes:test',
                            self.dungeon.encounters[floor-1], player_snapshot=actor)

    def attack(self, state):
        with patch.object(effects, 'roll', return_value=0):
            return battle.attack(state, self.registry, 'design', 'attributes:test')['battle']

    def test_crit_damage_adds_to_original_multiplier(self):
        actor={'attack_milli':10000,'crit_bps':3000,'crit_damage_bps':2000}
        state={'battle_id':'test','step':1,'enemy_hp_milli':100000}
        with patch.object(effects,'roll',return_value=0):
            value,critical=effects.attack_value(actor,state,battle.monster(self.registry,'thorn_path_v2_enemy_001'))
        self.assertTrue(critical);self.assertEqual(value,17000)

    def test_crit_resistance_cancels_enemy_critical(self):
        enemy=battle.monster(self.registry,'thorn_path_v2_enemy_100')
        self.assertEqual(enemy.crit_bps,1000)
        with patch.object(effects,'roll',return_value=0):
            self.assertTrue(effects.enemy_attack_value(enemy,{}, {'battle_id':'t','step':1})[1])
            value,critical=effects.enemy_attack_value(enemy,{'crit_resist_bps':1000},{'battle_id':'t','step':1})
        self.assertFalse(critical);self.assertEqual(value,enemy.attack_milli)

    def test_lifesteal_uses_actual_damage_and_can_heal_on_kill(self):
        state=thaw_json(self.start({'lifesteal_bps':1000}))
        state['battle']['player_hp_milli']=40000;state['battle']['enemy_hp_milli']=1000
        result=self.attack(freeze_json(state))
        self.assertEqual(result['status'],'PLAYER_WIN');self.assertEqual(result['player_hp_milli'],40100)
        heal=next(e for e in result['latest_events'] if e['kind']=='lifesteal')
        self.assertEqual(heal['damage_milli'],100)

    def test_full_life_does_not_overheal(self):
        result=self.attack(self.start({'lifesteal_bps':1500,'attack_milli':200000}))
        self.assertEqual(result['status'],'PLAYER_WIN')
        self.assertEqual(result['player_hp_milli'],80000)
        self.assertFalse(any(e['kind']=='lifesteal' for e in result['latest_events']))

    def test_damage_bonus_is_applied_after_armor(self):
        a=self.attack(self.start());b=self.attack(self.start({'damage_bonus_bps':1000}))
        hit=lambda row:next(e['damage_milli'] for e in row['latest_events'] if e['kind']=='damage' and e['actor']=='player')
        self.assertEqual(hit(b),hit(a)*11000//10000)

    def test_damage_reduction_changes_real_incoming_damage(self):
        a=self.attack(self.start());b=self.attack(self.start({'damage_reduction_bps':2000}))
        hit=lambda row:next(e['damage_milli'] for e in row['latest_events'] if e['kind']=='damage' and e['actor']=='enemy')
        self.assertEqual(hit(b),max(1000,hit(a)*8000//10000))

    def test_old_battle_does_not_gain_new_enemy_criticals(self):
        state=thaw_json(self.start(floor=100));del state['battle']['rules_version']
        result=self.attack(freeze_json(state))
        self.assertFalse(any(e['kind']=='critical' and e['actor']=='enemy' for e in result['latest_events']))

    def test_caps_and_display_total_crit_multiplier(self):
        for key,cap in effects.NEW_CAPS.items():
            effects.validate({key:cap})
            with self.assertRaises(ValidationError):effects.validate({key:cap+1})
        rows=attribute_rows(battle.player(self.registry,'design'))
        self.assertEqual(len(rows),16)
        self.assertEqual(next(r['value'] for r in rows if r['icon']=='crit_damage'),150)
        self.assertEqual(next(r['value'] for r in rows if r['icon']=='accuracy'),100)


class AttributeOwnershipTests(EquipmentFixture,unittest.TestCase):
    def test_new_affix_is_persisted_and_snapshot_is_valid(self):
        identity=self.forge();old=self.state().domains['equipment']['instances'][identity]
        self.assertEqual(len(old['affixes']),1)
        self.command('equipment_equip',{'instance_id':identity})
        self.command('combat_start',{'encounter_id':'thorn_first'})
        saved=self.state();self.assertEqual(saved.domains['equipment']['instances'][identity]['stats'],old['stats'])
        self.assertIn('crit_damage_bps',saved.domains['combat']['battle']['player_snapshot'])
        self.assertEqual(self.state(),saved)

    def test_existing_equipment_is_not_rerolled(self):
        registry=load_dungeons();p=items.add(items.initial(),registry,'design:1:i:1','thorn_fang_blade','old-loot',0,False,roll_version='thorn-roll-v2')
        row=p['instances']['design:1:i:1'];before=thaw_json(row)
        items.validate(p,registry,'design');self.assertEqual(thaw_json(row),before);self.assertEqual(row['affixes'],())

    def test_tampered_affix_is_rejected(self):
        registry=load_dungeons();p=thaw_json(items.add(items.initial(),registry,'design:1:i:1','thorn_fang_blade','loot',0,False,roll_version='thorn-roll-v2',combat_affix=True))
        p['instances']['design:1:i:1']['affixes'][0]['value']+=1
        with self.assertRaises(ValidationError):items.validate(p,registry,'design')

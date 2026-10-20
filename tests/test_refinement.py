"""Isolated SQLite integration: refinement, replay, combat witness and legacy data."""
import unittest
from dataclasses import replace
from unittest.mock import patch
from src.core.state.envelope import thaw_json
from src.core.validation import ValidationError, ConflictError
from src.application import equipment as equip
from src.application.memory import Command
from src.data.content_loader import load_current
from src.data.economy.refinement import settings, validate_config
from src.systems.equipment import items, refinement
from tests import test_market_restock as restock


class RefinementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = load_current()

    app = restock.RestockTests.app
    read = restock.RestockTests.read
    view = restock.RestockTests.view
    request = restock.RestockTests.request
    command = restock.RestockTests.command
    fixture = restock.RestockTests.fixture
    settle = restock.RestockTests.settle

    def setUp(self):
        restock.RestockTests.setUp(self)
        def prepare(state):
            state, self.item = equip.acquire(state, self.registry, 'thorn_fang_blade', 'refinement-fixture', roll_version=items.ROLL_VERSION)
            stock = {'coins': 100000, 'ore': 40, 'thorn_boar_bone': 40, 'fire_pattern_stone': 40}
            return replace(state, domains={**state.domains, 'inventory': {'holdings': stock}})
        self.fixture(prepare)

    def refine(self, materials=None, request=None):
        return self.command('equipment_refine', {'instance_id': self.item,
            'materials': ['ore', 'thorn_boar_bone', 'fire_pattern_stone'] if materials is None else materials}, request)

    def row(self):
        return self.read().domains['equipment']['instances'][self.item]

    def test_old_save_view_is_pure_and_catalog_registered(self):
        before = self.read(); view = self.view()['refinement']
        self.assertEqual(len(view['materials']), 84)
        self.assertEqual([s['weight_bps'] for s in view['slots']], [10000, 7000, 5000])
        self.assertNotIn('refinement', self.row()); self.assertEqual(before, self.read())
        for row in view['materials']:
            self.assertEqual(len(row['contributions']), 3)

    def test_atomic_spend_replay_restart_and_preserve_roll(self):
        before = self.row(); state = self.read()
        request = self.request('equipment_refine', {'instance_id': self.item, 'materials': ['ore', 'ore', 'ore']})
        receipt = self.refine(request=request)
        self.assertEqual(self.refine(request=request), receipt)
        self.assertEqual(self.row()['stats'], before['stats']); self.assertEqual(self.row()['affixes'], before['affixes'])
        self.assertEqual(self.row()['refinement']['stats'], {'attack_milli': 1100, 'armor_milli': 440})
        stock = self.read().domains['inventory']['holdings']
        self.assertEqual(stock['ore'], 25); self.assertEqual(stock['coins'], 99900)
        self.assertEqual(self.read().revision, state.revision + 1)
        with self.app() as app:
            self.assertEqual(app.query(self.sid), self.read())

    def test_repeated_refine_replaces_without_compounding(self):
        self.refine(['ore', None, None]); before = items.effective_stats(self.row())
        self.refine([None, 'ore', None]); after = items.effective_stats(self.row())
        self.assertEqual(before['attack_milli']-after['attack_milli'], 150)
        self.assertEqual(self.row()['refinement']['stats']['attack_milli'], 350)
        unchanged = self.read()
        with self.assertRaises(ValidationError): self.refine([None, 'ore', None])
        self.assertEqual(self.read(), unchanged)

    def test_preserves_enhancement(self):
        def enhance(state):
            part=thaw_json(state.domains['equipment'])
            part['instances'][self.item]['enhancement']={'level':1,'bonus_bps':1000,'version':'sect-enhance-v1'}
            return replace(state, domains={**state.domains, 'equipment':part})
        # Read actual versioned bonus rather than asserting a historical skill value.
        from src.systems.sect.management import config
        def actual(state):
            state=enhance(state);p=thaw_json(state.domains['equipment'])
            p['instances'][self.item]['enhancement']['bonus_bps']=config(self.registry)['enhancement_bonus_bps_per_level']
            return replace(state,domains={**state.domains,'equipment':p})
        self.fixture(actual);before=self.row()['enhancement'];self.refine()
        self.assertEqual(before,self.row()['enhancement'])

    def test_invalid_payloads_never_spend(self):
        for materials in ([], [None]*3, ['ore']*4, ['coins',None,None], [True,None,None], [{'id':'ore'},None,None], 'ore'):
            before=self.read()
            with self.subTest(materials=materials), self.assertRaises(ValidationError): self.refine(materials)
            self.assertEqual(self.read(),before)
        before=self.read()
        with self.assertRaises(ValidationError):self.command('equipment_refine',{'instance_id':self.item,'materials':['ore',None,None],'stats':{'attack_milli':999999}})
        self.assertEqual(before,self.read())

    def test_short_materials_and_reserves_roll_back(self):
        def reserve(state):
            p=thaw_json(state.domains['sect_management']);p['material_reserves']['ore']=30
            return replace(state,domains={**state.domains,'sect_management':p})
        self.fixture(reserve);before=self.read()
        with self.assertRaises(ValidationError):self.refine(['ore']*3)
        self.assertEqual(before,self.read())
        self.refine(['ore',None,None]);self.assertEqual(self.read().domains['inventory']['holdings']['ore'],35)

    def test_coin_shortage_and_forge_requirement(self):
        def poor(state):
            inv=thaw_json(state.domains['inventory']);inv['holdings']['coins']=99
            return replace(state,domains={**state.domains,'inventory':inv})
        self.fixture(poor);before=self.read()
        with self.assertRaises(ValidationError):self.refine()
        self.assertEqual(before,self.read())
        from src.application.refinement import reasons
        state=self.read();sect=thaw_json(state.domains['sect']);sect['buildings']={k:v for k,v in sect['buildings'].items() if v['definition_id']!='forge'}
        self.assertIn('炼器阁等级不足',reasons(replace(state,domains={**state.domains,'sect':sect}),self.registry))

    def test_pause_active_battle_and_auto_are_blocked(self):
        from src.application.refinement import reasons
        state=self.read()
        self.assertTrue(reasons(replace(state,time={**state.time,'world_paused':True}),self.registry))
        d=thaw_json(state.domains['dungeon']);d['auto']['enabled']=True
        self.assertTrue(reasons(replace(state,domains={**state.domains,'dungeon':d}),self.registry))
        self.command('combat_start',{'encounter_id':'thorn_path_v2_001'});before=self.read()
        with self.assertRaises(ValidationError):self.refine()
        self.assertEqual(before,self.read())

    def test_stale_conflicting_and_transaction_failure(self):
        q=self.request('equipment_refine',{'instance_id':self.item,'materials':['ore',None,None]});self.refine(request=q)
        bad=Command(q.save_id,q.generation,self.read().revision,q.request_id,q.name,{'instance_id':self.item,'materials':[None,'ore',None]})
        with self.assertRaises(ConflictError):self.command('',{},bad)
        before=self.read()
        with patch('src.core.save.sqlite.SQLiteSave.commit',side_effect=RuntimeError('test rollback')):
            with self.assertRaises(RuntimeError):self.refine([None,'ore',None])
        self.assertEqual(before,self.read())

    def test_refined_equipment_bulk_protection_and_projection(self):
        self.refine(['ore',None,None]);self.command('equipment_equip',{'instance_id':self.item})
        with self.app() as app:
            projected=app.player_projection(self.read())
        self.command('equipment_unequip',{'instance_id':self.item})
        self.assertEqual(equip.bulk_preview(self.read(),self.registry)['count'],0)
        with self.app() as app:
            bare=app.player_projection(self.read())
        self.assertEqual(projected['attack_milli']-bare['attack_milli'],items.effective_stats(self.row())['attack_milli'])

    def test_frozen_combat_survives_refine_unequip_and_disposal(self):
        self.refine(['ore',None,None]);self.command('equipment_equip',{'instance_id':self.item})
        self.command('combat_start',{'encounter_id':'thorn_path_v2_001'})
        snapshot=self.read().domains['combat']['battle']['equipment_snapshot']
        self.assertEqual(snapshot['instances'][self.item]['refinement']['stats']['attack_milli'],500)
        self.command('combat_abandon',{'battle_id':self.read().domains['combat']['battle']['battle_id']})
        self.refine([None,'ore',None]);self.command('equipment_unequip',{'instance_id':self.item})
        self.command('equipment_sell',{'instance_id':self.item})
        self.assertNotIn(self.item,self.read().domains['equipment']['instances'])
        self.assertEqual(snapshot,self.read().domains['combat']['battle']['equipment_snapshot'])
        self.view()  # Includes independent snapshot validation after reopening SQLite.

    def test_tamper_and_config_validation(self):
        self.refine();part=thaw_json(self.read().domains['equipment'])
        part['instances'][self.item]['refinement']['stats']['attack_milli']+=1
        with self.assertRaises(ValidationError):items.validate(part,self.registry,self.sid)
        for key,value in [('version','fake'),('element','fake'),('materials',['coins',None,None])]:
            record=thaw_json(self.row()['refinement']);record[key]=value
            with self.assertRaises(ValidationError):refinement.validate(record,self.registry)
        cfg=thaw_json(settings(self.registry));cfg['materials']['ore']['stats']['unknown_bps']=100
        with self.assertRaises(ValidationError):validate_config(cfg)

    def test_rate_caps_and_all_materials_are_effective(self):
        cfg=settings(self.registry)
        for rid in cfg['materials']:
            record=refinement.result([rid,rid,rid],cfg)
            refinement.validate(record,self.registry)
            refinement.validate(thaw_json(record),self.registry)
            self.assertTrue(record['stats'])
        self.refine(['ore',None,None]);self.command('equipment_equip',{'instance_id':self.item})
        base={k:cap for k,cap in items.RATE_CAPS.items()}
        actor=items.projection(self.read().domains['equipment'],base)
        for key,cap in items.RATE_CAPS.items():self.assertLessEqual(actor[key],cap)

    def test_sql_write_failure_rolls_back_materials_and_receipt(self):
        before=self.read();request=self.request('equipment_refine',{'instance_id':self.item,'materials':['ore',None,None]})
        with patch('src.core.save.sqlite.SQLiteSave._insert_receipt',side_effect=RuntimeError('failure after state SQL update')):
            with self.assertRaises(RuntimeError):self.refine(request=request)
        self.assertEqual(before,self.read())
        with self.app() as app:self.assertIsNone(app.store.receipt(self.sid,before.generation,request.request_id))
        self.refine(request=request)
        self.assertEqual(self.read().domains['inventory']['holdings']['ore'],35)

    def test_old_finished_battle_remains_valid_after_first_refinement(self):
        self.command('equipment_equip',{'instance_id':self.item})
        self.command('combat_start',{'encounter_id':'thorn_path_v2_001'})
        self.command('combat_abandon',{'battle_id':self.read().domains['combat']['battle']['battle_id']})
        before=self.read().domains['combat'];self.refine(['ore',None,None])
        self.assertEqual(before,self.read().domains['combat']);self.view()

    def test_auto_battle_preserves_refined_snapshot_and_rejects_tamper(self):
        self.refine(['ore',None,None]);self.command('equipment_equip',{'instance_id':self.item})
        self.command('dungeon_auto',{'enabled':True,'mode':'push','floor':1})
        self.settle(20000)
        state=self.read();b=state.domains['combat']['battle']
        self.assertIn('equipment_snapshot',b)
        bad=thaw_json(state.domains['combat'])
        bad['battle']['equipment_snapshot']['instances'][self.item]['refinement']['stats']['attack_milli']+=1
        with self.app() as app:
            with self.assertRaises(ValidationError):app.foundation.validate_state(replace(state,domains={**state.domains,'combat':bad}))
        self.assertEqual(state,self.read())


if __name__=='__main__':unittest.main()

"""Food retirement and content migration on disposable historical saves."""
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
from src.application.danding import initial_slice
from src.application.ecology import EcologyApplication
from src.application.ecology_upgrade import upgrade
from src.application.sect_management import ManagementApplication
from src.application.memory import Command
from src.application.settlement import SettlementRequest
from src.core.save.sqlite import SQLiteSave, V2_ROOT
from src.core.state.envelope import thaw_json
from src.core.validation import ConflictError
from src.data.dungeons.definitions import load_dungeons
from src.systems.economy import policy
from tests.fixtures.time import ManualClock


class EcologyUpgradeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old = load_dungeons(management=True, cold_jade=True)
        cls.new = load_dungeons(management=True, cold_jade=True, ecology=True)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=V2_ROOT / 'tests')
        self.addCleanup(self.tmp.cleanup)
        self.root, self.clock = Path(self.tmp.name), ManualClock()
        self.path = self.root / 'upgrade.sqlite3'
        state = initial_slice(self.old, last_settled_at_ms=self.clock.now_ms())
        self.sid = state.save_id
        stock = thaw_json(state.domains['inventory'])
        stock['holdings'].update(food=40, grain=100, spring_water=20, coins=1000)
        disciples = thaw_json(state.domains['disciples'])
        disciples['assignments'] = {}
        state = replace(state, domains={**state.domains, 'inventory': stock,
                        'disciples': disciples, 'automation': policy.initial()})
        with SQLiteSave.initialize(self.path, allowed_root=self.root) as store:
            ManagementApplication(store, self.old, self.clock).create(state)

    def command(self, app, name, payload):
        state = app.query(self.sid)
        request = Command(self.sid, state.generation, state.revision, str(uuid4()), name, payload)
        return request, app.execute(request)

    def request(self, state):
        return Command(self.sid, state.generation, state.revision, str(uuid4()), 'ecology_content_upgrade', {})

    def test_food_conversion_pure_views_and_repeat_upgrade(self):
        with SQLiteSave(self.path, allowed_root=self.root) as store:
            old = ManagementApplication(store, self.old, self.clock)
            before = old.query(self.sid)
            request = self.request(before)
            receipt = upgrade(store, self.clock, request)
            app = EcologyApplication(store, self.new, self.clock)
            after = app.query(self.sid)
            self.assertEqual(40, after.domains['inventory']['holdings']['meal_qingling_rice'])
            self.assertNotIn('food', after.domains['inventory']['holdings'])
            self.assertEqual(before.time, after.time)
            self.assertEqual(before.domains['disciples'], after.domains['disciples'])
            app.view(self.sid)
            self.assertEqual(after, app.query(self.sid))
            self.assertEqual(receipt, upgrade(store, self.clock, request))
            self.assertEqual(after, app.query(self.sid))

    def test_old_job_speed_receipt_and_remaining_paid_supply_preserved(self):
        with SQLiteSave(self.path, allowed_root=self.root) as store:
            old = ManagementApplication(store, self.old, self.clock)
            supply_request, supply_receipt = self.command(old, 'sect_supply', {'enabled': True, 'reserve': 0})
            bid = next(key for key, row in old.query(self.sid).domains['sect']['buildings'].items() if row['definition_id'] == 'canteen')
            self.command(old, 'work_assign', {'building_id': bid, 'count': 1})
            production_request, production_receipt = self.command(old, 'production_start', {'building_id': bid, 'recipe_id': 'sect_food'})
            before = old.query(self.sid)
            self.assertEqual(1150, before.domains['production']['jobs'][bid]['work_rate_milli'])
            upgrade(store, self.clock, self.request(before))
            app = EcologyApplication(store, self.new, self.clock)
            after = app.query(self.sid)
            self.assertEqual(before.domains['production'], after.domains['production'])
            self.assertEqual(8, after.domains['ecology']['supply']['legacy_covered_count'])
            self.assertEqual(production_receipt, app.execute(production_request))
            self.assertEqual(supply_receipt, app.execute(supply_request))
            self.assertEqual(after, app.query(self.sid))
            self.clock.advance(30000)
            app.settle(SettlementRequest(self.sid, after.generation, after.revision, str(uuid4()), 128, None))
            state = app.query(self.sid)
            self.assertEqual(34, state.domains['inventory']['holdings']['meal_qingling_rice'])
            self.assertNotIn('food', state.domains['inventory']['holdings'])

    def test_migration_failure_rolls_back_and_paused_state_kept(self):
        with SQLiteSave(self.path, allowed_root=self.root) as store:
            old = ManagementApplication(store, self.old, self.clock)
            self.command(old, 'world_pause', {})
            before = old.query(self.sid)
            request = self.request(before)
            with patch.object(store, 'commit', side_effect=RuntimeError('fixture failure')):
                with self.assertRaises(RuntimeError):
                    upgrade(store, self.clock, request)
            self.assertEqual(before, old.query(self.sid))
            upgrade(store, self.clock, request)
            after = EcologyApplication(store, self.new, self.clock).query(self.sid)
            self.assertEqual(before.time, after.time)
            self.assertTrue(after.time['world_paused'])

    def test_pending_window_requires_completion_before_switch(self):
        with SQLiteSave(self.path, allowed_root=self.root) as store:
            old = ManagementApplication(store, self.old, self.clock)
            self.command(old, 'sect_supply', {'enabled': True, 'reserve': 0})
            bid = next(key for key, row in old.query(self.sid).domains['sect']['buildings'].items() if row['definition_id'] == 'canteen')
            self.command(old, 'work_assign', {'building_id': bid, 'count': 1})
            self.command(old, 'production_start', {'building_id': bid, 'recipe_id': 'sect_food'})
            self.clock.advance(600000)
            state = old.query(self.sid)
            old.settle(SettlementRequest(self.sid, state.generation, state.revision, str(uuid4()), 1, None))
            before = old.query(self.sid)
            self.assertIsNotNone(before.time['pending'])
            with self.assertRaises(ConflictError):
                upgrade(store, self.clock, self.request(before))
            self.assertEqual(before, old.query(self.sid))

    def test_unchanged_combat_and_existing_production_definitions(self):
        for key, definition in self.old._definitions.items():
            if key.domain in ('encounters', 'monsters', 'equipment', 'equipment_rolls', 'production', 'dungeon_loot'):
                self.assertEqual(definition, self.new.lookup(key))

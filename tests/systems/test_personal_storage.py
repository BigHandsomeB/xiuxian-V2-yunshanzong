"""Personal items remain usable with a full warehouse; materials keep the original limit."""
import unittest
from src.systems.inventory import holdings, operations
from tests.systems.test_equipment_economy import EquipmentFixture


class PersonalStorageTests(EquipmentFixture, unittest.TestCase):
    def fill_warehouse(self):
        used = holdings.stock_size(self.state().domains['inventory'], self.registry)
        capacity = self.view()['capacity']['effective']
        self.command('inventory_grant', {'amounts': {'herb': capacity-used}})
        return capacity

    def test_full_warehouse_accepts_unlimited_pills_but_rejects_materials(self):
        capacity = self.fill_warehouse()
        self.command('inventory_grant', {'amounts': {'pill': 100000}})
        self.assertEqual(self.state().domains['inventory']['holdings']['pill'], 100000)
        self.assertEqual(self.view()['capacity']['used'], capacity)
        _, result = operations.grant(self.state().domains['inventory'], self.registry,
                                     {'wood': 1, 'pill': 1}, capacity=capacity)
        self.assertEqual(result['discarded'], {'wood': 1, 'pill': 0})

    def test_full_warehouse_does_not_block_equipment_delivery(self):
        self.supplies()
        self.assign('forge', 'ordinary_build')
        self.start('forge_sword', 'forge')
        capacity = self.fill_warehouse()
        self.clock.advance(120000)
        self.finish_pending()
        self.assertEqual(len(self.state().domains['equipment']['instances']), 1)
        self.assertEqual(self.view()['capacity']['used'], capacity)

    def test_full_warehouse_does_not_block_pill_delivery(self):
        self.command('inventory_grant', {'amounts': {'herb': 10}})
        self.start('pill', 'alchemy')
        capacity = self.fill_warehouse()
        self.clock.advance(120000)
        self.finish_pending()
        self.assertGreater(self.state().domains['inventory']['holdings'].get('pill', 0), 0)
        self.assertEqual(self.view()['capacity']['used'], capacity)

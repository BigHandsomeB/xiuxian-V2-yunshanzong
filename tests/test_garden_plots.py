"""Per-plot transactions and offline accrual on disposable authoritative saves."""
import unittest
from dataclasses import replace
from unittest.mock import patch
from src.core.state.envelope import thaw_json
from src.core.save.sqlite import SQLiteSave
from src.core.validation import ValidationError, ConflictError
from src.core.time.world import WorldPaused
from src.systems.resources import jobs
from tests.systems import test_ecology as fixtures


class GardenPlotTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.EcologyTests.setUpClass.__func__)
    for name in ('setUp', 'read', 'view', 'bid', 'request', 'execute', 'command', 'settle', 'fixture', 'assign', 'remove'):
        locals()[name] = getattr(fixtures.EcologyTests, name)

    def action(self, name, index=0, **payload):
        return self.command(name, {'building_id': self.bid('garden'), 'plot_index': index, **payload})

    def plant(self, recipe='herb', index=0):
        self.action('garden_reclaim', index)
        return self.action('garden_plant', index, recipe_id=recipe, repeat=False)

    def owned(self):
        return self.read().domains['ecology']['garden'][self.bid('garden')]

    def test_old_save_pure_read_and_unopened_slots(self):
        before = self.read()
        self.assertNotIn('garden', before.domains['ecology'])
        v = self.view()['ecology']['gardens'][0]
        self.assertEqual(v['capacity'], len(v['plots']))
        self.assertTrue(all(p['state'] == 'UNCULTIVATED' for p in v['plots']))
        self.assertEqual(before, self.read())

    def test_reclaim_is_persistent_free_idempotent_and_does_not_clear_plant(self):
        before = self.read()
        q = self.request('garden_reclaim', {'building_id': self.bid('garden'), 'plot_index': 0})
        r = self.execute(q); after = self.read()
        self.assertEqual(before.domains['inventory'], after.domains['inventory'])
        self.assertEqual(self.execute(q), r); self.assertEqual(after, self.read())
        self.assign('garden'); self.action('garden_plant', recipe_id='herb')
        planted = self.owned()['0']; self.action('garden_reclaim')
        self.assertEqual(planted, self.owned()['0'])

    def test_different_plants_charge_once_each_and_deliver_once(self):
        self.command('work_assign', {'building_id': self.bid('garden'), 'count': 2})
        before = self.read()
        self.action('garden_reclaim'); q = self.request('garden_plant', {'building_id': self.bid('garden'), 'plot_index': 0, 'recipe_id': 'herb', 'repeat':False})
        receipt = self.execute(q); after = self.read()
        self.assertEqual(self.execute(q), receipt); self.assertEqual(after, self.read())
        self.plant('grain', 1)
        plants = thaw_json(self.owned())
        self.assertEqual({r['recipe_id'] for r in plants.values()}, {'herb', 'grain'})
        water = sum(dict(jobs.definition(self.registry, r['recipe_id']).inputs).get('spring_water', 0) for r in plants.values())
        self.assertEqual(self.read().domains['inventory']['holdings']['spring_water'], before.domains['inventory']['holdings']['spring_water'] - water)
        duration = max(jobs.definition(self.registry, r['recipe_id']).duration_ms for r in plants.values())
        self.settle(duration)
        self.assertTrue(all(r is None for r in self.owned().values()))
        for r in plants.values():
            for rid, n in jobs.outputs(r, self.registry).items():
                self.assertEqual(self.read().domains['inventory']['holdings'].get(rid, 0), before.domains['inventory']['holdings'].get(rid, 0) + n)
        stock = self.read().domains['inventory']; self.settle(1000)
        self.assertEqual(stock, self.read().domains['inventory'])

    def test_reject_locked_wrong_building_bad_index_and_unreclaimed(self):
        cases = [('garden_reclaim', {'building_id': self.bid('pasture'), 'plot_index': 0}),
                 ('garden_reclaim', {'building_id': self.bid('garden'), 'plot_index': 999}),
                 ('garden_reclaim', {'building_id': self.bid('garden'), 'plot_index': True}),
                 ('garden_reclaim', {'building_id': self.bid('garden'), 'plot_index': -1}),
                 ('garden_plant', {'building_id': self.bid('garden'), 'plot_index': 0, 'recipe_id': 'herb', 'repeat':False})]
        for name, payload in cases:
            before = self.read()
            with self.assertRaises(ValidationError): self.command(name, payload)
            self.assertEqual(before, self.read())

    def test_shortage_and_occupied_plot_are_atomic(self):
        self.assign('garden'); self.action('garden_reclaim'); self.remove('spring_water')
        before = self.read()
        with self.assertRaises(ValidationError): self.action('garden_plant', recipe_id='herb')
        self.assertEqual(before, self.read())

    def test_missing_worker_and_locked_recipe_are_atomic(self):
        self.action('garden_reclaim'); before = self.read()
        with self.assertRaises(ValidationError): self.action('garden_plant', recipe_id='herb')
        self.assertEqual(before, self.read())
        self.assign('garden'); before = self.read()
        with self.assertRaises(ValidationError): self.action('garden_plant', recipe_id='ore')
        self.assertEqual(before, self.read())

    def test_unassign_pauses_and_reassign_resumes_without_paying_again(self):
        self.assign('garden'); self.plant(); self.settle(1000)
        self.command('work_unassign', {'building_id': self.bid('garden')})
        row = self.owned()['0']; self.assertEqual(row['rate_milli'], 0)
        self.settle(100000); self.assertEqual(self.owned()['0']['progress_milli'], row['progress_milli'])
        stock = self.read().domains['inventory']; self.assign('garden')
        self.assertGreater(self.owned()['0']['rate_milli'], 0)
        self.assertEqual(stock, self.read().domains['inventory'])
        self.settle(jobs.definition(self.registry, 'herb').duration_ms)
        self.assertIsNone(self.owned()['0'])

    def test_world_pause_keeps_progress_and_resources(self):
        self.assign('garden'); self.plant(); self.command('world_pause', {})
        before = self.read(); self.clock.advance(100000)
        with self.assertRaises(WorldPaused): self.action('garden_reclaim', 1)
        self.assertEqual(before, self.read())
        self.command('world_resume', {}); self.assertEqual(before.domains, self.read().domains)

    def test_legacy_job_and_automation_preserved(self):
        self.assign('garden'); self.command('production_start', {'building_id': self.bid('garden'), 'recipe_id': 'herb'})
        self.action('garden_reclaim'); before = self.read()
        with self.assertRaises(ValidationError): self.action('garden_plant', recipe_id='grain')
        self.assertEqual(before, self.read())
        self.assertIsNotNone(self.view()['ecology']['gardens'][0]['legacy_job'])
        self.settle(jobs.definition(self.registry, 'herb').duration_ms)
        self.command('automation_production', {'building_id': self.bid('garden'), 'policy': {'enabled': True, 'recipe_id': 'herb', 'target': 999}})
        before = self.read()
        with self.assertRaises(ValidationError): self.action('garden_plant', recipe_id='grain')
        self.assertEqual(before, self.read())

    def test_batch_start_does_not_double_use_plot_workers(self):
        self.assign('garden'); self.plant(); before = self.read()
        for name, payload in [('garden_plant', {'building_id': self.bid('garden'), 'plot_index': 0, 'recipe_id': 'grain'}), ('production_start', {'building_id': self.bid('garden'), 'recipe_id': 'grain'})]:
            with self.assertRaises(ValidationError): self.command(name, payload)
            self.assertEqual(before, self.read())

    def test_write_failure_rolls_back_water_plot_identity_and_receipt(self):
        self.assign('garden'); self.action('garden_reclaim'); before = self.read()
        q = self.request('garden_plant', {'building_id': self.bid('garden'), 'plot_index': 0, 'recipe_id': 'herb', 'repeat':False})
        with patch.object(SQLiteSave, 'commit', side_effect=RuntimeError('isolated fault')):
            with self.assertRaises(RuntimeError): self.execute(q)
        self.assertEqual(before, self.read()); self.execute(q)
        self.assertIsNotNone(self.owned()['0'])

    def test_upgrade_adds_unreclaimed_plots_and_preserves_existing(self):
        self.assign('garden'); self.plant(); before = self.owned()['0']; count = self.view()['ecology']['gardens'][0]['capacity']
        def upgrade(state):
            sect = thaw_json(state.domains['sect']); sect['buildings'][self.bid('garden')]['level'] += 1
            return replace(state, domains={**state.domains, 'sect': sect})
        self.fixture(upgrade)
        v = self.view()['ecology']['gardens'][0]
        self.assertGreater(v['capacity'], count); self.assertEqual(before, self.owned()['0'])
        self.assertTrue(all(r['state'] == 'UNCULTIVATED' for r in v['plots'][count:]))

    def test_online_offline_accrual_agree(self):
        self.assign('garden'); self.plant(); before = self.read()
        from src.application.ecology import EcologyApplication
        with SQLiteSave(self.path, allowed_root=self.root) as store:
            app = EcologyApplication(store, self.registry, self.clock)
            elapsed = jobs.definition(self.registry, 'herb').duration_ms
            one, _ = app.engine.advance(before, now_ms=before.time['last_settled_at_ms']+elapsed, max_events=128)
            split = before
            for step in range(1, 5):
                split, _ = app.engine.advance(split, now_ms=before.time['last_settled_at_ms']+elapsed*step//4, max_events=128)
            self.assertEqual(one.domains['inventory'], split.domains['inventory'])
            self.assertEqual(one.domains['ecology'], split.domains['ecology'])

    def test_full_warehouse_keeps_mature_plant_then_delivers_once(self):
        self.assign('garden'); self.plant()
        def fill(state):
            from src.application.sect_economy import reserved
            from src.application import sect
            from src.systems.inventory import holdings
            stock = thaw_json(state.domains['inventory'])
            free = sect.capacity_source(state, self.registry)['effective'] - holdings.stock_size(stock, self.registry) - reserved(state, self.registry)
            stock['holdings']['stone'] = stock['holdings'].get('stone', 0) + free
            return replace(state, domains={**state.domains, 'inventory': stock})
        self.fixture(fill); stock = self.read().domains['inventory']
        self.settle(jobs.definition(self.registry, 'herb').duration_ms)
        self.assertEqual(stock, self.read().domains['inventory'])
        self.assertEqual(self.view()['ecology']['gardens'][0]['plots'][0]['state'], 'READY')
        self.assertTrue(self.view()['economy']['needs_settlement'])
        self.remove('stone'); self.settle(1)
        self.assertIsNone(self.owned()['0'])
        delivered = self.read().domains['inventory']; self.settle(1000)
        self.assertEqual(delivered, self.read().domains['inventory'])

    def test_one_event_budget_preserves_two_simultaneous_crops(self):
        self.command('work_assign', {'building_id': self.bid('garden'), 'count': 2})
        self.plant('herb', 0); self.plant('grain', 1)
        self.settle(max(jobs.definition(self.registry, key).duration_ms for key in ('herb', 'grain')), max_events=1)
        self.assertTrue(all(row is None for row in self.owned().values()))

"""Real commands and event settlement on disposable V2 SQLite saves."""
import tempfile
import unittest
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
from src.application.danding import initial_slice
from src.application.ecology import EcologyApplication
from src.application.memory import Command
from src.application.settlement import SettlementRequest
from src.core.save.sqlite import SQLiteSave, V2_ROOT
from src.core.save.codec import StoredReceipt
from src.core.state.envelope import thaw_json
from src.core.time.model import Continuation
from src.core.validation import ValidationError
from src.core.validation import ConflictError
from src.application.recovery import RecoveryApplication
from src.core.save.recovery import RecoveryRequest
from src.data.dungeons.definitions import load_dungeons
from src.data.economy.ecology import settings
from src.systems.economy import policy
from src.systems.resources import jobs
from tests.fixtures.time import ManualClock


class EcologyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = load_dungeons(management=True, cold_jade=True, ecology=True)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=V2_ROOT / 'tests')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / 'ecology.sqlite3'
        self.clock = ManualClock()
        state = initial_slice(self.registry, last_settled_at_ms=self.clock.now_ms())
        self.sid = state.save_id
        stock = thaw_json(state.domains['inventory'])
        stock['holdings'].update(coins=10000, spring_water=100, meal_qingling_rice=100,
                                 beast_feed_basic=100, fish_feed_basic=100,
                                 sect_crop_01=100, sect_lining=20, sect_bone_frame=20,
                                 sect_shell_part=20, sect_nurture_agent=20,
                                 ordinary_wood=100, stone=100)
        sect = thaw_json(state.domains['sect'])
        counter = state.identity['instance_counter']
        for kind in ('pasture', 'spring'):
            if not any(row['definition_id'] == kind for row in sect['buildings'].values()):
                counter += 1
                sect['buildings'][f'{state.save_id}:1:i:{counter}'] = {
                    'definition_id': kind, 'level': 1, 'construction_target': None}
        disciples = thaw_json(state.domains['disciples'])
        disciples['assignments'] = {}
        state = replace(state, identity={**state.identity, 'instance_counter': counter},
                        domains={**state.domains, 'inventory': stock, 'sect': sect,
                                 'disciples': disciples, 'automation': policy.initial()})
        with SQLiteSave.initialize(self.path, allowed_root=self.root) as store:
            EcologyApplication(store, self.registry, self.clock).create(state)

    def read(self):
        with SQLiteSave(self.path, allowed_root=self.root) as store:
            return EcologyApplication(store, self.registry, self.clock).query(self.sid)

    def view(self):
        with SQLiteSave(self.path, allowed_root=self.root) as store:
            return EcologyApplication(store, self.registry, self.clock).view(self.sid)

    def bid(self, kind):
        return next(bid for bid, row in self.read().domains['sect']['buildings'].items()
                    if row['definition_id'] == kind)

    def request(self, name, payload):
        state = self.read()
        return Command(self.sid, state.generation, state.revision, str(uuid4()), name, payload)

    def execute(self, request):
        with SQLiteSave(self.path, allowed_root=self.root) as store:
            return EcologyApplication(store, self.registry, self.clock).execute(request)

    def command(self, name, payload):
        return self.execute(self.request(name, payload))

    def settle(self, elapsed=0, max_events=128):
        self.clock.advance(elapsed)
        for _ in range(100):
            with SQLiteSave(self.path, allowed_root=self.root) as store:
                app = EcologyApplication(store, self.registry, self.clock)
                state = app.query(self.sid)
                app.settle(SettlementRequest(self.sid, state.generation, state.revision, str(uuid4()),
                                             max_events, Continuation.for_state(state) if state.time['pending'] else None))
                if not app.query(self.sid).time['pending']:
                    return
        self.fail('bounded settlement did not converge')

    def fixture(self, change):
        with SQLiteSave(self.path, allowed_root=self.root) as store:
            with store.transaction():
                app = EcologyApplication(store, self.registry, self.clock)
                original = app.query(self.sid)
                candidate = replace(change(original), revision=original.revision + 1)
                app.foundation.validate_state(candidate)
                store.commit(original, candidate, StoredReceipt(self.sid, candidate.generation,
                             str(uuid4()), '0' * 64, candidate.revision, 'command', {}))

    def remove(self, rid):
        def change(state):
            stock = thaw_json(state.domains['inventory'])
            stock['holdings'].pop(rid, None)
            return replace(state, domains={**state.domains, 'inventory': stock})
        self.fixture(change)

    def assign(self, kind):
        self.command('work_assign', {'building_id': self.bid(kind), 'count': 1})

    def buy(self, species='pasture_species_02', count=1):
        kind = next(row['building_kind'] for row in settings(self.registry)['species'] if row['id'] == species)
        return self.command('ecology_buy', {'building_id': self.bid(kind), 'species_id': species, 'count': count}).result['batch_id']

    def test_catalog_and_read_are_pure(self):
        before = self.read()
        view = self.view()
        self.assertEqual(24, len(view['ecology']['species']))
        self.assertEqual(27, len(view['ecology']['meals']))
        self.assertEqual(before, self.read())
        self.assertFalse(view['ecology']['supply']['activated'])

    def test_purchase_pays_money_once_and_live_stock_not_inventory(self):
        self.assign('pasture')
        before = self.read()
        request = self.request('ecology_buy', {'building_id': self.bid('pasture'), 'species_id': 'pasture_species_02', 'count': 2})
        receipt = self.execute(request)
        after = self.read()
        self.assertEqual(24, before.domains['inventory']['holdings']['coins'] - after.domains['inventory']['holdings']['coins'])
        self.assertEqual(2, after.domains['ecology']['batches'][receipt.result['batch_id']]['count'])
        self.assertEqual(receipt, self.execute(request))
        self.assertEqual(after, self.read())
        self.assertFalse(any(key.startswith('pasture_species') for key in after.domains['inventory']['holdings']))

    def test_capacity_and_wrong_building_are_atomic(self):
        before = self.read()
        with self.assertRaises(ValidationError):
            self.buy(count=9)
        with self.assertRaises(ValidationError):
            self.command('ecology_buy', {'building_id': self.bid('spring'), 'species_id': 'pasture_species_02', 'count': 1})
        self.assertEqual(before, self.read())

    def test_chicken_matures_then_full_cycle_and_collects_once(self):
        self.assign('pasture')
        identity = self.buy()
        self.settle(120000)
        self.assertEqual('MATURE', self.read().domains['ecology']['batches'][identity]['stage'])
        self.assertNotIn('egg', self.read().domains['inventory']['holdings'])
        self.settle(120000)
        self.assertEqual('READY', self.read().domains['ecology']['batches'][identity]['stage'])
        request = self.request('ecology_collect', {'batch_id': identity, 'mode': 'periodic', 'count': 1})
        receipt = self.execute(request)
        after = self.read()
        self.assertEqual(4, after.domains['inventory']['holdings']['egg'])
        self.assertEqual(receipt, self.execute(request))
        self.assertEqual(after, self.read())
        with self.assertRaises(ValidationError):
            self.command('ecology_collect', {'batch_id': identity, 'mode': 'harvest', 'count': 1})

    def test_no_feed_no_growth_no_debt(self):
        self.remove('beast_feed_basic')
        self.assign('pasture')
        identity = self.buy()
        self.settle(1200000)
        row = self.read().domains['ecology']['batches'][identity]
        self.assertEqual(0, row['progress_milli'])
        self.assertEqual(0, row['feed_paid'])
        self.assertEqual('JUVENILE', row['stage'])

    def test_pause_freezes_growth_and_supply(self):
        self.assign('pasture')
        self.buy()
        self.command('ecology_supply', {'enabled': True, 'target_days': 3})
        self.command('world_pause', {})
        before = self.read()
        self.clock.advance(1200000)
        self.command('world_resume', {})
        after = self.read()
        self.assertEqual(before.domains, after.domains)
        self.assertEqual(before.time['sim_time_ms'], after.time['sim_time_ms'])

    def test_supply_daily_not_minutes_and_shortage_next_day(self):
        self.command('ecology_supply', {'enabled': True, 'target_days': 3})
        before = self.read().domains['inventory']['holdings']['meal_qingling_rice']
        self.settle(120000)
        state = self.read()
        self.assertEqual(before - 8, state.domains['inventory']['holdings']['meal_qingling_rice'])
        self.assertEqual(0, sum(state.domains['ecology']['supply']['hungry'].values()))
        self.remove('meal_qingling_rice')
        self.settle(120000)
        self.assertEqual(0, sum(self.read().domains['ecology']['supply']['hungry'].values()))
        self.settle(120000)
        self.assertEqual(8, sum(self.read().domains['ecology']['supply']['hungry'].values()))

    def test_disable_supply_does_not_reset_hunger(self):
        self.remove('meal_qingling_rice')
        self.command('ecology_supply', {'enabled': True, 'target_days': 3})
        self.settle(240000)
        self.command('ecology_supply', {'enabled': False, 'target_days': 3})
        self.assertTrue(self.read().domains['ecology']['supply']['activated'])
        self.assertEqual(8, sum(self.read().domains['ecology']['supply']['hungry'].values()))

    def test_facility_finishes_as_capacity_not_inventory(self):
        self.assign('garden')
        before = self.read()
        bid = self.bid('garden')
        self.command('production_start', {'building_id': bid, 'recipe_id': 'build_garden_plot'})
        started = self.read()
        self.assertEqual(before.domains['inventory']['holdings']['sect_lining'] - 1,
                         started.domains['inventory']['holdings']['sect_lining'])
        self.settle(120000)
        self.assertEqual(1, self.read().domains['ecology']['facilities'][bid]['garden_plot'])
        with self.assertRaises(ValidationError):
            self.command('production_start', {'building_id': bid, 'recipe_id': 'build_garden_plot'})

    def test_retired_recipes_and_supply_reject(self):
        before = self.read()
        with self.assertRaises(ValidationError):
            self.command('production_start', {'building_id': self.bid('canteen'), 'recipe_id': 'sect_food'})
        with self.assertRaises(ValidationError):
            self.command('sect_supply', {'enabled': True, 'reserve': 0})
        self.assertEqual(before, self.read())

    def test_purchase_write_failure_rolls_back_everything(self):
        before = self.read()
        request = self.request('ecology_buy', {'building_id': self.bid('pasture'), 'species_id': 'pasture_species_02', 'count': 1})
        with patch.object(SQLiteSave, 'commit', side_effect=RuntimeError('fixture failure')):
            with self.assertRaises(RuntimeError):
                self.execute(request)
        self.assertEqual(before, self.read())

    def test_max_event_segmentation_preserves_results(self):
        self.assign('pasture')
        identity = self.buy()
        self.command('ecology_supply', {'enabled': True, 'target_days': 3})
        self.settle(480000, max_events=1)
        state = self.read()
        self.assertEqual('READY', state.domains['ecology']['batches'][identity]['stage'])
        self.assertEqual(68, state.domains['inventory']['holdings']['meal_qingling_rice'])
        self.assertIsNone(state.time['pending'])

    def test_periodic_fraction_feed_is_paid_exactly_across_days(self):
        self.assign('pasture')
        identity = self.buy('pasture_species_03')  # 4 feed over 3 days
        before = self.read().domains['inventory']['holdings']['beast_feed_basic']
        self.settle(360000, max_events=1)
        row = self.read().domains['ecology']['batches'][identity]
        self.assertEqual('MATURE', row['stage'])
        # Four juvenile feed and the next production cycle's first-day funding.
        self.assertEqual(4 + row['feed_paid'], 100 - self.read().domains['inventory']['holdings']['beast_feed_basic'])
        self.assertEqual(2, 100 - before)

    def test_fish_harvest_removes_individuals_and_releases_capacity(self):
        self.assign('spring')
        identity = self.buy('spring_species_01', count=2)
        self.settle(120000)
        self.command('ecology_collect', {'batch_id': identity, 'mode': 'harvest', 'count': 2})
        after = self.read()
        self.assertNotIn(identity, after.domains['ecology']['batches'])
        species = settings(self.registry)['species'][12]
        rid = next(iter(species['harvest_outputs']))
        self.assertEqual(8, after.domains['inventory']['holdings'][rid])
        self.assertEqual(0, next(row for row in self.view()['ecology']['farms'] if row['building_kind'] == 'spring')['occupied'])

    def test_partial_collection_preserves_total_live_population(self):
        self.assign('pasture')
        identity = self.buy(count=2)
        self.settle(240000)
        self.command('ecology_collect', {'batch_id': identity, 'mode': 'periodic', 'count': 1})
        rows = self.read().domains['ecology']['batches']
        self.assertEqual(2, sum(row['count'] for row in rows.values()))
        self.assertEqual(1, sum(row['count'] for row in rows.values() if row['stage'] == 'READY'))
        self.assertEqual(4, self.read().domains['inventory']['holdings']['egg'])

    def test_full_inventory_keeps_ready_results_and_no_redraw_reward(self):
        self.assign('pasture')
        identity = self.buy()
        self.settle(240000)
        def fill(state):
            stock = thaw_json(state.domains['inventory'])
            from src.systems.inventory import holdings
            capacity = EcologyApplication(None, self.registry, self.clock)._capacity(state)
            stock['holdings']['stone'] += capacity - holdings.stock_size(stock, self.registry)
            return replace(state, domains={**state.domains, 'inventory': stock})
        self.fixture(fill)
        before = self.read()
        with self.assertRaises(ValidationError):
            self.command('ecology_collect', {'batch_id': identity, 'mode': 'periodic', 'count': 1})
        self.view()
        self.settle(120000)
        after = self.read()
        self.assertEqual(before.domains['inventory'], after.domains['inventory'])
        self.assertEqual('READY', after.domains['ecology']['batches'][identity]['stage'])

    def test_position_meal_speed_snapshot_and_no_double_food(self):
        self.assign('garden')
        rid = 'meal_qingyuan_herb_soup'
        self.fixture(lambda state: replace(state, domains={**state.domains, 'inventory': {
            **state.domains['inventory'], 'holdings': {**state.domains['inventory']['holdings'], rid: 5}}}))
        bid = self.bid('garden')
        self.command('ecology_meal', {'building_id': bid, 'meal_id': rid, 'enabled': True})
        self.assertEqual(4, self.read().domains['inventory']['holdings'][rid])
        self.command('production_start', {'building_id': bid, 'recipe_id': 'grow_sect_crop_01'})
        job = self.read().domains['production']['jobs'][bid]
        self.assertEqual(1120, job['work_rate_milli'])
        self.command('ecology_meal', {'building_id': bid, 'meal_id': rid, 'enabled': False})
        self.assertEqual(job, self.read().domains['production']['jobs'][bid])
        self.assertEqual(4, self.read().domains['inventory']['holdings'][rid])

    def test_work_unassign_stops_uncommitted_live_growth(self):
        self.assign('pasture')
        identity = self.buy()
        self.settle(10000)
        self.command('work_unassign', {'building_id': self.bid('pasture')})
        before = self.read().domains['ecology']['batches'][identity]['progress_milli']
        self.settle(120000)
        self.assertEqual(before, self.read().domains['ecology']['batches'][identity]['progress_milli'])

    def test_probability_result_is_stable_when_delivery_blocked(self):
        self.assign('garden')
        bid = self.bid('garden')
        self.command('production_start', {'building_id': bid, 'recipe_id': 'grow_sect_crop_01'})
        state = self.read()
        app = EcologyApplication(None, self.registry, self.clock)
        job = state.domains['production']['jobs'][bid]
        self.assertEqual(app.delivery_outputs(state, job), app.delivery_outputs(state, job))

    def test_new_meals_use_real_inputs_and_commit_results(self):
        self.assign('canteen')
        before = self.read()
        bid = self.bid('canteen')
        self.command('production_start', {'building_id': bid, 'recipe_id': 'meal_qingling_rice'})
        started = self.read()
        self.assertEqual(before.domains['inventory']['holdings']['sect_crop_01'] - 4,
                         started.domains['inventory']['holdings']['sect_crop_01'])
        self.settle(30000)
        self.assertEqual(before.domains['inventory']['holdings']['meal_qingling_rice'] + 4,
                         self.read().domains['inventory']['holdings']['meal_qingling_rice'])

    def test_fixed_facility_quote_with_multiple_workers(self):
        bid = self.bid('garden')
        self.command('work_assign', {'building_id': bid, 'count': 2})
        def exact(state):
            stock = thaw_json(state.domains['inventory'])
            definition = jobs.definition(self.registry, 'build_garden_plot')
            stock['holdings'].update(dict(definition.inputs))
            return replace(state, domains={**state.domains, 'inventory': stock})
        self.fixture(exact)
        row = next(row for row in self.view()['economy']['recipes'] if row['recipe_id'] == 'build_garden_plot')
        self.assertTrue(row['can_start'], row['blocking_reasons'])
        self.command('production_start', {'building_id': bid, 'recipe_id': 'build_garden_plot'})

    def test_fresh_process_preserves_stock_supply_and_receipt(self):
        self.assign('pasture')
        request = self.request('ecology_buy', {'building_id': self.bid('pasture'), 'species_id': 'pasture_species_02', 'count': 2})
        receipt = self.execute(request)
        self.command('ecology_supply', {'enabled': True, 'target_days': 3})
        self.settle(60000)
        before = self.read().to_dict()
        code = '''import json,sys
from pathlib import Path
from src.application.ecology import EcologyApplication
from src.data.dungeons.definitions import load_dungeons
from src.core.save.sqlite import SQLiteSave
from tests.fixtures.time import ManualClock
with SQLiteSave(Path(sys.argv[1]),allowed_root=Path(sys.argv[2])) as store:
 app=EcologyApplication(store,load_dungeons(management=True,cold_jade=True,ecology=True),ManualClock())
 print(json.dumps(app.query(sys.argv[3]).to_dict()))
'''
        result = subprocess.run([sys.executable, '-B', '-c', code, str(self.path), str(self.root), self.sid],
                                check=True, capture_output=True, text=True, timeout=30)
        self.assertEqual(before, json.loads(result.stdout))
        self.assertEqual(receipt, self.execute(request))
        self.assertEqual(before, self.read().to_dict())

    def test_recovery_restores_live_stock_and_old_request_is_stale(self):
        self.assign('pasture')
        request = self.request('ecology_buy', {'building_id': self.bid('pasture'), 'species_id': 'pasture_species_02', 'count': 1})
        self.execute(request)
        source = self.read()
        with SQLiteSave(self.path, allowed_root=self.root) as store:
            EcologyApplication(store, self.registry, self.clock).checkpoint(self.sid)
        self.settle(240000)
        with SQLiteSave(self.path, allowed_root=self.root) as store:
            app = EcologyApplication(store, self.registry, self.clock)
            recovery = RecoveryApplication(app.foundation, self.clock)
            observation = recovery.inspect(self.sid)
            result = recovery.recover(RecoveryRequest(self.sid, observation.current_generation,
                observation.current_fingerprint, observation.source_fingerprint, str(uuid4()), 'TEST ecology recovery'))
            self.assertEqual('SUCCESS', result.status)
        restored = self.read()
        self.assertEqual(source.domains, restored.domains)
        self.assertEqual(2, restored.generation)
        with self.assertRaises(ConflictError):
            self.execute(request)
        self.settle(240000)
        self.assertEqual('READY', next(iter(self.read().domains['ecology']['batches'].values()))['stage'])

    def test_corrupt_successor_and_excess_probability_rejected(self):
        self.assign('garden')
        self.command('ecology_supply', {'enabled': True, 'target_days': 3})
        before = self.read()
        def invalid(state):
            part = thaw_json(state.domains['ecology'])
            part['wake']['next_event_id'] = part['wake']['event_id']
            return replace(state, domains={**state.domains, 'ecology': part})
        with self.assertRaises(ValidationError):
            self.fixture(invalid)
        self.assertEqual(before, self.read())
        self.command('production_start', {'building_id': self.bid('garden'), 'recipe_id': 'grow_sect_crop_01'})
        before = self.read()
        def forged(state):
            part = thaw_json(state.domains['ecology'])
            next(iter(part['job_effects'].values()))['extra_bps'] = 10000
            return replace(state, domains={**state.domains, 'ecology': part})
        with self.assertRaises(ValidationError):
            self.fixture(forged)
        self.assertEqual(before, self.read())

    def test_every_species_has_real_paid_feed_and_collectible_outputs(self):
        self.assign('pasture')
        self.assign('spring')
        for species in settings(self.registry)['species']:
            with self.subTest(species=species['id']):
                def supplies(state):
                    stock = {'holdings': {'coins': 10000, species['feed_id']: 100}}
                    return replace(state, domains={**state.domains, 'inventory': stock})
                self.fixture(supplies)
                identity = self.buy(species['id'])
                self.settle(species['days'] * 120000)
                self.assertEqual('MATURE', self.read().domains['ecology']['batches'][identity]['stage'])
                if species['periodic_outputs']:
                    self.settle(species['days'] * 120000)
                    self.command('ecology_collect', {'batch_id': identity, 'mode': 'periodic', 'count': 1})
                    for rid, quantity in species['periodic_outputs'].items():
                        self.assertEqual(quantity, self.read().domains['inventory']['holdings'][rid])
                    self.settle(1)
                self.command('ecology_collect', {'batch_id': identity, 'mode': 'harvest', 'count': 1})
                for rid, quantity in species['harvest_outputs'].items():
                    self.assertEqual(quantity + species['periodic_outputs'].get(rid, 0),
                                     self.read().domains['inventory']['holdings'][rid])
                self.assertNotIn(identity, self.read().domains['ecology']['batches'])


    def test_preparation_costs_sources_and_views_are_pure(self):
        before=self.read()
        for _ in range(2):
            p=self.view()['preparation']
            self.assertEqual(p['phase'],'prepare')
            self.assertEqual(p['sources']['bone_floor'],6)
            self.assertFalse(p['sources']['bone_enterable'])
            self.assertEqual(p['sources']['ingot_floor'],0)
            costs={r['resource_id']:r for r in p['blade']['requirements']}
            self.assertEqual({k:r['quantity'] for k,r in costs.items()},{'ingot':15,'thorn_boar_bone':15,'coins':300})
            for rid,row in costs.items():
                self.assertEqual(row['current'],before.domains['inventory']['holdings'].get(rid,0))
                self.assertEqual(row['missing'],max(0,row['quantity']-row['current']))
            self.assertEqual(before,self.read())

    def test_preparation_owned_blade_and_defense_follow_actual_instances(self):
        from src.application import equipment as equip
        identities=[]
        def acquire(state):
            for key in ('thorn_fang_blade','thorn_pattern_robe'):
                state,identity=equip.acquire(state,self.registry,key,'preparation:'+key)
                identities.append(identity)
            return state
        self.fixture(acquire)
        p=self.view()['preparation']
        self.assertTrue(p['blade']['owned']);self.assertFalse(p['blade']['equipped'])
        self.assertEqual(p['unequipped_defense'],1)
        self.command('equipment_equip',{'instance_id':identities[0]})
        self.command('equipment_equip',{'instance_id':identities[1]})
        p=self.view()['preparation']
        self.assertTrue(p['blade']['equipped']);self.assertEqual(p['unequipped_defense'],0)

    def test_preparation_advanced_save_skips_crafting_and_respects_supply_target(self):
        def advance(state):
            dungeon=thaw_json(state.domains['dungeon']);dungeon['cleared_floor']=100;dungeon['selected_id']='red_copper_mine'
            return replace(state,domains={**state.domains,'dungeon':dungeon})
        self.fixture(advance)
        p=self.view()['preparation']
        self.assertEqual(p['cleared_floor'],100);self.assertFalse(p['selected_thorn'])
        self.assertEqual(p['phase'],'supply')
        self.command('ecology_supply',{'enabled':True,'target_days':7})
        before=self.read();p=self.view()['preparation']
        self.assertEqual(p['phase'],'development')
        self.assertEqual(p['supply']['suggested_stock'],24)
        self.assertEqual(p['supply']['target_days'],7)
        self.assertEqual(before,self.read())

    def test_preparation_spring_quote_for_advanced_save_without_spring(self):
        def change(state):
            sect=thaw_json(state.domains['sect'])
            sect['buildings']={k:v for k,v in sect['buildings'].items() if v['definition_id']!='spring'}
            dungeon=thaw_json(state.domains['dungeon']);dungeon['cleared_floor']=10
            return replace(state,domains={**state.domains,'sect':sect,'dungeon':dungeon})
        self.fixture(change)
        p=self.view()['preparation'];self.assertEqual(p['phase'],'spring')
        self.assertFalse(p['spring']['exists'])
        self.assertEqual({r['resource_id']:r['quantity'] for r in p['spring']['requirements']},
                         {'wood':15,'stone':10,'coins':150,'spirit_stone_low':1,'ordinary_wood':10})

    def test_preparation_water_uses_actual_offers_prices_and_remaining_stock(self):
        from src.systems.sect import market
        with patch('src.systems.sect.market.current_offers',return_value=()):
            self.assertFalse(self.view()['preparation']['water']['listed'])
        with patch('src.systems.sect.market.current_offers',return_value=('spring_water',)):
            view=self.view();water=view['preparation']['water'];offer=view['sect_services']['market']['offers'][0]
            self.assertTrue(water['listed']);self.assertEqual(water['price'],offer['price'])
            self.assertEqual(water['remaining'],offer['remaining_stock'])
            self.command('market_buy',{'resource_id':'spring_water','quantity':100,'market_day':market.day(self.read()),
                         'price_milli':market.price(self.registry,self.sid,market.day(self.read()),'spring_water')['buy_price_milli']})
            water=self.view()['preparation']['water']
            self.assertEqual(water['remaining'],0);self.assertEqual(water['max_quantity'],0)

    def test_preparation_technique_uses_initial_bonus_and_saved_equipped_state(self):
        key='manual_a00f304b07a9a'
        p=self.view()['preparation']['technique']
        self.assertFalse(p['owned']);self.assertEqual(p['level'],1)
        self.assertEqual({r['name']:r['amount'] for r in p['bonuses']},{'生命':3,'护甲':0.1})
        self.assertEqual(p['requirements'][0]['quantity'],200)
        self.command('technique_buy',{'technique_id':key})
        p=self.view()['preparation']['technique'];self.assertTrue(p['owned']);self.assertFalse(p['equipped'])
        self.command('technique_equip',{'technique_id':key,'slot':'defense'})
        before=self.read();p=self.view()['preparation']['technique']
        self.assertTrue(p['equipped']);self.assertEqual(len(p['requirements']),0)
        self.assertEqual(before,self.read())

    def test_preparation_paused_view_reports_status_without_advancing(self):
        self.command('world_pause',{})
        before=self.read();p=self.view()['preparation']
        self.assertTrue(p['paused']);self.assertFalse(p['pending']);self.assertEqual(before,self.read())


    def test_preparation_pending_projection_is_pure_and_reports_continuation(self):
        for kind,recipe in (('spring','sect_spring_water'),('mine','ore')):
            self.assign(kind)
            self.command('production_start',{'building_id':self.bid(kind),'recipe_id':recipe})
        self.clock.advance(300000)
        with SQLiteSave(self.path,allowed_root=self.root) as store:
            app=EcologyApplication(store,self.registry,self.clock)
            state=app.query(self.sid)
            app.settle(SettlementRequest(self.sid,state.generation,state.revision,str(uuid4()),1,None))
        before=self.read()
        self.assertIsNotNone(before.time['pending'])
        p=self.view()['preparation']
        self.assertTrue(p['pending']);self.assertEqual(before,self.read())

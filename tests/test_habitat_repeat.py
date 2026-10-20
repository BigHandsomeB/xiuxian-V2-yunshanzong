"""Repeated crops and placed husbandry over isolated SQLite/world time."""
import unittest
from dataclasses import replace
from unittest.mock import patch
from src.core.state.envelope import thaw_json
from src.core.save.sqlite import SQLiteSave
from src.core.validation import ValidationError
from src.systems.resources import jobs
from src.data.economy.ecology import lookup
from tests.systems import test_ecology as fixtures


class HabitatRepeatTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.EcologyTests.setUpClass.__func__)
    for name in ('setUp','read','view','bid','request','execute','command','settle','fixture','assign','remove'):
        locals()[name] = getattr(fixtures.EcologyTests,name)

    def plant(self):
        bid=self.bid('garden');self.assign('garden')
        self.command('garden_reclaim',{'building_id':bid,'plot_index':0})
        self.command('garden_plant',{'building_id':bid,'plot_index':0,'recipe_id':'herb'})
        return bid

    def test_garden_repeats_pays_each_cycle_and_can_stop(self):
        bid=self.plant();started=self.read();water=started.domains['inventory']['holdings']['spring_water']
        duration=jobs.definition(self.registry,'herb').duration_ms
        self.settle(duration*2)
        after=self.read();plant=after.domains['ecology']['garden'][bid]['0']
        self.assertIsNotNone(plant)
        self.assertEqual(after.domains['inventory']['holdings']['spring_water'],water-2)
        self.assertEqual(after.domains['inventory']['holdings'].get('herb',0),started.domains['inventory']['holdings'].get('herb',0)+6)
        self.command('garden_repeat',{'building_id':bid,'plot_index':0,'enabled':False})
        self.settle(duration)
        self.assertIsNone(self.read().domains['ecology']['garden'][bid]['0'])

    def test_garden_waits_for_water_then_resumes_without_new_click(self):
        bid=self.plant();self.remove('spring_water');self.settle(jobs.definition(self.registry,'herb').duration_ms)
        self.assertEqual(self.view()['ecology']['gardens'][0]['plots'][0]['state'],'REPLANT_WAIT')
        before=self.read().domains['inventory']['holdings'].get('herb',0);self.settle(5000)
        self.assertEqual(before,self.read().domains['inventory']['holdings'].get('herb',0))
        def add(state):
            stock=thaw_json(state.domains['inventory']);stock['holdings']['spring_water']=5
            return replace(state,domains={**state.domains,'inventory':stock})
        self.fixture(add);self.settle(1)
        self.assertEqual(self.read().domains['inventory']['holdings']['spring_water'],4)
        self.assertEqual(self.view()['ecology']['gardens'][0]['plots'][0]['state'],'GROWING')

    def test_repeat_choice_survives_reopen_and_stale_replay(self):
        bid=self.plant();q=self.request('garden_repeat',{'building_id':bid,'plot_index':0,'enabled':False})
        r=self.execute(q);before=self.read();self.assertEqual(r,self.execute(q));self.assertEqual(before,self.read())
        self.assertFalse(self.view()['ecology']['gardens'][0]['plots'][0]['repeat'])

    def stock(self,kind='pasture',species='pasture_species_02',index=0):
        bid=self.bid(kind);self.assign(kind)
        q=self.request('habitat_stock',{'building_id':bid,'slot_index':index,'species_id':species})
        r=self.execute(q);return bid,q,r.result['batch_id']

    def test_pinned_stock_has_real_cells_costs_and_replay(self):
        before=self.read();bid,q,identity=self.stock(index=3);saved=self.read();self.execute(q);self.assertEqual(saved,self.read())
        h=next(r for r in self.view()['ecology']['habitats'] if r['building_id']==bid)
        self.assertEqual(h['cells'][3]['batch_id'],identity)
        self.assertTrue(saved.domains['ecology']['batches'][identity]['repeat'])
        cost=lookup(self.registry,'species','pasture_species_02')['purchase_coins']
        self.assertEqual(saved.domains['inventory']['holdings']['coins'],before.domains['inventory']['holdings']['coins']-cost)

    def test_periodic_auto_collect_keeps_animal_and_slot(self):
        bid,q,identity=self.stock();before=self.read();self.settle(240000)
        after=self.read();row=after.domains['ecology']['batches'][identity]
        self.assertEqual(row['cycle'],1);self.assertEqual(row['slot_index'],0);self.assertEqual(row['stage'],'MATURE')
        self.assertEqual(after.domains['inventory']['holdings']['coins'],before.domains['inventory']['holdings']['coins'])
        for rid,n in lookup(self.registry,'species',row['species_id'])['periodic_outputs'].items():
            self.assertEqual(after.domains['inventory']['holdings'].get(rid,0),before.domains['inventory']['holdings'].get(rid,0)+n)

    def test_fish_harvest_pays_to_restock_and_retains_pool(self):
        bid,q,identity=self.stock('spring','spring_species_01',4);before=self.read();self.settle(120000)
        after=self.read();rows=[r for r in after.domains['ecology']['batches'].values() if r['building_id']==bid]
        self.assertEqual(len(rows),1);self.assertNotIn(identity,after.domains['ecology']['batches'])
        self.assertEqual(rows[0]['slot_index'],4);self.assertEqual(rows[0]['stage'],'JUVENILE')
        species=lookup(self.registry,'species','spring_species_01')
        self.assertEqual(after.domains['inventory']['holdings']['coins'],before.domains['inventory']['holdings']['coins']-species['purchase_coins'])

    def test_missing_restock_money_keeps_mature_fish_without_free_reward(self):
        bid,q,identity=self.stock('spring','spring_species_01',1);self.remove('coins');before=self.read();self.settle(120000)
        after=self.read();self.assertIn(identity,after.domains['ecology']['batches']);self.assertEqual(after.domains['ecology']['batches'][identity]['stage'],'MATURE')
        for rid in lookup(self.registry,'species','spring_species_01')['harvest_outputs']:
            self.assertEqual(after.domains['inventory']['holdings'].get(rid,0),before.domains['inventory']['holdings'].get(rid,0))

    def test_stop_auto_allows_manual_collect(self):
        bid,q,identity=self.stock();self.command('habitat_repeat',{'batch_id':identity,'enabled':False});self.settle(240000)
        self.assertEqual(self.read().domains['ecology']['batches'][identity]['stage'],'READY')
        self.command('ecology_collect',{'batch_id':identity,'mode':'periodic','count':1})
        self.assertEqual(self.read().domains['ecology']['batches'][identity]['stage'],'MATURE')

    def test_grid_collision_capacity_missing_worker_are_atomic(self):
        bid,q,identity=self.stock(index=1)
        for index in (1,999):
            before=self.read()
            with self.assertRaises(ValidationError):self.command('habitat_stock',{'building_id':bid,'slot_index':index,'species_id':'pasture_species_02'})
            self.assertEqual(before,self.read())
        before=self.read()
        with self.assertRaises(ValidationError):self.command('habitat_stock',{'building_id':bid,'slot_index':3,'species_id':'pasture_species_02'})
        self.assertEqual(before,self.read())

    def test_large_beast_occupies_one_cell(self):
        bid,q,identity=self.stock('pasture','pasture_species_03',2)
        h=next(r for r in self.view()['ecology']['habitats'] if r['building_id']==bid)
        self.assertEqual([c['index'] for c in h['cells'] if c.get('batch_id')==identity],[2])
        self.assertTrue(h['cells'][2]['primary']);self.assertNotIn('batch_id',h['cells'][3])

    def test_missing_feed_pauses_without_fabricating_growth(self):
        bid,q,identity=self.stock();self.remove('beast_feed_basic');self.settle(240000)
        row=self.read().domains['ecology']['batches'][identity];self.assertEqual(row['progress_milli'],0)

    def test_worker_removal_pauses_then_resumes(self):
        bid,q,identity=self.stock();self.settle(1000);self.command('work_unassign',{'building_id':bid})
        before=self.read().domains['ecology']['batches'][identity]['progress_milli'];self.settle(10000)
        self.assertEqual(before,self.read().domains['ecology']['batches'][identity]['progress_milli'])
        self.assign('pasture');self.settle(1000);self.assertGreater(self.read().domains['ecology']['batches'][identity]['progress_milli'],before)

    def test_write_fault_preserves_coins_slots_and_receipt(self):
        self.assign('pasture');before=self.read();q=self.request('habitat_stock',{'building_id':self.bid('pasture'),'slot_index':0,'species_id':'pasture_species_02'})
        with patch.object(SQLiteSave,'commit',side_effect=RuntimeError('isolated fault')):
            with self.assertRaises(RuntimeError):self.execute(q)
        self.assertEqual(before,self.read());self.execute(q)

    def test_legacy_stock_view_is_read_only(self):
        self.command('ecology_buy',{'building_id':self.bid('pasture'),'species_id':'pasture_species_02','count':2})
        before=self.read();h=next(r for r in self.view()['ecology']['habitats'] if r['kind']=='pasture')
        self.assertEqual(sum('batch_id' in c for c in h['cells']),2);self.assertEqual(before,self.read())

    def test_full_warehouse_keeps_fish_and_does_not_charge_restock(self):
        bid,q,identity=self.stock('spring','spring_species_01',1)
        def fill(state):
            from src.application import sect
            from src.systems.inventory import holdings
            stock=thaw_json(state.domains['inventory'])
            free=sect.capacity_source(state,self.registry)['effective']-holdings.stock_size(stock,self.registry)
            stock['holdings']['stone']=stock['holdings'].get('stone',0)+free
            return replace(state,domains={**state.domains,'inventory':stock})
        self.fixture(fill);before=self.read().domains['inventory'];self.settle(120000)
        self.assertEqual(before,self.read().domains['inventory']);self.assertIn(identity,self.read().domains['ecology']['batches'])
        self.remove('stone');self.settle(1)
        self.assertNotIn(identity,self.read().domains['ecology']['batches'])

    def test_repeated_fish_online_offline_results_match(self):
        self.stock('spring','spring_species_01',2);before=self.read()
        from src.application.ecology import EcologyApplication
        from src.core.time.model import Continuation
        with SQLiteSave(self.path,allowed_root=self.root) as store:
            app=EcologyApplication(store,self.registry,self.clock)
            def advance(state,target):
                for _ in range(50):
                    state,_=app.engine.advance(state,now_ms=None if state.time['pending'] else target,max_events=128,continuation=Continuation.for_state(state) if state.time['pending'] else None)
                    if not state.time['pending']:return state
                self.fail('bounded fixture did not converge')
            start=before.time['last_settled_at_ms'];one=advance(before,start+360000);split=before
            for n in range(1,7):split=advance(split,start+n*60000)
            self.assertEqual(one.domains['inventory'],split.domains['inventory'])
            self.assertEqual(one.domains['ecology']['batches'],split.domains['ecology']['batches'])

    def test_repeated_garden_online_offline_results_match(self):
        self.plant();before=self.read()
        from src.application.ecology import EcologyApplication
        from src.core.time.model import Continuation
        with SQLiteSave(self.path,allowed_root=self.root) as store:
            app=EcologyApplication(store,self.registry,self.clock)
            def advance(state,target):
                for _ in range(50):
                    state,_=app.engine.advance(state,now_ms=None if state.time['pending'] else target,max_events=1,continuation=Continuation.for_state(state) if state.time['pending'] else None)
                    if not state.time['pending']:return state
                self.fail('bounded fixture did not converge')
            start=before.time['last_settled_at_ms'];one=advance(before,start+180000);split=before
            for n in range(1,7):split=advance(split,start+n*30000)
            self.assertEqual(one.domains['inventory'],split.domains['inventory'])
            self.assertEqual(one.domains['ecology']['garden'],split.domains['ecology']['garden'])

    def test_long_offline_husbandry_report_remains_readable(self):
        self.stock('spring','spring_species_01',2);self.settle(600000)
        view=self.view()
        self.assertIn('offline_reports',view)
        self.assertEqual(len(next(r for r in view['ecology']['habitats'] if r['kind']=='spring')['cells']),12)

    def test_every_species_uses_one_cell_for_individual_and_legacy_cohorts(self):
        from src.data.economy.ecology import settings
        from src.systems.sect import habitats, ecology
        from copy import deepcopy
        for species in settings(self.registry)['species']:
            with self.subTest(species=species['id']):
                self.assertEqual(species['slots'],1)
                bid=self.bid(species['building_kind'])
                part={'batches':{'legacy':{'building_id':bid,'species_id':species['id'],'count':3}}}
                before=deepcopy(part)
                cells=habitats.layout(part,self.registry,bid,4)
                self.assertEqual(sum(c is not None for c in cells),3)
                self.assertEqual(ecology.occupied(part,self.registry,bid),3)
                part['batches']['legacy'].update(count=1,slot_index=3)
                cells=habitats.layout(part,self.registry,bid,4)
                self.assertIsNotNone(cells[3]);self.assertEqual(sum(c is not None for c in cells),1)
                self.assertEqual(before['batches']['legacy']['count'],3)

    def test_large_species_can_use_last_cell_and_adjacent_cell(self):
        from src.systems.sect import ecology
        bid=self.bid('pasture')
        self.command('work_assign',{'building_id':bid,'count':2})
        capacity=ecology.capacity(self.read(),self.registry,bid)
        ids=[]
        for index in (capacity-1,capacity-2):
            r=self.command('habitat_stock',{'building_id':bid,'slot_index':index,'species_id':'pasture_species_06'})
            ids.append(r.result['batch_id'])
        before=self.read();h=next(r for r in self.view()['ecology']['habitats'] if r['building_id']==bid)
        self.assertEqual(before,self.read())
        self.assertEqual([c['index'] for c in h['cells'] if c.get('batch_id') in ids],[capacity-2,capacity-1])
        self.assertEqual(ecology.occupied(before.domains['ecology'],self.registry,bid),2)

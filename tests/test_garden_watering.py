"""Real watering deduction and replay over isolated authoritative saves."""
import unittest
from dataclasses import replace
from src.core.state.envelope import thaw_json
from src.core.validation import ValidationError
from src.core.save.sqlite import SQLiteSave
from tests.systems import test_sect_management as fixtures

class GardenWateringTests(unittest.TestCase):
    setUp=fixtures.ManagementTests.setUp
    app=fixtures.ManagementTests.app
    read=fixtures.ManagementTests.read
    view=fixtures.ManagementTests.view
    q=fixtures.ManagementTests.q
    execute=fixtures.ManagementTests.execute
    cmd=fixtures.ManagementTests.cmd
    fixture=fixtures.ManagementTests.fixture
    settle=fixtures.ManagementTests.settle
    drain=fixtures.ManagementTests.drain

    def assign_garden(self,count=2):
        for bid in {a['building_id'] for g in self.view()['disciples']['groups'] for a in g['assignments']}:
            self.cmd('work_unassign',{'building_id':bid})
        bid=next(b['instance_id'] for b in self.view()['buildings'].values() if b['definition_id']=='garden')
        self.cmd('work_assign',{'building_id':bid,'count':count})
        return bid

    def test_charge_once_per_worker_and_complete_without_extra_water(self):
        bid=self.assign_garden()
        configured=self.read().domains['automation']['production'].get(bid)
        if configured and configured['enabled']:
            self.cmd('automation_production',{'building_id':bid,'policy':{**thaw_json(configured),'enabled':False}})
        before=self.read();request=self.q('production_start',{'building_id':bid,'recipe_id':'herb'})
        receipt=self.execute(request);started=self.read()
        self.assertEqual(started.domains['inventory']['holdings']['spring_water'],before.domains['inventory']['holdings']['spring_water']-2)
        self.assertEqual(self.execute(request),receipt);self.assertEqual(self.read(),started)
        row=next(r for r in self.view()['economy']['recipes'] if r['recipe_id']=='herb')
        self.assertEqual([(r['resource_id'],r['quantity']) for r in row['inputs']],[('spring_water',2)])
        job=started.domains['production']['jobs'][bid];self.clock.advance(job['due_ms']-job['started_ms']);self.drain()
        ended=self.read();self.assertEqual(ended.domains['inventory']['holdings']['spring_water'],started.domains['inventory']['holdings']['spring_water'])
        self.assertEqual(ended.domains['inventory']['holdings'].get('herb',0),before.domains['inventory']['holdings'].get('herb',0)+6)

    def test_shortage_preserves_entire_save(self):
        bid=self.assign_garden()
        def scarce(s):
            stock=thaw_json(s.domains['inventory']);stock['holdings']['spring_water']=1
            return replace(s,domains={**s.domains,'inventory':stock})
        self.fixture(scarce);before=self.read()
        with self.assertRaises(ValidationError):self.cmd('production_start',{'building_id':bid,'recipe_id':'herb'})
        self.assertEqual(self.read(),before)
        row=next(r for r in self.view()['economy']['recipes'] if r['recipe_id']=='herb');self.assertFalse(row['can_start'])

    def test_automatic_legacy_budget_does_not_block_watering(self):
        bid=self.assign_garden();before=self.read()
        with SQLiteSave(self.db,allowed_root=self.root) as store:
            app=self.app(store)
            started=app.start_candidate(before,bid,'herb',{'max_consumption':1,'reserves':{'spring_water':999999}})
            self.assertEqual(started.domains['production']['jobs'][bid]['status'],'WORKING')
            self.assertEqual(started.domains['inventory']['holdings']['spring_water'],before.domains['inventory']['holdings']['spring_water']-2)
        self.assertEqual(self.read(),before)

    def test_threshold_only_policy_runs_and_stops_with_real_water(self):
        bid=self.assign_garden();before=self.read();current=before.domains['inventory']['holdings'].get('herb',0)
        request=self.q('automation_production',{'building_id':bid,'policy':{'enabled':True,'recipe_id':'herb','target':current+1}})
        receipt=self.execute(request);saved=self.read();self.assertEqual(self.execute(request),receipt);self.assertEqual(self.read(),saved)
        self.drain();started=self.read();job=started.domains['production']['jobs'][bid]
        self.assertEqual(job['status'],'WORKING');self.assertEqual(started.domains['inventory']['holdings']['spring_water'],before.domains['inventory']['holdings']['spring_water']-2)
        self.clock.advance(job['due_ms']-job['started_ms']);self.drain();ended=self.read()
        self.assertEqual(ended.domains['production']['jobs'][bid]['status'],'COMPLETE');self.assertEqual(ended.domains['inventory']['holdings'].get('herb',0),current+6)
        self.clock.advance(60000);self.drain();self.assertEqual(self.read().domains['inventory']['holdings']['spring_water'],ended.domains['inventory']['holdings']['spring_water'])

    def test_grain_also_requires_water(self):
        bid=self.assign_garden();before=self.read();self.cmd('production_start',{'building_id':bid,'recipe_id':'grain'})
        after=self.read();self.assertEqual(after.domains['inventory']['holdings']['spring_water'],before.domains['inventory']['holdings']['spring_water']-2)
        row=next(r for r in self.view()['economy']['recipes'] if r['recipe_id']=='grain')
        self.assertEqual([(r['resource_id'],r['quantity']) for r in row['inputs']],[('spring_water',2)])

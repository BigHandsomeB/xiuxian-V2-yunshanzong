"""Recipe staffing through disposable SQLite, shared workers and original settlement."""
from dataclasses import replace
from unittest.mock import patch
import unittest
from uuid import uuid4
from src.core.state.envelope import thaw_json
from src.core.validation import ValidationError, ConflictError
from src.application import recipe_staffing
from src.systems.disciples import work, recipe_allocations as plans
from src.systems.economy import policy
from src.systems.resources import jobs
from tests import test_market_restock as fixtures


class RecipeStaffingTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.RestockTests.setUpClass.__func__)
    for name in ('app', 'read', 'view', 'request', 'command', 'fixture', 'settle'):
        locals()[name] = getattr(fixtures.RestockTests, name)

    def setUp(self):
        fixtures.RestockTests.setUp(self)
        self.alchemy = next(k for k, b in self.read().domains['sect']['buildings'].items() if b['definition_id']=='alchemy')
        def supply(s):
            return replace(s,domains={**s.domains,'inventory':{'holdings':{'coins':10000,'herb':40,'spring_water':10}}})
        self.fixture(supply)

    def adjust(self, rid='pill', delta=1, bid=None, request=None):
        return self.command('work_recipe_adjust', {'building_id':bid or self.alchemy,'recipe_id':rid,'delta':delta}, request)

    def model(self, bid=None):
        return next(b for b in self.view()['recipe_staffing']['buildings'] if b['building_id']==(bid or self.alchemy))

    def test_legacy_view_is_pure_and_never_migrates(self):
        before=self.read();model=self.model()
        self.assertTrue(model['rows']);self.assertTrue(all(r['count']==0 for r in model['rows']))
        self.assertNotIn('recipe_assignments',self.read().domains['disciples'])
        self.assertNotIn('recipe_production',self.read().domains['automation'])
        self.assertEqual(before,self.read())

    def test_two_recipes_have_independent_people_and_actual_inputs(self):
        self.adjust('pill');self.adjust('pill');self.adjust('ju_qi_pill')
        p=self.read().domains['disciples']
        self.assertEqual(work.capability(p,self.registry,self.alchemy,'pill')['workers'],2)
        self.assertEqual(work.capability(p,self.registry,self.alchemy,'ju_qi_pill')['workers'],1)
        self.assertEqual(work.capability(p,self.registry,self.alchemy)['workers'],3)
        self.command('production_start',{'building_id':self.alchemy,'recipe_id':'pill'})
        s=self.read();j=s.domains['production']['jobs'][self.alchemy]
        self.assertEqual(j['workers'],2);self.assertEqual(s.domains['inventory']['holdings']['herb'],30)
        self.assertEqual(sum(s.domains['disciples']['commitments'][j['job_id']]['workers'].values()),2)

    def test_round_robin_produces_both_recipes(self):
        self.adjust('pill');self.adjust('ju_qi_pill');self.settle()
        s=self.read();first=s.domains['production']['jobs'][self.alchemy]
        self.assertIn(first['recipe_id'],('pill','ju_qi_pill'))
        self.settle(first['due_ms']-s.time['sim_time_ms']+1)
        second=self.read().domains['production']['jobs'][self.alchemy]
        self.assertNotEqual(first['recipe_id'],second['recipe_id']);self.assertEqual(second['workers'],1)
        for rid,_ in jobs.definition(self.registry,first['recipe_id']).outputs:
            self.assertGreater(self.read().domains['inventory']['holdings'].get(rid,0),0)

    def test_decrease_active_recipe_preserves_batch_and_held_people(self):
        self.adjust('pill');self.adjust('pill');self.adjust('ju_qi_pill')
        self.command('production_start',{'building_id':self.alchemy,'recipe_id':'pill'})
        before=self.read();j=before.domains['production']['jobs'][self.alchemy]
        self.adjust('pill',-1);after=self.read();row=next(r for r in self.model()['rows'] if r['recipe_id']=='pill')
        self.assertEqual(after.domains['production'],before.domains['production'])
        self.assertEqual(after.domains['inventory'],before.domains['inventory'])
        self.assertEqual(row['count'],1);self.assertEqual(row['working'],2);self.assertEqual(row['pending_release'],1)
        self.assertEqual(self.model()['occupied'],3)
        self.settle(j['due_ms']-after.time['sim_time_ms']+1)
        self.assertEqual(self.model()['occupied'],2);self.assertEqual(self.model()['pending_release'],0)

    def test_same_cohort_does_not_lend_pending_worker_to_another_recipe(self):
        p=thaw_json(self.read().domains['disciples']);gid=next(iter(p['groups']))
        p['groups']={gid:{**p['groups'][gid],'count':3}}
        p['assignments']={gid:{self.alchemy:3}}
        p['recipe_assignments']={self.alchemy:{'pill':{gid:2},'ju_qi_pill':{gid:1}}}
        p['commitments']={'held-job':{'building_id':self.alchemy,'recipe_id':'pill','workers':{gid:2}}}
        work.validate(p,self.registry)
        reduced=plans.adjust(p,self.registry,self.alchemy,'pill',-1)
        self.assertEqual(work.allocations(reduced,gid)[self.alchemy],3)
        with self.assertRaises(ValidationError):plans.adjust(reduced,self.registry,self.alchemy,'ju_qi_pill',1)
        released=work.release_finished(reduced,self.registry,set())
        gained=plans.adjust(released,self.registry,self.alchemy,'ju_qi_pill',1)
        work.validate(gained,self.registry);self.assertEqual(work.capability(gained,self.registry,self.alchemy,'ju_qi_pill')['workers'],2)

    def test_legacy_running_job_is_attributed_only_to_actual_recipe(self):
        self.command('work_assign',{'building_id':self.alchemy,'count':2})
        self.command('production_start',{'building_id':self.alchemy,'recipe_id':'pill'})
        before=self.read();rows={r['recipe_id']:r for r in self.model()['rows']}
        self.assertEqual(rows['pill']['count'],2);self.assertEqual(rows['ju_qi_pill']['count'],0)
        self.assertEqual(before,self.read())
        self.adjust('pill',-1);self.assertEqual(self.read().domains['production'],before.domains['production'])
        self.assertEqual(self.model()['occupied'],2)

    def test_legacy_policy_preserved_and_new_recipe_policy_independent(self):
        self.command('work_assign',{'building_id':self.alchemy,'count':2})
        self.command('automation_production',{'building_id':self.alchemy,'policy':{'enabled':True,'recipe_id':'pill','target':7}})
        self.adjust('ju_qi_pill')
        queue=self.read().domains['automation']['recipe_production'][self.alchemy]
        self.assertEqual(queue['recipes']['pill']['target'],7)
        self.assertEqual(queue['recipes']['ju_qi_pill']['target'],30)
        self.assertEqual(work.capability(self.read().domains['disciples'],self.registry,self.alchemy,'pill')['workers'],2)
        self.command('automation_production',{'building_id':self.alchemy,'policy':{'enabled':False,'recipe_id':'ju_qi_pill','target':13}})
        queue=self.read().domains['automation']['recipe_production'][self.alchemy]
        self.assertTrue(queue['recipes']['pill']['enabled']);self.assertFalse(queue['recipes']['ju_qi_pill']['enabled'])
        self.assertEqual(queue['recipes']['pill']['target'],7)

    def test_replay_stale_and_conflicting_request(self):
        q=self.request('work_recipe_adjust',{'building_id':self.alchemy,'recipe_id':'pill','delta':1})
        receipt=self.adjust(request=q);before=self.read()
        self.assertEqual(self.adjust(request=q),receipt);self.assertEqual(self.read(),before)
        with self.assertRaises(ConflictError):self.adjust(request=replace(q,request_id=str(uuid4())))
        with self.assertRaises(ConflictError):self.adjust(request=replace(q,payload={'building_id':self.alchemy,'recipe_id':'pill','delta':-1}))

    def test_sql_failure_rolls_back_entire_allocation_and_queue(self):
        before=self.read();q=self.request('work_recipe_adjust',{'building_id':self.alchemy,'recipe_id':'pill','delta':1})
        with patch('src.core.save.sqlite.SQLiteSave._insert_receipt',side_effect=RuntimeError('after SQL write')):
            with self.assertRaises(RuntimeError):self.adjust(request=q)
        self.assertEqual(before,self.read())
        self.adjust(request=q);self.assertEqual(self.model()['assigned'],1)

    def test_bad_counts_wrong_recipe_and_zero_are_atomic(self):
        for rid,delta in [('pill',True),('pill',0),('pill',2),('pill',-1),('unknown',1),('herb',1)]:
            before=self.read()
            with self.subTest(rid=rid,delta=delta),self.assertRaises(ValidationError):self.adjust(rid,delta)
            self.assertEqual(before,self.read())

    def test_paused_and_pending_block_without_material_or_time_changes(self):
        self.command('world_pause',{});before=self.read()
        with self.assertRaises(ValidationError):self.adjust()
        self.assertEqual(before,self.read());self.assertTrue(self.view()['recipe_staffing']['blocked'])

    def test_unspecified_workers_reallocated_without_consuming_another_person(self):
        self.command('work_assign',{'building_id':self.alchemy,'count':2});idle=self.view()['recipe_staffing']['idle']
        self.adjust();self.assertEqual(self.model()['assigned'],2)
        self.assertEqual(self.view()['recipe_staffing']['idle'],idle)
        self.assertEqual(next(r for r in self.model()['rows'] if r['recipe_id']=='pill')['count'],1)

    def test_special_care_uses_real_shared_assignment(self):
        bid=next(k for k,b in self.read().domains['sect']['buildings'].items() if b['definition_id']=='garden')
        row=self.model(bid);self.assertFalse(row['recipe_mode']);self.assertIsNone(row['rows'][0]['recipe_id'])
        self.adjust(None,1,bid);self.assertEqual(self.model(bid)['assigned'],1)
        self.adjust(None,-1,bid);self.assertEqual(self.model(bid)['assigned'],0)

    def test_remove_all_legacy_controls_preserve_recipe_schema(self):
        self.adjust();self.adjust('ju_qi_pill');self.command('work_unassign',{'building_id':self.alchemy})
        self.assertEqual(self.model()['assigned'],0);self.assertTrue(all(r['count']==0 for r in self.model()['rows']))
        self.settle();self.assertNotIn(self.alchemy,self.read().domains['production']['jobs'])

    def test_automatic_targets_short_materials_and_reserves(self):
        self.adjust();self.adjust('ju_qi_pill')
        self.command('automation_production',{'building_id':self.alchemy,'policy':{'enabled':True,'recipe_id':'ju_qi_pill','target':30,'reserves':{'herb':40},'max_consumption':0}})
        self.settle();self.assertEqual(self.read().domains['production']['jobs'][self.alchemy]['recipe_id'],'pill')
        self.assertLess(self.read().domains['inventory']['holdings']['herb'],40)

    def test_tampered_quota_or_policy_rejected(self):
        self.adjust();state=self.read();part=thaw_json(state.domains['disciples'])
        gid=next(iter(part['recipe_assignments'][self.alchemy]['pill']))
        part['recipe_assignments'][self.alchemy]['pill'][gid]=999
        with self.assertRaises(ValidationError):work.validate(part,self.registry)
        auto=thaw_json(state.domains['automation']);auto['recipe_production'][self.alchemy]['recipes']['pill']['recipe_id']='herb'
        with self.assertRaises(ValidationError):policy.validate(auto,self.registry)

    def test_capacity_stops_plus_and_never_changes_inventory(self):
        from src.systems.sect import buildings
        capacity=buildings.work_slots(self.read().domains['sect'],self.registry,self.alchemy)
        for _ in range(capacity):self.adjust()
        before=self.read();self.assertFalse(next(r for r in self.model()['rows'] if r['recipe_id']=='pill')['can_add'])
        with self.assertRaises((ValidationError,ConflictError)):self.adjust()
        self.assertEqual(before,self.read())

    def test_unknown_or_historical_empty_job_has_no_fake_controls(self):
        bid=next(k for k,b in self.read().domains['sect']['buildings'].items() if b['definition_id']=='field')
        self.assertFalse(any(b['building_id']==bid for b in self.view()['recipe_staffing']['buildings']))
        before=self.read()
        with self.assertRaises(ValidationError):self.adjust(None,1,bid)
        self.assertEqual(before,self.read())

    def test_generic_legacy_controls_do_not_duplicate_held_recipe_workers(self):
        self.adjust();self.adjust();self.command('production_start',{'building_id':self.alchemy,'recipe_id':'pill'})
        self.adjust('pill',-1)
        before=self.model()['occupied'];self.command('work_assign',{'building_id':self.alchemy,'count':1})
        self.assertEqual(self.model()['occupied'],before+1)
        self.assertEqual(work.capability(self.read().domains['disciples'],self.registry,self.alchemy,'pill')['workers'],1)

    def test_closed_recipe_does_not_poll_using_obsolete_single_policy(self):
        self.command('work_assign',{'building_id':self.alchemy,'count':2})
        self.command('automation_production',{'building_id':self.alchemy,'policy':{'enabled':True,'recipe_id':'pill','target':30}})
        self.adjust('pill',-1)
        self.command('automation_production',{'building_id':self.alchemy,'policy':{'enabled':False,'recipe_id':'pill','target':30}})
        self.assertFalse(self.view()['economy']['needs_settlement'])

    def test_offline_and_segmented_production_are_equivalent(self):
        import shutil
        from tests.fixtures.time import ManualClock
        self.adjust();self.adjust('ju_qi_pill');self.settle()
        original=self.path;copy=self.root/'segmented.sqlite3';shutil.copy2(original,copy)
        now=self.clock.now_ms();self.settle(120000);offline=self.read()
        self.path=copy;self.clock=ManualClock(now)
        for _ in range(4):self.settle(30000)
        online=self.read()
        self.assertEqual(offline.domains['inventory'],online.domains['inventory'])
        self.assertEqual(offline.domains['disciples'],online.domains['disciples'])
        self.assertEqual(offline.domains['production'],online.domains['production'])
        self.assertEqual(offline.domains['automation']['recipe_production'],online.domains['automation']['recipe_production'])
        self.assertEqual(offline.time['sim_time_ms'],online.time['sim_time_ms'])


if __name__=='__main__':unittest.main()

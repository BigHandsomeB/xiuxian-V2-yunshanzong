import unittest
from unittest.mock import patch
from src.core.validation import ValidationError, ConflictError, NotFoundError
from tests.systems import test_sect_management as fixtures

class SharedWorkforceTests(unittest.TestCase):
    setUp=fixtures.ManagementTests.setUp
    app=fixtures.ManagementTests.app
    read=fixtures.ManagementTests.read
    view=fixtures.ManagementTests.view
    q=fixtures.ManagementTests.q
    execute=fixtures.ManagementTests.execute
    cmd=fixtures.ManagementTests.cmd
    settle=fixtures.ManagementTests.settle
    drain=fixtures.ManagementTests.drain

    def building(self,kind):
        return next(b['instance_id'] for b in self.view()['buildings'].values() if b['definition_id']==kind)

    def free_all(self):
        for bid in {a['building_id'] for g in self.view()['disciples']['groups'] for a in g['assignments']}:
            self.cmd('work_unassign',{'building_id':bid})

    def test_shared_assignment_crosses_old_cohorts_and_replays(self):
        self.free_all();before=self.read();bid=self.building('field');q=self.q('work_assign',{'building_id':bid,'count':5})
        receipt=self.execute(q);after=self.read();groups=self.view()['disciples']['groups']
        self.assertEqual(sum(g['available_count'] for g in groups),3)
        self.assertEqual(sum(g['allocations'].get(bid,0) for g in groups),5)
        self.assertGreater(sum(bid in targets for targets in after.domains['disciples']['assignments'].values()),1)
        self.assertEqual(before.domains['disciples']['groups'],after.domains['disciples']['groups'])
        self.assertEqual(self.execute(q),receipt);self.assertEqual(self.read(),after)

    def test_can_add_to_existing_shared_assignment(self):
        self.free_all();bid=self.building('field');self.cmd('work_assign',{'building_id':bid,'count':1});self.cmd('work_assign',{'building_id':bid,'count':2})
        self.assertEqual(self.view()['buildings'][bid]['assigned_count'],3)

    def test_capacity_and_idle_shortage_are_atomic(self):
        self.free_all();bid=self.building('field');before=self.read()
        with self.assertRaises((ValidationError,ConflictError)):self.cmd('work_assign',{'building_id':bid,'count':6})
        self.assertEqual(before,self.read());self.cmd('work_assign',{'building_id':bid,'count':5});before=self.read()
        with self.assertRaises((ValidationError,ConflictError)):self.cmd('work_assign',{'building_id':self.building('canteen'),'count':4})
        self.assertEqual(before,self.read())

    def test_invalid_counts_and_unknown_target_preserve_save(self):
        self.free_all();before=self.read()
        for n in [0,-1,True,1.5,'2']:
            with self.assertRaises(ValidationError):self.cmd('work_assign',{'building_id':self.building('field'),'count':n})
            self.assertEqual(before,self.read())
        with self.assertRaises(NotFoundError):self.cmd('work_assign',{'building_id':'unknown','count':1})
        self.assertEqual(before,self.read())

    def test_cancel_running_job_holds_people_until_completion(self):
        self.free_all();bid=self.building('canteen');self.cmd('work_assign',{'building_id':bid,'count':2});self.cmd('production_start',{'building_id':bid,'recipe_id':'sect_food'})
        job=self.read().domains['production']['jobs'][bid];self.cmd('work_unassign',{'building_id':bid});v=self.view()
        self.assertEqual(v['buildings'][bid]['assigned_count'],0);self.assertEqual(v['buildings'][bid]['occupied_count'],2)
        self.assertEqual(sum(g['available_count'] for g in v['disciples']['groups']),6)
        self.clock.advance(job['due_ms']-job['started_ms']);self.drain()
        self.assertEqual(self.view()['buildings'][bid]['occupied_count'],0)
        self.assertEqual(sum(g['available_count'] for g in self.view()['disciples']['groups']),8)

    def test_fault_rolls_back_whole_shared_assignment(self):
        self.free_all();before=self.read()
        with patch('src.core.save.sqlite.SQLiteSave.commit',side_effect=RuntimeError('fixture failure')):
            with self.assertRaises(RuntimeError):self.cmd('work_assign',{'building_id':self.building('field'),'count':5})
        self.assertEqual(before,self.read())

    def test_generic_recruitment_keeps_count_and_replay(self):
        before=sum(g['count'] for g in self.view()['disciples']['groups']);q=self.q('sect_recruit',{'count':1});receipt=self.execute(q);started=self.read()
        self.assertEqual(receipt,self.execute(q));self.assertEqual(started,self.read())
        self.clock.advance(100000);self.drain()
        self.assertEqual(sum(g['count'] for g in self.view()['disciples']['groups']),before+1)
        self.assertTrue(all(g['name']=='宗门弟子' for g in self.view()['disciples']['groups']))

    def test_legacy_command_and_pause_compatibility(self):
        self.free_all();gid=next(iter(self.read().domains['disciples']['groups']));bid=self.building('field')
        self.cmd('work_assign',{'worker_id':gid,'building_id':bid,'count':1});self.cmd('work_unassign',{'worker_id':gid,'building_id':bid})
        self.cmd('world_pause',{});before=self.read()
        with self.assertRaises(ValidationError):self.cmd('work_assign',{'building_id':bid,'count':1})
        self.assertEqual(before,self.read())

    def test_http_intent_shape_reaches_shared_assignment(self):
        from src.core.save.sqlite import SQLiteSave
        self.free_all();s=self.read();q=self.q('work_assign',{'building_id':self.building('field'),'count':3})
        body={'protocol_version':1,'save_id':self.sid,'generation':s.generation,'expected_revision':s.revision,'request_id':q.request_id,'command':{'name':'work_assign','version':1,'payload':dict(q.payload)}}
        with SQLiteSave(self.db,allowed_root=self.root) as store:
            receipt=self.app(store).act(self.sid,body)
        self.assertEqual(receipt.committed_revision,s.revision+1)
        self.assertEqual(self.view()['buildings'][q.payload['building_id']]['assigned_count'],3)

    def test_add_people_to_held_target_counts_new_people_once(self):
        self.free_all();bid=self.building('canteen');self.cmd('work_assign',{'building_id':bid,'count':1});self.cmd('production_start',{'building_id':bid,'recipe_id':'sect_food'})
        self.cmd('work_unassign',{'building_id':bid});self.cmd('work_assign',{'building_id':bid,'count':1})
        v=self.view();self.assertEqual(v['buildings'][bid]['occupied_count'],2)
        self.assertEqual(sum(g['available_count'] for g in v['disciples']['groups']),6)

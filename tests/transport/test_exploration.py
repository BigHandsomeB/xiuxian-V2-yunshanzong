"""Authenticated shipping HTTP command seam; temporary SQLite only."""
from uuid import uuid4
import unittest
from src.data.content_loader import load_current
from tests.transport import test_ecology as http
from tests.systems import test_exploration as domain


class ExplorationHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.registry=load_current()
    setUp=http.EcologyHTTPTests.setUp
    for name in ('read','request','execute','command','settle','fixture','body','post'):
        locals()[name]=getattr(http.EcologyHTTPTests,name)
    view=domain.ExplorationTests.view
    start=domain.ExplorationTests.start
    finish=domain.ExplorationTests.finish

    def test_get_pure_start_replay_and_stale_revision(self):
        before=self.read();self.assertEqual(self.client.get('/api/view').status_code,200);self.assertEqual(before,self.read())
        body=self.body('exploration_start',{'region_id':'thorn_outskirts'})
        self.assertEqual(self.post(body).status_code,200);after=self.read()
        self.assertEqual(self.post(body).status_code,200);self.assertEqual(after,self.read())
        body['request_id']=str(uuid4());self.assertEqual(self.post(body).status_code,409);self.assertEqual(after,self.read())

    def test_ready_choice_replay_double_claim_and_forged_rewards(self):
        self.start();a=self.finish()
        body=self.body('exploration_choose',{'journey_id':a['id'],'choice_id':'leave','rewards':{'coins':999999}})
        before=self.read();self.assertEqual(self.post(body).status_code,422);self.assertEqual(before,self.read())
        body=self.body('exploration_choose',{'journey_id':a['id'],'choice_id':'leave'})
        self.assertEqual(self.post(body).status_code,200);after=self.read()
        self.assertEqual(self.post(body).status_code,200);self.assertEqual(after,self.read())
        self.assertEqual(self.post(self.body('exploration_choose',body['command']['payload'])).status_code,422)
        self.assertEqual(after,self.read())
        projected=self.client.get('/api/view').json['view']['exploration']
        self.assertIsNone(projected['active']);self.assertEqual(len(projected['history']),1)

    def test_csrf_and_paused_start_rejected(self):
        body=self.body('exploration_start',{'region_id':'thorn_outskirts'});before=self.read()
        self.assertEqual(self.client.post('/api/command',json=body).status_code,403);self.assertEqual(before,self.read())
        self.command('world_pause',{});before=self.read()
        self.assertEqual(self.post(self.body('exploration_start',{'region_id':'thorn_outskirts'})).status_code,422)
        self.assertEqual(before,self.read())

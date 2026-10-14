"""Authenticated shipping HTTP commands over disposable saves."""
import unittest
from uuid import uuid4
from tests.transport import test_ecology as http_fixtures
from tests.systems import test_sect_activities as activity_fixtures

class ActivityHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):http_fixtures.EcologyHTTPTests.setUpClass.__func__(cls)
    setUp=http_fixtures.EcologyHTTPTests.setUp
    for name in ('read','bid','request','execute','command','assign','settle','fixture','body','post'):
        locals()[name]=getattr(http_fixtures.EcologyHTTPTests,name)
    seed=activity_fixtures.ActivityTests.seed
    fill_order=activity_fixtures.ActivityTests.fill_order
    def test_commission_replay_and_stale_revision(self):
        before=self.read();response=self.client.get('/api/view');self.assertEqual(response.status_code,200);self.assertEqual(self.read(),before)
        row=response.json['view']['sect_activities']['orders'][0];self.fill_order(row)
        body=self.body('sect_commission_claim',{k:row[k] for k in ('order_id','market_day','quote_id')})
        r=self.post(body);self.assertEqual(r.status_code,200);self.assertEqual(self.client.get('/api/view').json['view']['sect_activities']['contribution'],20)
        after=self.read();self.assertEqual(self.post(body).status_code,200);self.assertEqual(self.read(),after)
        body['request_id']=str(uuid4());self.assertEqual(self.post(body).status_code,409);self.assertEqual(self.read(),after)
    def test_chest_explicit_choice_replays_and_double_open_rejected(self):
        self.seed(extra={'issued':['thorn_path'],'chests':{'thorn_path':{'tier':1,'battle_id':'test-boss'}}})
        before=self.read();bad=self.post(self.body('boss_chest_open',{'chest_id':'thorn_path','choice':'invalid'}));self.assertEqual(bad.status_code,422);self.assertEqual(self.read(),before)
        body=self.body('boss_chest_open',{'chest_id':'thorn_path','choice':'management'});self.assertEqual(self.post(body).status_code,200)
        after=self.read();self.assertEqual(self.post(body).status_code,200);self.assertEqual(self.read(),after)
        self.assertEqual(self.post(self.body('boss_chest_open',{'chest_id':'thorn_path','choice':'equipment'})).status_code,422);self.assertEqual(self.read(),after)
    def test_no_csrf_and_insufficient_contribution_cannot_grant(self):
        before=self.read();body=self.body('sect_contribution_exchange',{'exchange_id':'manual_page'})
        self.assertEqual(self.client.post('/api/command',json=body).status_code,403)
        self.assertEqual(self.post(body).status_code,422);self.assertEqual(self.read(),before)

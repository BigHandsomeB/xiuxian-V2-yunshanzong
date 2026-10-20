"""Authenticated trial command round-trip against isolated SQLite."""
import unittest
from uuid import uuid4
from src.data.content_loader import load_current
from tests.transport import test_ecology as http

class AttributeTrialHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.registry=load_current()
    setUp=http.EcologyHTTPTests.setUp
    for name in ('read','request','execute','command','settle','fixture','body','post'):
        locals()[name]=getattr(http.EcologyHTTPTests,name)
    def test_start_stop_pure_get_replay_and_stale(self):
        before=self.read();v=self.client.get('/api/view');self.assertEqual(v.status_code,200);self.assertEqual(len(v.json['view']['cultivation']['attribute_trials']['rows']),3);self.assertEqual(before,self.read())
        q=self.body('attribute_trial_start',{'stat':'attack_milli','wave':1});self.assertEqual(self.post(q).status_code,200);after=self.read();self.assertEqual(self.post(q).status_code,200);self.assertEqual(after,self.read());q['request_id']=str(uuid4());self.assertEqual(self.post(q).status_code,409)
        self.assertEqual(self.post(self.body('attribute_trial_stop',{})).status_code,200)
    def test_forged_rewards_invalid_fields_and_csrf(self):
        for payload in ({'stat':'attack_milli','wave':1,'xp':9999},{'stat':'speed_bps','wave':1},{'stat':'attack_milli','wave':2},{'stat':'attack_milli','wave':True}):
            before=self.read();self.assertEqual(self.post(self.body('attribute_trial_start',payload)).status_code,422);self.assertEqual(before,self.read())
        self.assertEqual(self.client.post('/api/command',json=self.body('attribute_trial_start',{'stat':'attack_milli','wave':1})).status_code,403)

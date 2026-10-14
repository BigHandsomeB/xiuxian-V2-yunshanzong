"""Authenticated report transport uses only isolated SQLite saves."""
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4
from src.application.sect_management import ManagementApplication
from src.core.save.sqlite import SQLiteSave,V2_ROOT
from src.transport.danding import create_app
from tests.systems import test_settlement_batch as fixtures


class OfflineReportTransportTests(unittest.TestCase):
    def setUp(self):
        fixture=fixtures.SettlementBatchTests();fixture.setUp();self.addCleanup(fixture.doCleanups);self.f=fixture
        self.tmp=tempfile.TemporaryDirectory(dir=V2_ROOT/'tests');self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.path=self.root/'http.sqlite3';self.sid=fixture.state.save_id
        with SQLiteSave.initialize(self.path,allowed_root=self.root) as store:
            ManagementApplication(store,fixture.registry,fixture.clock).create(fixture.state)
        fixture.clock.advance(120000)
        self.web=create_app(self.application,self.sid,lambda v:{},lambda *a:None,'isolated-report-token-00000000000',secure=False,cookie_path='/')
        self.client=self.web.test_client()
        with self.client.session_transaction() as session:session.update(authenticated=True,csrf='report-fixture')

    @contextmanager
    def application(self):
        with SQLiteSave(self.path,allowed_root=self.root) as store:
            app=ManagementApplication(store,self.f.registry,self.f.clock);app.settlement_max_events=2;yield app

    def body(self):
        view=self.client.get('/api/view').get_json()['view']
        return {'protocol_version':1,'save_id':self.sid,'request_id':str(uuid4()),'generation':view['generation'],'expected_revision':view['revision'],'continuation':view['time']['continuation']}

    def post(self,path,body):return self.client.post('/api/'+path,json=body,headers={'X-CSRF-Token':'report-fixture'})

    def drain(self):
        body=self.body();seen=[]
        for _ in range(500):
            response=self.post('settle',body);self.assertEqual(response.status_code,200);payload=response.get_json();seen.append(payload)
            self.assertEqual(self.post('settle',body).get_json(),payload)
            if not payload['time']['pending']:return payload,seen
            body={**body,'request_id':str(uuid4()),'expected_revision':payload['revision'],'continuation':payload['time']['continuation']}
        self.fail('fixture did not finish')

    def test_completion_response_and_persistent_view_same_report_no_intermediate_report(self):
        final,seen=self.drain();self.assertGreater(len(seen),2)
        self.assertTrue(all(p['receipt']['result']['offline_report'] is None for p in seen[:-1]))
        report=final['receipt']['result']['offline_report'];self.assertIsNotNone(report)
        view=self.client.get('/api/view').get_json()['view'];self.assertEqual(view['offline_reports'][0],report)
        self.assertEqual(seen[0]['time']['settlement_duration_ms'],120000)
        self.assertEqual(seen[0]['time']['offline_duration_ms'],120000)
        self.assertEqual(seen[0]['time']['from_sim_ms'],0)
        self.assertEqual(view['offline_report_names']['dungeons']['thorn_path'],'荆棘古道')
        self.assertNotIn('view',seen[0]);self.assertNotIn('baseline',report)

    def test_ack_authorized_idempotent_csrf_and_refresh(self):
        final,_=self.drain();view=self.client.get('/api/view').get_json()['view'];rid=final['receipt']['result']['offline_report']['report_id']
        body={k:v for k,v in self.body().items() if k!='continuation'};body['command']={'name':'offline_report_ack','version':1,'payload':{'report_id':rid}}
        self.assertEqual(self.client.post('/api/command',json=body).status_code,403)
        first=self.post('command',body);self.assertEqual(first.status_code,200);self.assertEqual(self.post('command',body).get_json(),first.get_json())
        after=self.client.get('/api/view').get_json()['view'];self.assertEqual(after['offline_reports'],[])
        self.assertEqual(after['inventory'],view['inventory']);self.assertEqual(after['time'],view['time'])
        self.assertEqual(self.client.post('/api/command',data='x'*4097,content_type='application/json',headers={'X-CSRF-Token':'report-fixture'}).status_code,413)

    def test_pending_view_carries_server_duration_and_ack_cannot_change_cursor(self):
        body=self.body();payload=self.post('settle',body).get_json()
        view=self.client.get('/api/view').get_json()['view'];self.assertEqual(view['time']['offline_duration_ms'],120000)
        report_id=payload['time']['continuation']['save_id']+':1:r:0'
        command={'protocol_version':1,'save_id':self.sid,'generation':view['generation'],'expected_revision':view['revision'],'request_id':str(uuid4()),'command':{'name':'offline_report_ack','version':1,'payload':{'report_id':report_id}}}
        self.assertEqual(self.post('command',command).status_code,409)
        self.assertEqual(self.client.get('/api/view').get_json()['view'],view)

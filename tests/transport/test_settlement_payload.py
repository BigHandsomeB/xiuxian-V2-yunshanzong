"""Wire bounds/compression are projections; committed history stays complete."""
import gzip,json
from dataclasses import replace
from uuid import uuid4
from tests.transport.test_settle_progress import SettleProgressHTTPTests
from src.core.save.sqlite import SQLiteSave
from src.application.sect_management import ManagementApplication
from src.core.state.envelope import thaw_json
from src.application import offline_reports as reports

class SettlementPayloadTests(SettleProgressHTTPTests):
    def test_gzip_negotiation_and_plain_clients(self):
        plain=self.client.get('/api/view');compressed=self.client.get('/api/view',headers={'Accept-Encoding':'gzip'})
        self.assertEqual(plain.status_code,200);self.assertEqual(compressed.headers['Content-Encoding'],'gzip')
        self.assertEqual(json.loads(gzip.decompress(compressed.data)),plain.get_json())
        self.assertLess(len(compressed.data),len(plain.data)/3)
        self.assertEqual(compressed.headers['Cache-Control'],'no-store');self.assertIn('Accept-Encoding',compressed.headers['Vary'])
        refused=self.client.get('/api/view',headers={'Accept-Encoding':'gzip;q=0'})
        self.assertNotIn('Content-Encoding',refused.headers)

    def test_receipt_ids_are_on_demand_and_reading_does_not_advance(self):
        p=self.post(self.body).get_json();self.assertEqual(p['receipt']['result']['processed_events'],[])
        detail=self.client.get('/api/settlement/'+self.body['request_id']).get_json()
        self.assertEqual(len(detail['result']['processed_events']),p['processed_count'])
        with self.application() as game:before=game.query(self.state.save_id)
        self.client.get('/api/history?kind=equipment&limit=10');self.client.get('/api/settlement/'+self.body['request_id'])
        with self.application() as game:self.assertEqual(game.query(self.state.save_id),before)
        self.assertEqual(self.client.get('/api/history?kind=equipment&limit=101').status_code,422)
        self.assertEqual(self.client.get('/api/history?kind=unknown').status_code,422)
        self.assertEqual(self.client.get('/api/settlement/'+str(uuid4())).status_code,422)
        with self.client.session_transaction() as session:session['authenticated']=False
        self.assertEqual(self.client.get('/api/history').status_code,401)

    def test_large_report_view_is_bounded_full_report_is_retained(self):
        s,r=self.fixture.app.engine.advance(self.state,max_events=4096,now_ms=121000)
        data=thaw_json(s.domains[reports.DOMAIN]);report=data['unread'][0]
        n=s.identity['instance_counter'];ids=[f'{s.save_id}:1:i:{n+i+1}' for i in range(503)]
        report['equipment']={'added_ids':ids,'removed_ids':ids,'sold_ids':ids,'salvaged_ids':[], 'quality_counts':{'white':{'gained':503,'removed':503,'sold':503,'salvaged':0}}}
        s=replace(s,identity={**s.identity,'instance_counter':n+503},domains={**s.domains,reports.DOMAIN:data})
        # A separate isolated HTTP database avoids administrative replacement of a live row.
        other=self.root/'large.sqlite3'
        with SQLiteSave.initialize(other,allowed_root=self.root) as store:ManagementApplication(store,self.fixture.registry,self.fixture.clock).create(s)
        self.path=other
        view=self.client.get('/api/view').get_json()['view'];small=view['offline_reports'][0]
        self.assertEqual(len(small['equipment']['added_ids']),50);self.assertTrue(small['equipment']['ids_truncated'])
        full=self.client.get('/api/offline-report/'+report['report_id']).get_json()
        self.assertEqual(full,report);self.assertEqual(len(full['equipment']['added_ids']),503)
        with self.application() as game:self.assertEqual(thaw_json(game.query(s.save_id).domains[reports.DOMAIN]),data)

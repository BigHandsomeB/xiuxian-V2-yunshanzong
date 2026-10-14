"""Battle report observations share reward transactions and survive request replay."""
import tempfile,unittest
from pathlib import Path
from dataclasses import replace
from uuid import uuid4
from src.core.save.sqlite import SQLiteSave,V2_ROOT
from src.core.state.envelope import thaw_json
from src.core.time.model import Continuation
from src.application.settlement import SettlementRequest
from src.application.memory import Command
from src.application.sect_management import ManagementApplication
from src.application import offline_reports as reports
from tests.systems import test_settlement_batch as fixtures

class OfflineBattleReportTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.SettlementBatchTests();self.f.setUp();self.addCleanup(self.f.doCleanups)

    def drain(self,s,target,compressed=False):
        self.f.app.engine.result_path=compressed
        for _ in range(1000):
            s,r=self.f.app.engine.advance(s,max_events=8,now_ms=None if s.time['pending'] else target,continuation=Continuation.for_state(s) if s.time['pending'] else None)
            if not s.time['pending']:return s
        self.fail('did not complete')

    def test_summary_original_compressed_and_only_latest(self):
        before=self.f.state;a=self.drain(before,121000);b=self.drain(before,121000,True)
        from tests.systems.test_compressed_settlement import digest
        self.assertEqual(digest(a),digest(b))
        self.assertEqual(thaw_json(reports.latest_battle(a)),thaw_json(reports.latest_battle(b)))
        row=reports.latest_battle(b);generic=b.domains[reports.DOMAIN]['unread'][0]
        self.assertEqual(row['battles'],generic['combat']['wins']+generic['combat']['losses']);self.assertEqual(row['wins'],generic['combat']['wins'])
        self.assertEqual(row['coins'],b.domains['inventory']['holdings'].get('coins',0)-before.domains['inventory']['holdings'].get('coins',0))
        self.assertEqual(row['equipment_count'],sum(r['gained'] for r in generic['equipment']['quality_counts'].values()))
        end=self.drain(b,241000,True);self.assertNotEqual(reports.latest_battle(end)['report_id'],row['report_id'])
        self.assertEqual(end.domains[reports.DOMAIN]['latest_battle_report']['report_id'],reports.latest_battle(end)['report_id'])

    def test_old_save_and_old_active_report_have_no_invented_battle_report(self):
        self.assertIsNone(reports.latest_battle(self.f.state));self.assertNotIn(reports.DOMAIN,self.f.state.domains)
        s,r=self.f.app.engine.advance(self.f.state,max_events=1,now_ms=121000)
        data=thaw_json(s.domains[reports.DOMAIN]);data.pop('latest_battle_report',None);data['active'].pop('battle_summary')
        old=replace(s,domains={**s.domains,reports.DOMAIN:data});reports.validate(old)
        end=self.drain(old,999999999,True)
        self.assertIsNone(reports.latest_battle(end));self.assertEqual(end.time['sim_time_ms'],120000)

    def test_reward_replay_rollback_and_pause_report(self):
        self.f.clock.advance(120000)
        with tempfile.TemporaryDirectory(dir=V2_ROOT/'.tmp') as directory:
            root=Path(directory);path=root/'war.sqlite3'
            with SQLiteSave.initialize(path,allowed_root=root) as store:
                app=ManagementApplication(store,self.f.registry,self.f.clock);app.create(self.f.state);s=app.query(self.f.state.save_id)
                q=SettlementRequest(s.save_id,s.generation,s.revision,str(uuid4()),4096)
                receipt=app.settle(q);after=app.query(s.save_id)
                self.assertEqual(app.settle(q),receipt);self.assertEqual(app.query(s.save_id),after)
                row=reports.latest_battle(after);self.assertGreater(row['wins'],0)
                pause=Command(s.save_id,after.generation,after.revision,str(uuid4()),'world_pause',{})
                app.execute(pause);paused=app.query(s.save_id)
                self.assertTrue(paused.time['world_paused']);self.assertEqual(reports.latest_battle(paused)['stop_reason'],'WORLD_PAUSED')
                self.assertEqual(reports.latest_battle(paused)['stop_sim_ms'],paused.time['sim_time_ms'])
                self.assertEqual(paused.domains['inventory'],after.domains['inventory'])
                self.assertEqual(app.execute(pause),app.execute(pause));self.assertEqual(app.query(s.save_id),paused)

    def test_overflow_is_counted_separately_from_materials_kept(self):
        from src.data.economy.sect_rules import settings
        stock=thaw_json(self.f.state.domains['inventory']);stock['holdings'].update({k:n for k,n in settings(self.f.registry)['material_caps'].items() if k.startswith('thorn_')})
        start=replace(self.f.state,domains={**self.f.state.domains,'inventory':stock})
        end=self.drain(start,121000,True);row=reports.latest_battle(end)
        self.assertGreater(row['overflow_coins'],0);self.assertTrue(row['converted_materials'])
        self.assertLessEqual(row['overflow_coins'],row['coins'])

    def test_defeat_and_full_storage_stop_time_is_persisted(self):
        from tests.systems import test_compressed_settlement as gates
        gate=gates.CompressionGateTests()
        for mode,reason in [('defeat','DEFEATED'),('full','STORAGE_FULL')]:
            start=gate.scenario(self.f,mode);end=self.drain(start,121000,True)
            self.assertEqual(end.domains['dungeon']['auto']['reason'],reason)
            stop=end.domains['dungeon']['auto']['stop_sim_ms'];self.assertGreater(stop,0);self.assertLess(stop,end.time['sim_time_ms'])
            self.assertEqual(reports.latest_battle(end)['stop_reason'],reason);self.assertEqual(reports.latest_battle(end)['stop_sim_ms'],stop)

    def test_invalid_summary_is_rejected(self):
        end=self.drain(self.f.state,121000,True);data=thaw_json(end.domains[reports.DOMAIN]);data['latest_battle_report']['wins']+=10000
        from src.core.validation import ValidationError
        with self.assertRaises(ValidationError):reports.validate(replace(end,domains={**end.domains,reports.DOMAIN:data}))

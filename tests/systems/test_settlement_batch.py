"""Same fixed window and event stream across legacy, timed and resumed batches."""
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
from src.application.danding import initial_slice
from src.application.sect_management import ManagementApplication
from src.application.economy_settlement import EconomySettlement
from src.application.settlement import SettlementRequest
from src.core.save.sqlite import SQLiteSave, V2_ROOT
from src.core.state.envelope import thaw_json
from src.core.time.model import Continuation
from src.core.validation import ConflictError
from src.data.dungeons.definitions import load_dungeons
from src.systems.dungeons import progress
from tests.fixtures.time import ManualClock
from tests.fixtures.settlement_legacy import legacy_advance


class SettlementBatchTests(unittest.TestCase):
    def setUp(self):
        self.registry = load_dungeons(management=True)
        self.clock = ManualClock(1000)
        self.app = ManagementApplication(None, self.registry, self.clock)
        self.app.engine.result_path=False  # Original event-stream contract; compression has its own parity gate.
        s = initial_slice(self.registry, last_settled_at_ms=1000)
        seed = tempfile.TemporaryDirectory(dir=V2_ROOT/'tests'); self.addCleanup(seed.cleanup)
        seed_root = Path(seed.name)
        with SQLiteSave.initialize(seed_root/'seed.sqlite3', allowed_root=seed_root) as store:
            game = ManagementApplication(store, self.registry, self.clock); game.create(s); s = game.query(s.save_id)
        dungeon = thaw_json(s.domains['dungeon']); dungeon['cleared_floor'] = 4
        dungeon = progress.set_auto(dungeon, self.registry, True, 'farm', 2, 3)
        self.state = self.app.engine.wake(replace(s, domains={**s.domains, 'dungeon': dungeon}))

    def drain(self, start, target, *, legacy=False, batch=4096):
        s = start; events = []; rounds = 0
        while True:
            continuation = Continuation.for_state(s) if s.time['pending'] else None
            kwargs = dict(max_events=batch, continuation=continuation, now_ms=target if continuation is None else None)
            if legacy:
                with patch.object(EconomySettlement, 'advance', legacy_advance):
                    s, result = self.app.engine.advance(s, **kwargs)
            else:
                s, result = self.app.engine.advance(s, **kwargs)
            events.extend(result.processed_events); rounds += 1
            if result.status == 'COMPLETE': return s, events, rounds
            self.assertLess(rounds, 10000)

    def assert_same(self, left, right):
        a = left.to_dict(); b = right.to_dict()
        a.pop('revision'); b.pop('revision')
        # Reporting is observational; compare every original gameplay field.
        a['domains'].pop('offline_reports',None); b['domains'].pop('offline_reports',None)
        self.assertEqual(a, b)  # All domains, time, identity, IDs, loot/stats and metadata.

    def test_legacy_and_timed_batches_have_identical_world_and_event_order(self):
        for elapsed in (0, 20000, 120000):
            with self.subTest(elapsed=elapsed):
                before, old_events, _ = self.drain(self.state, 1000 + elapsed, legacy=True)
                after, new_events, _ = self.drain(self.state, 1000 + elapsed)
                self.assert_same(before, after); self.assertEqual(old_events, new_events)

    def test_same_due_events_and_resume_keep_fixed_target_and_sequence(self):
        single, single_events, _ = self.drain(self.state, 81000, batch=1)
        batched, batch_events, _ = self.drain(self.state, 81000, batch=4096)
        self.assert_same(single, batched); self.assertEqual(single_events, batch_events)
        partial, result = self.app.engine.advance(self.state, max_events=1, now_ms=81000)
        continuation = Continuation.for_state(partial)
        self.clock.advance(1000000)
        resumed, result = self.app.engine.advance(partial, max_events=4096, continuation=continuation)
        self.assertEqual(result.target_sim_ms, 80000)
        self.assert_same(single, resumed)
        with self.assertRaises(ConflictError):
            self.app.engine.advance(replace(partial, revision=partial.revision+1), max_events=32, continuation=continuation)

    def test_production_resource_delivery_and_combat_match_legacy(self):
        from src.systems.economy import policy
        s=self.state
        for kind,recipe in (('garden','grain'),('forest','wood')):
            building=next(k for k,row in s.domains['sect']['buildings'].items() if row['definition_id']==kind)
            s=self.app.start_candidate(s,building,recipe)
            automation=policy.set_production(s.domains['automation'],self.registry,building,{'enabled':True,'recipe_id':recipe,'target':100,'reserves':{},'max_consumption':100})
            s=replace(s,domains={**s.domains,'automation':automation})
        s=self.app.engine.wake(s)
        before,old_events,_=self.drain(s,91000,legacy=True)
        after,new_events,_=self.drain(s,91000)
        self.assert_same(before,after);self.assertEqual(old_events,new_events)
        self.assertGreater(after.domains['inventory']['holdings'].get('grain',0),s.domains['inventory']['holdings'].get('grain',0))
        self.assertGreater(after.domains['inventory']['holdings'].get('wood',0),s.domains['inventory']['holdings'].get('wood',0))

    def test_time_budget_is_configurable_and_checked_between_events(self):
        for target, deadline in ((51000, 1.6), (101000, 4.1)):
            with self.subTest(target=target), patch('src.application.economy_settlement.monotonic', side_effect=[0, .01, .02, deadline]):
                s, result = self.app.engine.advance(self.state, max_events=4096, now_ms=target)
            self.assertEqual(len(result.processed_events), 3)
            self.assertIsNotNone(s.time['pending'])

    def test_batch_commit_replay_cas_restart_and_failure_are_atomic(self):
        with tempfile.TemporaryDirectory(dir=V2_ROOT/'tests') as directory:
            root = Path(directory); path = root/'batch.sqlite3'
            with SQLiteSave.initialize(path, allowed_root=root) as store:
                game = ManagementApplication(store, self.registry, self.clock); game.create(self.state)
                self.clock.advance(80000)
                q = SettlementRequest(self.state.save_id, self.state.generation, self.state.revision, str(uuid4()), 4096)
                commits = []; commit = store.commit
                def counted(*args): commits.append(args); return commit(*args)
                with patch.object(store, 'commit', counted): receipt = game.settle(q)
                after = game.query(self.state.save_id)
                self.assertGreater(len(receipt.result.processed_events), 1); self.assertEqual(len(commits), 1)
                self.assertEqual(game.settle(q), receipt); self.assertEqual(game.query(self.state.save_id), after)
                with self.assertRaises(ConflictError):
                    game.settle(replace(q, request_id=str(uuid4())))
                next_q = SettlementRequest(after.save_id, after.generation, after.revision, str(uuid4()), 4096, Continuation.for_state(after) if after.time['pending'] else None)
                self.clock.advance(80000)
                with patch.object(store, '_insert_receipt', side_effect=RuntimeError('fixture failure')):
                    with self.assertRaises(RuntimeError): game.settle(next_q)
                self.assertEqual(game.query(after.save_id), after)
                self.assertIsNone(store.receipt(after.save_id, after.generation, next_q.request_id))
            with SQLiteSave(path, allowed_root=root) as store:
                game = ManagementApplication(store, self.registry, self.clock)
                self.assertEqual(game.settle(q), receipt); self.assertEqual(game.query(after.save_id), after)

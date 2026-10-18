"""Scoped display construction is equivalent and never changes validated save facts."""
import tempfile,unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch
from tools.playable.game import PROJECT,game_factory
from src.application.danding import initial_slice
from src.core.save.sqlite import SQLiteSave
from src.core.state.envelope import thaw_json
from src.core.state import draft
from src.data.dungeons.definitions import load_dungeons
from tests.fixtures.time import ManualClock


class ProjectionScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.registry=load_dungeons(management=True,cold_jade=True,ecology=True)
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=PROJECT/'.tmp');self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name);self.clock=ManualClock();state=initial_slice(self.registry,last_settled_at_ms=self.clock.now_ms());self.sid=state.save_id
        path=root/'game.sqlite3'
        with SQLiteSave.initialize(path,allowed_root=root):pass
        self.factory=game_factory(path,root,self.clock,registry=self.registry)
        with self.factory() as game:game.create(state)
    def test_projection_matches_unscoped_implementation_and_is_immutable(self):
        with self.factory() as game:
            before=game.query(self.sid);view=game.view(self.sid)
            with patch('src.core.state.draft.batch_scope',nullcontext):baseline=game.view(self.sid)
            self.assertEqual(view,baseline);self.assertEqual(game.query(self.sid),before)
            self.assertFalse(draft.enabled())
            with self.assertRaises(TypeError):view['revision']=999
            detached=thaw_json(view);detached['inventory'].clear()
            self.assertTrue(game.view(self.sid)['inventory'])
    def test_failed_projection_restores_scope_without_writing(self):
        with self.factory() as game:
            before=game.query(self.sid)
            with patch.object(game,'project_full_view',side_effect=RuntimeError('projection failed')):
                with self.assertRaises(RuntimeError):game.view(self.sid)
            self.assertFalse(draft.enabled());self.assertEqual(game.query(self.sid),before)
    def test_pending_projection_keeps_serialization_outside_mutable_scope(self):
        from types import SimpleNamespace
        from src.core.state.envelope import freeze_json
        with self.factory() as game:
            def display(state):
                self.assertFalse(draft.enabled())
                return freeze_json({'revision':1})
            with patch.object(game,'query',return_value=SimpleNamespace(time={'pending':{'target_sim_ms':1000}})),patch.object(game,'project_full_view',side_effect=display):
                self.assertEqual(game.view(self.sid)['revision'],1)
            self.assertFalse(draft.enabled())
    def test_save_validation_precedes_projection(self):
        from src.core.save.codec import CorruptSaveError
        with self.factory() as game,patch.object(game,'query',side_effect=CorruptSaveError('invalid current snapshot')),patch.object(game,'project_full_view') as projection:
            with self.assertRaises(CorruptSaveError):game.view(self.sid)
            projection.assert_not_called();self.assertFalse(draft.enabled())


class ProjectionCheckTests(unittest.TestCase):
    def test_only_immutable_inputs_in_same_scope_reuse_successful_checks(self):
        from types import SimpleNamespace
        from src.core.state.envelope import freeze_json
        from src.core.state.projection import projection_checks,checked_partition
        registry=SimpleNamespace(is_sealed=True);calls=[]
        @checked_partition
        def validate(value,registry,**options):
            calls.append((value,registry,options))
            if value.get('bad'):raise ValueError('invalid partition')
            return value
        owned=freeze_json({'n':1});mutable={'n':1}
        with projection_checks():
            validate(owned,registry);validate(owned,registry);self.assertEqual(len(calls),1)
            validate(owned,registry,save_id='other');self.assertEqual(len(calls),2)
            validate(mutable,registry);mutable['bad']=True
            with self.assertRaises(ValueError):validate(mutable,registry)
            bad=freeze_json({'bad':True})
            for i in range(2):
                with self.assertRaises(ValueError):validate(bad,registry)
            self.assertEqual(len(calls),6)
        validate(owned,registry);self.assertEqual(len(calls),7)
        with projection_checks():validate(owned,registry)
        self.assertEqual(len(calls),8)
        registry.is_sealed=False
        with projection_checks():validate(owned,registry);validate(owned,registry)
        self.assertEqual(len(calls),10)

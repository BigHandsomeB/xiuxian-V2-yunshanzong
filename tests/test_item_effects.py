"""Controlled effects: real old rules, isolated SQLite and unchanged command receipts."""
from contextlib import contextmanager
from dataclasses import replace, FrozenInstanceError
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import MappingProxyType
import unittest
from unittest.mock import patch
from uuid import uuid4

from src.application.cultivation import CultivationApplication, partition
from src.application.danding import initial_slice
from src.application.ecology import EcologyApplication
from src.application.memory import Command
from src.core.save.sqlite import SQLiteSave, V2_ROOT
from src.core.save.codec import StoredReceipt
from src.core.state.envelope import freeze_json, thaw_json
from src.core.validation import ConflictError, ValidationError
from src.data import content_loader
from src.data.cultivation.definitions import load_cultivation
from src.data.dungeons.definitions import load_dungeons
from src.data.economy.sect_rules import settings
from src.data.item_effects import bindings_for, validate_bindings
from src.data.registry import DefinitionKey, DefinitionRegistry
from src.systems.cultivation import growth, leveling, item_effects
from tests.fixtures.time import ManualClock


PROFILES = ({}, {'legacy': True}, {'balance_legacy': True}, {'expansion_legacy': True},
            {'management': True}, {'cold_jade': True},
            {'management': True, 'cold_jade': True},
            {'management': True, 'cold_jade': True, 'ecology': True})


def legacy_foundation_registry():
    source = load_dungeons()
    registry = DefinitionRegistry(schema_version=source.schema_version,
                                  content_version=source.content_version)
    for definition in source._definitions.values():
        if definition.key == DefinitionKey('sect_rules', 'shipping'):
            values = thaw_json(definition.values)
            values.pop('leveling')
            definition = replace(definition, values=freeze_json(values))
        registry.register(definition)
    registry.seal()
    return registry


def original(command, key, p, registry, save, stock, active=False, count=1, world_ms=0):
    if command == 'cultivation_train':
        return growth.train(p, registry, save, stock, active, count=count, world_ms=world_ms)
    return growth.use_foundation_pill(p, registry, save, stock, key, active,
                                     count=count, world_ms=world_ms)


class ItemEffectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.current = load_dungeons(management=True, cold_jade=True, ecology=True)

    def row(self, **changes):
        return {'command':'cultivation_use_pill', 'item_id':'ju_qi_pill',
                'effect_type':'cultivation_pill', 'parameters':{}, **changes}

    def test_strict_schema_unknown_effects_parameters_commands_and_references(self):
        rows = [self.row(effect_type=x) for x in ('eval', 'os.system', '', 1, None)]
        rows += [self.row(parameters=x) for x in ({'gain': 999}, {'handler': 'os.system'}, [], None)]
        rows += [self.row(command=x) for x in ('item_use', 'cultivation_breakthrough', None)]
        rows += [self.row(item_id=x) for x in ('missing', '../pill', True, ['pill'])]
        rows += [{**self.row(), 'extra': 1}, {k:v for k,v in self.row().items() if k != 'parameters'},
                 self.row(command='cultivation_train')]
        for row in rows:
            with self.subTest(row=row), self.assertRaises(ValidationError):
                validate_bindings(self.current, [row])

    def test_duplicate_bindings_and_unsealed_registry_rejected(self):
        with self.assertRaisesRegex(ValidationError, 'duplicate'):
            validate_bindings(self.current, [self.row(), self.row()])
        registry = DefinitionRegistry(schema_version=1, content_version='test')
        with self.assertRaisesRegex(ValidationError, 'sealed'):
            validate_bindings(registry, [])

    def test_binding_table_and_parameters_are_immutable(self):
        table = bindings_for(self.current)
        binding = table[('cultivation_use_pill', 'ju_qi_pill')]
        with self.assertRaises(TypeError):table[('x', 'y')] = binding
        with self.assertRaises(TypeError):binding.parameters['gain'] = 1
        with self.assertRaises(FrozenInstanceError):binding.effect_type = 'eval'
        with self.assertRaises(TypeError):item_effects.HANDLERS['eval'] = lambda: None

    def test_all_profiles_keep_definitions_and_use_their_own_pill_ids(self):
        for registry in [load_cultivation(), *(load_dungeons(**flags) for flags in PROFILES),
                         legacy_foundation_registry()]:
            with self.subTest(version=registry.content_version):
                before = dict(registry._definitions)
                table = bindings_for(registry)
                item_effects.validate_handlers(table)
                cfg = settings(registry) or {}
                pills = (cfg.get('leveling') or cfg.get('foundation_cultivation') or {}).get('pills', {})
                self.assertEqual(set(table), {('cultivation_train', 'pill')} |
                                 {('cultivation_use_pill', key) for key in pills})
                self.assertEqual(dict(registry._definitions), before)
        self.assertEqual(len(self.current._definitions), 1529)

    def test_missing_handler_rejected_before_store_is_used(self):
        table = bindings_for(self.current)
        with patch.object(item_effects, 'HANDLERS', MappingProxyType({})):
            with self.assertRaises(ValidationError):item_effects.validate_handlers(table)
            with self.assertRaises(ValidationError):EcologyApplication(None, self.current, ManualClock())

    def test_temporary_new_pill_uses_same_handler_without_name_inference(self):
        from src.data.items.resources import ResourceDefinition
        registry = DefinitionRegistry(schema_version=self.current.schema_version,
                                      content_version=self.current.content_version)
        for definition in self.current._definitions.values():
            if definition.key == DefinitionKey('sect_rules','shipping'):
                values = thaw_json(definition.values)
                values['leveling']['pills']['trial_tonic'] = dict(values['leveling']['pills']['ju_qi_pill'])
                definition = replace(definition,values=freeze_json(values))
            registry.register(definition)
        registry.register(ResourceDefinition('resources','trial_tonic','临时测试修为药',(),False))
        registry.seal()
        table = bindings_for(registry)
        self.assertIn(('cultivation_use_pill','trial_tonic'),table)
        result = item_effects.apply(table,'cultivation_use_pill','trial_tonic',growth.initial('effect'),
                                    registry,'effect',{'trial_tonic':10},count=2)
        self.assertEqual(result.costs,{'trial_tonic':2})
        self.assertGreater(result.cultivation['total_xp'],0)
        self.assertNotIn(('cultivation_use_pill','trial_tonic'),bindings_for(self.current))
        self.assertFalse(self.current.contains(DefinitionKey('resources','trial_tonic')))

    def test_current_loader_does_not_pin_invalid_effect_bindings(self):
        loader = content_loader.ContentLoader()
        with patch('src.data.item_effects.bindings_for', side_effect=ValidationError('bad binding')):
            with self.assertRaisesRegex(ValidationError, 'bad binding'):loader.load()
        self.assertIsNone(loader._registry)

    def assert_equivalent(self, registry, command, key, p, stock, **options):
        before = thaw_json(freeze_json(p)), dict(stock)
        try:
            candidate, events = original(command, key, p, registry, 'effect', stock, **options)
        except (ValidationError, growth.CultivationBlocked) as exc:
            with self.assertRaises(type(exc)) as caught:
                item_effects.apply(bindings_for(registry), command, key, p, registry,
                                   'effect', stock, **options)
            self.assertEqual(str(caught.exception), str(exc))
        else:
            result = item_effects.apply(bindings_for(registry), command, key, p, registry,
                                        'effect', stock, **options)
            self.assertEqual((result.cultivation, result.events), (candidate, events))
            self.assertEqual(result.costs, {events[0]['item_id']: events[0]['quantity']})
        self.assertEqual((thaw_json(freeze_json(p)), stock), before)

    def test_historical_progress_and_foundation_handlers_are_equivalent(self):
        registry = load_cultivation()
        for progress in (0, 1799, 1800):
            p = {**growth.initial('effect'), 'progress': progress}
            for count in (1, 3, 100):
                self.assert_equivalent(registry, 'cultivation_train', 'pill', p, {'pill': 30}, count=count)
        registry = legacy_foundation_registry()
        for key in settings(registry)['foundation_cultivation']['pills']:
            for progress in (0, 5999, 6000):
                p = {**growth.initial('effect'), 'current_realm': 'realm_1', 'progress': progress}
                self.assert_equivalent(registry, 'cultivation_use_pill', key, p, {key: 10}, count=3)

    def test_eight_profiles_every_pill_level_boundaries_and_batch_equivalence(self):
        for flags in PROFILES:
            registry = load_dungeons(**flags)
            c = leveling.config(registry)
            if c is None:
                for progress in (0, 1799, 1800):
                    self.assert_equivalent(registry, 'cultivation_train', 'pill',
                                           {**growth.initial('effect'), 'progress':progress}, {'pill':30}, count=3)
                continue
            for key, row in c['pills'].items():
                for L in {row['minimum_level'], row['maximum_level'], max(1, row['minimum_level']-1)}:
                    p = {'player_id': 'effect:hero', 'current_realm': 'realm_0' if L <= 500 else 'realm_1',
                         'total_xp': leveling.table(c)[L], 'growth_revision': 1}
                    with self.subTest(flags=flags, item=key, level=L):
                        self.assert_equivalent(registry, 'cultivation_use_pill', key, p, {key: 10}, count=3)
                        if key == 'pill':
                            self.assert_equivalent(registry, 'cultivation_train', key, p, {key: 10}, count=3)

    def test_current_time_window_reduction_clamp_and_rejections_equivalent(self):
        registry = self.current
        c = leveling.config(registry)
        p = {**growth.initial('effect'), 'total_xp': 0, 'pill_window_start_ms': 0,
             'pill_count': c['pill_full_count']-1}
        cases = [({}, {'ju_qi_pill': 10}, dict(count=3, world_ms=0)),
                 ({}, {'ju_qi_pill': 10}, dict(count=3, world_ms=c['pill_period_ms'])),
                 ({'pill_window_start_ms': 100}, {'ju_qi_pill': 10}, dict(world_ms=99)),
                 ({'total_xp': leveling.table(c)[101]-1}, {'ju_qi_pill': 10}, dict(count=10)),
                 ({}, {}, dict(count=1)), ({}, {'ju_qi_pill': 1}, dict(count=3)),
                 ({}, {'ju_qi_pill': 10}, dict(active=True))]
        cases += [({}, {'ju_qi_pill': 10}, dict(count=count)) for count in (0, -1, True, 1.5, None)]
        for extra, stock, options in cases:
            with self.subTest(extra=extra, options=options):
                self.assert_equivalent(registry, 'cultivation_use_pill', 'ju_qi_pill', {**p, **extra}, stock, **options)


class ItemEffectTransactionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.registry = load_dungeons(management=True, cold_jade=True, ecology=True)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='item-effects-', dir=V2_ROOT/'tests')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root/'isolated.sqlite3'
        self.clock = ManualClock(1000)
        state = initial_slice(self.registry, last_settled_at_ms=1000)
        domains = thaw_json(state.domains)
        domains['inventory']['holdings'].update(ju_qi_pill=100, pill=10, coins=1000, herb=100, spring_water=100)
        self.save = state.save_id
        domains['disciples']['assignments'] = {}
        counter = state.identity['instance_counter']+1
        domains['sect']['buildings'][f'{state.save_id}:1:i:{counter}'] = {
            'definition_id':'spring', 'level':1, 'construction_target':None}
        state = replace(state, identity={**state.identity,'instance_counter':counter}, domains=domains)
        with SQLiteSave.initialize(self.path, allowed_root=self.root) as store:
            EcologyApplication(store, self.registry, self.clock).create(state)

    @contextmanager
    def application(self):
        with SQLiteSave(self.path, allowed_root=self.root) as store:
            yield EcologyApplication(store, self.registry, self.clock)

    def command(self, app, name='cultivation_use_pill', payload=None, **changes):
        s = app.query(self.save)
        values = dict(save_id=self.save, generation=s.generation, expected_revision=s.revision,
                      request_id=str(uuid4()), name=name,
                      payload={'item_id': 'ju_qi_pill'} if payload is None else payload)
        return Command(**{**values, **changes})

    def test_real_cost_growth_default_count_replay_close_reopen_and_pure_views(self):
        with self.application() as app:
            before = app.query(self.save)
            q = self.command(app)
            r = app.execute(q)
            after = app.query(self.save)
            self.assertEqual(after.domains['inventory']['holdings']['ju_qi_pill'], 99)
            self.assertGreater(leveling.xp(partition(after), leveling.config(self.registry)),
                               leveling.xp(partition(before), leveling.config(self.registry)))
            self.assertEqual(r.result['operation'], 'cultivation_use_pill')
            self.assertEqual(r.result['events'][0]['quantity'], 1)
            self.assertEqual(app.execute(q), r)
            self.assertEqual(app.query(self.save), after)
        with self.application() as app, patch.object(item_effects, 'apply', side_effect=AssertionError('replay executed effect')):
            app.view(self.save); app.view(self.save)
            self.assertEqual(app.query(self.save), after)
            self.assertEqual(app.execute(q), r)
            self.assertEqual(app.query(self.save), after)
            conflict = replace(q, payload={'item_id':'ju_qi_pill', 'count':2})
            with self.assertRaises(ConflictError):app.execute(conflict)
            self.assertEqual(app.query(self.save), after)

    def test_new_route_matches_original_full_state_and_receipt(self):
        with self.application() as app:
            before = app.query(self.save)
            q = self.command(app, payload={'item_id':'ju_qi_pill','count':3})
            result = app.execute(q)
            after = app.query(self.save)
        def old_apply(bindings, command, key, p, registry, save, stock, active=False, **options):
            candidate, events = original(command,key,p,registry,save,stock,active,**options)
            return item_effects.ItemEffectResult(candidate,{events[0]['item_id']:events[0]['quantity']},events)
        with SQLiteSave.initialize(self.root/'original.sqlite3',allowed_root=self.root) as store:
            app = EcologyApplication(store,self.registry,self.clock)
            app.create(before)
            with patch.object(item_effects,'apply',side_effect=old_apply):old = app.execute(q)
            self.assertEqual(app.query(self.save),after)
            self.assertEqual(result,old)

    def commit_fixture(self, app, before, candidate):
        q = self.command(app, name='test_fixture', payload={})
        app.foundation.validate_state(candidate)
        with app.store.transaction():
            app.store.commit(before,candidate,StoredReceipt(candidate.save_id,candidate.generation,
                q.request_id,q.digest(),candidate.revision,'command',{}))

    def test_insufficient_inventory_rolls_back_then_large_count_clamps_at_pill_interval(self):
        with self.application() as app:
            state = app.query(self.save)
            domains = thaw_json(state.domains)
            domains['inventory']['holdings']['ju_qi_pill'] = 1
            low = replace(state,revision=state.revision+1,domains=domains)
            self.commit_fixture(app,state,low)
            q = self.command(app,payload={'item_id':'ju_qi_pill','count':3})
            with self.assertRaises(growth.CultivationBlocked):app.execute(q)
            self.assertEqual(app.query(self.save),low)
            self.assertIsNone(app.store.receipt(low.save_id,low.generation,q.request_id))
            c = leveling.config(self.registry)
            domains = thaw_json(low.domains)
            domains['cultivation'] = {**growth.initial(self.save), 'total_xp':leveling.table(c)[101]-1}
            edge = replace(low,revision=low.revision+1,domains=domains)
            self.commit_fixture(app,low,edge)
            result = app.execute(self.command(app,payload={'item_id':'ju_qi_pill','count':10000}))
            self.assertEqual(result.result['events'][0]['quantity'],1)
            self.assertNotIn('ju_qi_pill',app.query(self.save).domains['inventory']['holdings'])

    def test_old_receipt_replays_without_effect_after_fresh_process_restart(self):
        def old_apply(bindings, command, key, p, registry, save, stock, active=False, **options):
            candidate, events = original(command, key, p, registry, save, stock, active, **options)
            return item_effects.ItemEffectResult(candidate, {events[0]['item_id']:events[0]['quantity']}, events)
        with self.application() as app:
            q = self.command(app, payload={'item_id':'ju_qi_pill', 'count':3})
            with patch.object(item_effects, 'apply', side_effect=old_apply):r = app.execute(q)
            before = app.query(self.save)
        code = """
import json, sys
from pathlib import Path
from unittest.mock import patch
from src.application.ecology import EcologyApplication
from src.application.memory import Command
from src.core.save.sqlite import SQLiteSave
from src.core.state.envelope import thaw_json
from src.data.dungeons.definitions import load_dungeons
from src.systems.cultivation import item_effects
from tests.fixtures.time import ManualClock
root=Path(sys.argv[1]); q=Command(**json.loads(sys.argv[2]))
with SQLiteSave(root/'isolated.sqlite3',allowed_root=root) as store:
    app=EcologyApplication(store,load_dungeons(management=True,cold_jade=True,ecology=True),ManualClock(1000))
    before=app.query(q.save_id)
    with patch.object(item_effects,'apply',side_effect=AssertionError('old receipt executed')):
        r=app.execute(q)
    assert app.query(q.save_id)==before
    print(json.dumps({'result':thaw_json(r.result),'revision':before.revision},sort_keys=True))
"""
        data = {key:getattr(q, key) for key in ('save_id','generation','expected_revision','request_id','name','payload','version')}
        data['payload'] = thaw_json(q.payload)
        child = subprocess.run([sys.executable, '-B', '-c', code, str(self.root), json.dumps(data)],
                               cwd=V2_ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(child.returncode, 0, child.stderr)
        result = json.loads(child.stdout)
        self.assertEqual(result, {'result':thaw_json(r.result), 'revision':before.revision})

    def test_handler_inventory_validation_and_commit_failures_roll_back(self):
        for stage in ('handler', 'inventory', 'validation', 'commit'):
            with self.subTest(stage=stage), self.application() as app:
                before = app.query(self.save)
                q = self.command(app)
                if stage == 'handler':
                    target, attr = item_effects, 'apply'
                elif stage == 'inventory':
                    from src.systems.inventory import operations
                    target, attr = operations, 'consume'
                elif stage == 'validation':target, attr = app.foundation, 'validate_state'
                else:target, attr = app.store, 'commit'
                actual = getattr(target, attr)
                def fail(*args, **kwargs):
                    # Even a failure after a real SQL commit call must roll back in the outer transaction.
                    actual(*args, **kwargs)
                    raise ValidationError('injected failure')
                with patch.object(target, attr, side_effect=fail):
                    with self.assertRaisesRegex(ValidationError, 'injected failure'):app.execute(q)
                self.assertEqual(app.query(self.save), before)
                self.assertIsNone(app.store.receipt(before.save_id, before.generation, q.request_id))
                app.execute(q)

    def test_bad_inputs_stale_revision_and_generation_do_not_write_receipts(self):
        payloads = ({'item_id':'wood'}, {'item_id':'missing'}, {'item_id':['ju_qi_pill']},
                    {'item_id':'ju_qi_pill','count':0}, {'item_id':'ju_qi_pill','count':True},
                    {'item_id':'ju_qi_pill','count':-1},
                    {'item_id':'ju_qi_pill','gain':999}, {})
        with self.application() as app:
            before = app.query(self.save)
            qs = [self.command(app, payload=payload) for payload in payloads]
            qs += [self.command(app, expected_revision=before.revision+1),
                   self.command(app, generation=before.generation+1)]
            for q in qs:
                with self.subTest(payload=q.payload):
                    with self.assertRaises((ValidationError, ConflictError)):app.execute(q)
                    self.assertEqual(app.query(self.save), before)
                    self.assertIsNone(app.store.receipt(before.save_id,before.generation,q.request_id))

    def test_pending_blocks_handler_and_preserves_jobs_deadlines_and_receipts(self):
        from src.application.settlement import SettlementRequest
        with self.application() as app:
            before = app.query(self.save)
            for kind, recipe in (('spring','sect_spring_water'), ('mine','ore')):
                bid = next(key for key,row in before.domains['sect']['buildings'].items()
                           if row['definition_id'] == kind)
                app.execute(self.command(app, name='work_assign', payload={'building_id':bid,'count':1}))
                app.execute(self.command(app, name='production_start', payload={'building_id':bid,'recipe_id':recipe}))
            self.clock.advance(300000)
            state = app.query(self.save)
            app.settle(SettlementRequest(self.save,state.generation,state.revision,str(uuid4()),1,None))
            pending = app.query(self.save)
            self.assertIsNotNone(pending.time['pending'])
            q = self.command(app)
            with patch.object(item_effects,'apply',side_effect=AssertionError('pending reached handler')):
                with self.assertRaises(ConflictError):app.execute(q)
            self.assertEqual(app.query(self.save),pending)
            self.assertIsNone(app.store.receipt(pending.save_id,pending.generation,q.request_id))
        with self.application() as app:
            self.assertEqual(app.query(self.save),pending)

    def test_pause_and_active_battle_block_without_consumption(self):
        with self.application() as app:
            app.execute(self.command(app, name='world_pause', payload={}))
            paused = app.query(self.save)
            with self.assertRaises(ValidationError):app.execute(self.command(app))
            self.assertEqual(app.query(self.save), paused)
            app.execute(self.command(app, name='world_resume', payload={}))
            app.execute(self.command(app, name='combat_start', payload={'encounter_id':'thorn_path_v2_001'}))
            active = app.query(self.save)
            self.assertEqual(active.domains['combat']['battle']['status'], 'ACTIVE')
            with self.assertRaises(growth.CultivationBlocked):app.execute(self.command(app))
            self.assertEqual(app.query(self.save), active)


if __name__ == '__main__':unittest.main()

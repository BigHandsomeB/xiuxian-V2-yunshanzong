"""Real disposable SQLite commands, shared settlement and additive legacy snapshots."""
from dataclasses import replace
from unittest.mock import patch
import unittest
from uuid import uuid4
from src.core.state.envelope import thaw_json
from src.core.validation import ValidationError, ConflictError
from src.core.time.world import paused
from src.data.content_loader import load_current
from src.data.exploration.definitions import settings, region
from src.application.exploration import transition
from src.systems.sect import exploration
from tests.systems import test_ecology as fixtures


class ExplorationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = load_current()
    for name in ('setUp','read','view','request','execute','command','settle','fixture','remove','bid','assign','buy'):
        locals()[name] = getattr(fixtures.EcologyTests,name)

    def start(self,rid='thorn_outskirts'):
        self.command('exploration_start',{'region_id':rid})
        return self.read().domains['sect_management']['exploration']['active']

    def finish(self):
        active = self.read().domains['sect_management']['exploration']['active']
        self.settle(active['due_ms']-self.read().time['sim_time_ms'])
        return self.view()['exploration']['active']

    def choose(self,choice='leave'):
        a = self.read().domains['sect_management']['exploration']['active']
        return self.command('exploration_choose',{'journey_id':a['id'],'choice_id':choice})

    def test_legacy_get_is_pure_and_old_equipment_preserved(self):
        before=self.read();view=self.view()['exploration']
        self.assertNotIn('exploration',before.domains['sect_management']);self.assertIsNone(view['active'])
        self.assertEqual(len(view['regions']),4);self.assertEqual(self.read(),before)
        self.start();after=self.read()
        for key,value in before.domains.items():
            if key!='sect_management':
                self.assertEqual({k:thaw_json(after.domains[key][k]) for k in value},thaw_json(value),key)
        self.assertEqual(before.time,after.time)
        self.assertEqual(before.identity,after.identity)

    def test_catalog_and_unlocks_match_existing_dungeon_gates(self):
        self.assertEqual(sum(len(r['events']) for r in settings(self.registry)['regions']),12)
        self.assertEqual([r['unlocked'] for r in self.view()['exploration']['regions']],[True,False,False,False])
        before=self.read()
        for r in settings(self.registry)['regions'][1:]:
            with self.assertRaises(ConflictError):self.start(r['id'])
            self.assertEqual(self.read(),before)
        def unlock(s):
            d=thaw_json(s.domains['dungeon']);d.update(cleared_floor=100,progress={'red_copper_mine':100,'mist_marsh':100})
            return replace(s,domains={**s.domains,'dungeon':d})
        self.fixture(unlock)
        self.assertTrue(all(r['can_start'] for r in self.view()['exploration']['regions']))
        for r in settings(self.registry)['regions']:
            with self.subTest(region=r['id']):
                self.start(r['id']);self.finish();result=self.choose()
                self.assertEqual(dict(result.result['rewards']),dict(r['rewards']))

    def test_start_replay_and_second_journey_blocked(self):
        request=self.request('exploration_start',{'region_id':'thorn_outskirts'})
        receipt=self.execute(request);after=self.read()
        self.assertEqual(receipt,self.execute(request));self.assertEqual(self.read(),after)
        with self.assertRaises(ValidationError):self.start()
        self.assertEqual(self.read(),after)
        with self.assertRaises(ConflictError):self.execute(replace(request,request_id=str(uuid4())))
        self.assertEqual(self.read(),after)

    def test_early_unknown_and_stale_choices_never_mutate(self):
        a=self.start();before=self.read()
        for payload in ({'journey_id':a['id'],'choice_id':'leave'}, {'journey_id':'old','choice_id':'leave'}):
            with self.assertRaises(ValidationError):self.command('exploration_choose',payload)
            self.assertEqual(before,self.read())
        self.finish();before=self.read()
        with self.assertRaises(ValidationError):self.choose('nonexistent')
        self.assertEqual(before,self.read())

    def test_result_hidden_until_ready_and_no_get_reroll(self):
        active=self.start();snapshot=self.read();v=self.view()['exploration']['active']
        self.assertNotIn('event',v);self.assertNotIn('roll',v);self.assertEqual(self.read(),snapshot)
        v=self.finish();before=self.read()
        self.assertIn('event',v);self.assertNotIn('roll',v)
        self.assertEqual(v,self.view()['exploration']['active']);self.assertEqual(before,self.read())
        self.assertEqual(active['event_id'],v['event']['id'])

    def test_ready_journey_polls_only_until_due(self):
        self.start();self.assertTrue(self.view()['economy']['needs_poll'])
        self.assertTrue(self.view()['economy']['needs_settlement'])
        self.finish();self.assertTrue(self.view()['exploration']['active']['ready'])

    def test_choose_replay_and_different_request_double_claim_rejected(self):
        self.start();a=self.finish();stock=dict(self.read().domains['inventory']['holdings'])
        request=self.request('exploration_choose',{'journey_id':a['id'],'choice_id':'leave'})
        receipt=self.execute(request);after=self.read()
        self.assertEqual(after.domains['inventory']['holdings']['ordinary_wood'],stock['ordinary_wood']+2)
        self.assertEqual(receipt,self.execute(request));self.assertEqual(after,self.read())
        with self.assertRaises(ValidationError):self.command('exploration_choose',request.payload)
        self.assertEqual(after,self.read());self.assertIsNone(self.view()['exploration']['active'])
        self.assertEqual(len(self.view()['exploration']['history']),1)

    def test_rotation_covers_three_without_repeats_and_history_is_bounded(self):
        self.start();s=self.read();seen=[]
        for visit in range(1,34):
            if visit>1:s=transition(s,self.registry,'exploration_start',{'region_id':'thorn_outskirts'},100000)[0]
            a=exploration.ledger(s)['active'];seen.append(a['event_id'])
            s=replace(s,time={**s.time,'sim_time_ms':a['due_ms']})
            s,_=transition(s,self.registry,'exploration_choose',{'journey_id':a['id'],'choice_id':'leave'},100000)
        self.assertEqual(len(set(seen[:3])),3);self.assertTrue(all(a!=b for a,b in zip(seen,seen[1:])))
        p=exploration.ledger(s);self.assertEqual(len(p['history']),30);self.assertEqual(p['history'][0]['sequence'],4)
        self.assertEqual(p['sequence'],33);exploration.validate_state(s,self.registry)

    def test_pause_freezes_and_resume_excludes_paused_wall_time(self):
        a=self.start();self.command('world_pause',{});before=self.read()
        with self.assertRaises(ValidationError):self.settle(240000)
        self.assertEqual(before.time['sim_time_ms'],self.read().time['sim_time_ms'])
        with self.assertRaises(ValidationError):self.choose()
        self.assertTrue(paused(self.read().time));self.command('world_resume',{})
        self.assertFalse(paused(self.read().time));self.assertFalse(self.view()['exploration']['active']['ready'])
        self.finish();self.choose()

    def test_paused_start_and_pending_commands_blocked(self):
        self.command('world_pause',{});before=self.read()
        with self.assertRaises(ValidationError):self.start()
        self.assertEqual(self.read(),before)
        self.command('world_resume',{})
        from src.application.settlement import SettlementRequest
        from src.core.save.sqlite import SQLiteSave
        from src.application.ecology import EcologyApplication
        self.assign('pasture');self.buy()
        self.clock.advance(600000);state=self.read()
        with SQLiteSave(self.path,allowed_root=self.root) as store:
            EcologyApplication(store,self.registry,self.clock).settle(SettlementRequest(self.sid,state.generation,state.revision,str(uuid4()),1,None))
        self.assertTrue(self.read().time['pending'])
        before=self.read()
        with self.assertRaises(ConflictError):self.start()
        self.assertEqual(self.read(),before)

    def test_full_warehouse_preserves_journey_cost_and_reward(self):
        self.start();self.finish();before=self.read()
        with patch('src.application.ecology.EcologyApplication._capacity',return_value=0):
            with self.assertRaisesRegex(ValidationError,'仓库空间不足'):self.choose()
            view=self.view()['exploration']['active']
            self.assertTrue(all(not c['can_choose'] for c in view['event']['choices']))
        self.assertEqual(before,self.read());self.choose()

    def test_every_event_option_real_cost_reward_and_failed_outcome(self):
        # Exercise all content, including paid choices and both sides of risk.
        baseline=self.read()
        for r in settings(self.registry)['regions']:
            for e in r['events']:
                for c in e['choices']:
                    for success in ([True,False] if c['success_bps']<10000 else [True]):
                        with self.subTest(event=e['id'],choice=c['id'],success=success):
                            a=dict(id='explore:1',sequence=1,region_id=r['id'],event_id=e['id'],started_ms=0,
                                   due_ms=r['duration_days']*baseline.time['day_length_ms'],roll=0 if success else 9999)
                            p={'sequence':1,'visits':{r['id']:1},'active':a,'history':[]}
                            m=thaw_json(baseline.domains['sect_management']);m['exploration']=p
                            s=replace(baseline,time={**baseline.time,'sim_time_ms':a['due_ms']},domains={**baseline.domains,'sect_management':m})
                            candidate,details=transition(s,self.registry,'exploration_choose',{'journey_id':a['id'],'choice_id':c['id']},100000)
                            expected=dict(r['rewards'])
                            if success:
                                for rid,n in c['rewards'].items():expected[rid]=expected.get(rid,0)+n
                            self.assertEqual(details['rewards'],expected);self.assertEqual(details['success'],success)
                            for rid in set(expected)|set(c['cost']):
                                self.assertEqual(candidate.domains['inventory']['holdings'].get(rid,0),s.domains['inventory']['holdings'].get(rid,0)-c['cost'].get(rid,0)+expected.get(rid,0))

    def test_material_shortage_and_reserves_keep_event(self):
        self.start();s=self.read()
        # Move through the fixed rotation until the wounded scatterer, which has a paid water choice.
        for _ in range(3):
            a=self.finish()
            if a['event']['id']=='wounded_wanderer':break
            self.choose();self.start()
        self.assertEqual(a['event']['id'],'wounded_wanderer')
        def reserve(s):
            m=thaw_json(s.domains['sect_management']);m['material_reserves']['spring_water']=s.domains['inventory']['holdings']['spring_water']-1
            return replace(s,domains={**s.domains,'sect_management':m})
        self.fixture(reserve);before=self.read()
        with self.assertRaisesRegex(ValidationError,'保留量'):self.choose('help')
        self.assertEqual(before,self.read())
        self.remove('spring_water');before=self.read()
        with self.assertRaisesRegex(ValidationError,'材料不足'):self.choose('help')
        self.assertEqual(before,self.read());self.choose('leave')

    def test_tampered_roll_deadline_and_unknown_fields_rejected(self):
        self.start();s=self.read()
        for change in (lambda a:a.update(roll=(a['roll']+1)%10000),lambda a:a.update(due_ms=a['due_ms']+1),lambda a:a.update(extra=True)):
            p=exploration.ledger(s);change(p['active']);m=thaw_json(s.domains['sect_management']);m['exploration']=p
            with self.assertRaises(ValidationError):exploration.validate_state(replace(s,domains={**s.domains,'sect_management':m}),self.registry)

    def test_offline_full_and_chunked_completion_match(self):
        from src.core.save.sqlite import SQLiteSave
        from src.application.ecology import EcologyApplication
        from tests.fixtures.time import ManualClock
        self.start();before=self.read();original_path=self.path
        other=self.root/'chunked.sqlite3'
        with SQLiteSave.initialize(other,allowed_root=self.root) as store:
            EcologyApplication(store,self.registry,self.clock).create(before)
        self.settle(600000);full=thaw_json(self.view()['exploration'])
        self.path=other;self.clock=ManualClock()
        for _ in range(5):self.settle(120000,max_events=2)
        chunked=thaw_json(self.view()['exploration'])
        self.assertEqual(full,chunked);self.assertTrue(chunked['active']['ready'])
        self.assertEqual(chunked['history'],[])
        # Arrival does not auto-grant rewards or expire the encounter.
        self.assertEqual(self.read().domains['inventory'],before.domains['inventory'])
        self.choose();chunked_result=self.read().domains['inventory']
        self.path=original_path;self.choose();self.assertEqual(self.read().domains['inventory'],chunked_result)

    def test_maximum_reward_capacity_never_discloses_saved_roll(self):
        self.start();self.finish();baseline=self.read()
        r=settings(self.registry)['regions'][0];e=next(e for e in r['events'] if e['id']=='mist_fork')
        for roll in (0,9999):
            p=exploration.ledger(baseline);p['active'].update(event_id=e['id'],roll=roll)
            m=thaw_json(baseline.domains['sect_management']);m['exploration']=p
            s=replace(baseline,domains={**baseline.domains,'sect_management':m})
            from src.systems.inventory.holdings import stock_size
            cap=stock_size(s.domains['inventory'],self.registry)+r['rewards']['ordinary_wood']
            with self.assertRaisesRegex(ValidationError,'仓库空间不足'):
                transition(s,self.registry,'exploration_choose',{'journey_id':p['active']['id'],'choice_id':'deep'},cap)

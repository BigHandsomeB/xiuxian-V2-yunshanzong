"""Story packages, real SQLite/HTTP acknowledgements and factual old-save backfill."""
import json
from pathlib import Path
from dataclasses import replace
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4
import unittest

from tests import test_market_restock as fixtures
from src.core.state.envelope import thaw_json
from src.core.validation import ValidationError,ConflictError
from src.core.save.sqlite import SQLiteSave
from src.data.story.definitions import catalog,validate,load_catalog
from src.systems.sect import story
from src.application.memory import Command
from src.application.settlement import SettlementRequest
from src.systems.resources import jobs


class StoryTests(unittest.TestCase):
    setUpClass=classmethod(fixtures.RestockTests.setUpClass.__func__)
    setUp=fixtures.RestockTests.setUp
    for name in ('app','read','view','request','command','fixture','settle'):
        locals()[name]=getattr(fixtures.RestockTests,name)

    def complete(self):
        def update(s):
            d=thaw_json(s.domains['dungeon']);d['cleared_floor']=100
            d['progress']={did:100 for did in ['red_copper_mine','mist_marsh','cold_jade_cave','fire_elixir_ruins']}
            return replace(s,domains={**s.domains,'dungeon':d})
        self.fixture(update)

    def test_catalog_all_36_and_no_rewards_or_author_truth(self):
        data=catalog();self.assertEqual(len(data['nodes']),36)
        self.assertEqual(len({n['id'] for n in data['nodes']}),36)
        text=json.dumps(thaw_json(data),ensure_ascii=False)
        self.assertNotIn('日志里的',text);self.assertIn('残刻所指',text)
        self.assertIn('检修台旁拂开积灰，露出',text)
        for n in data['nodes']:
            self.assertNotIn('rewards',n);self.assertNotIn('author',n)

    def test_pure_old_save_view_no_automatic_migration(self):
        before=self.read();v=self.view()['story'];self.assertEqual(before,self.read())
        self.assertNotIn('story',before.domains['sect_management'])
        self.assertEqual(v['unread_count'],1);self.assertTrue(v['nodes'][0]['can_read'])
        self.assertTrue(all(not n['lines'] for n in v['nodes'] if not n['can_read']))

    def test_read_preserves_all_gameplay_and_time_while_paused(self):
        self.command('world_pause',{});before=self.read();q=self.request('story_read',{'node_id':'chapter_1_01'})
        receipt=self.command('',{},q);after=self.read()
        self.assertEqual(after.time,before.time);self.assertEqual(after.identity,before.identity)
        for domain in before.domains:
            if domain!='sect_management':self.assertEqual(after.domains[domain],before.domains[domain],domain)
        old=thaw_json(before.domains['sect_management']);old.pop('story',None);new=thaw_json(after.domains['sect_management']);new.pop('story')
        self.assertEqual(old,new);self.assertEqual(self.command('',{},q),receipt);self.assertEqual(after,self.read())

    def test_locked_and_out_of_order_are_atomic_no_spoilers(self):
        for nid in ['missing','chapter_5_07','chapter_1_03']:
            before=self.read()
            with self.assertRaises(ValidationError):self.command('story_read',{'node_id':nid})
            self.assertEqual(before,self.read())
        self.complete();v=self.view()['story']
        last=next(n for n in v['nodes'] if n['id']=='chapter_5_07')
        self.assertTrue(last['unlocked']);self.assertFalse(last['can_read']);self.assertEqual(last['lines'],())

    def test_old_complete_save_backfills_main_in_order_without_side_gates(self):
        self.complete();before=self.read();v=self.view()['story'];self.assertEqual(self.read(),before)
        self.assertEqual(sum(n['unlocked'] for n in v['nodes'] if n['track']=='main'),33)
        for n in catalog()['nodes']:
            if n['track']=='main':self.command('story_read',{'node_id':n['id']})
        view=self.view()['story'];self.assertEqual(view['read_count'],33)
        self.assertFalse(next(n for n in view['nodes'] if n['id']=='chapter_1_02')['unlocked'])
        self.assertTrue(next(n for n in view['nodes'] if n['id']=='chapter_5_07')['read'])

    def test_foundation_node_independent_and_not_given_to_qi(self):
        from src.systems.cultivation import growth
        before=self.read();grown=thaw_json(before.domains['cultivation'])
        grown.update(current_realm='realm_1',progress=0,growth_revision=1)
        state=replace(before,domains={**before.domains,'cultivation':grown})
        v=story.projection(state,self.registry);node=next(n for n in v['nodes'] if n['id']=='cultivation_foundation_01')
        self.assertTrue(node['can_read']);self.assertFalse(any(n['unlocked'] for n in v['nodes'] if n['chapter']=='chapter_3'))
        self.assertFalse(next(n for n in self.view()['story']['nodes'] if n['id']==node['id'])['unlocked'])
        changed=story.mark_read(state,self.registry,{'node_id':node['id']});self.assertIn(node['id'],story.ledger(changed)['read'])

    def test_selected_fact_survives_switching_and_restart_connections(self):
        self.fixture(lambda s:replace(s,domains={**s.domains,'dungeon':{**s.domains['dungeon'],'cleared_floor':100}}))
        self.command('dungeon_select',{'dungeon_id':'red_copper_mine'})
        self.assertIn('chapter_2_01',story.ledger(self.read())['unlocked'])
        self.command('dungeon_select',{'dungeon_id':'thorn_path'})
        self.assertTrue(next(n for n in self.view()['story']['nodes'] if n['id']=='chapter_2_01')['unlocked'])
        self.assertFalse(next(n for n in self.view()['story']['nodes'] if n['id']=='chapter_2_02')['unlocked'])

    def test_manual_battle_entry_is_recorded_without_changing_rewards(self):
        from src.systems.dungeons import progress
        eid=progress.definition(self.registry,'thorn_path').encounters[0]
        self.command('combat_start',{'encounter_id':eid})
        s=self.read();self.assertIn('chapter_1_03',story.ledger(s)['unlocked'])
        self.assertEqual(progress.cleared(s.domains['dungeon']),0)
        self.assertEqual(s.domains['combat']['battle']['status'],'ACTIVE')

    def test_wood_event_only_after_actual_production_delivery(self):
        before=self.read()
        self.fixture(lambda s:replace(s,domains={**s.domains,'inventory':{'holdings':{'coins':100000,'wood':100}}}))
        self.assertFalse(next(n for n in self.view()['story']['nodes'] if n['id']=='chapter_1_02')['unlocked'])
        state=self.read();bid=next(k for k,b in state.domains['sect']['buildings'].items() if b['definition_id']=='forest')
        self.command('work_assign',{'building_id':bid,'count':1})
        recipe=next(r for r in self.view()['economy']['recipes'] if r['building_id']==bid and any(o['resource_id'] in ('wood','ordinary_wood') for o in r['outputs']))
        self.command('production_start',{'building_id':bid,'recipe_id':recipe['recipe_id']})
        self.assertNotIn('chapter_1_02',story.ledger(self.read())['unlocked'])
        due=self.read().domains['production']['jobs'][bid]['due_ms'];self.settle(due-state.time['sim_time_ms']+1)
        self.assertIn('chapter_1_02',story.ledger(self.read())['unlocked'])

    def test_rollback_after_sql_write_and_retry(self):
        before=self.read();commit=SQLiteSave.commit
        def fail(store,*args):commit(store,*args);raise RuntimeError('after write')
        with patch.object(SQLiteSave,'commit',fail):
            with self.assertRaises(RuntimeError):self.command('story_read',{'node_id':'chapter_1_01'})
        self.assertEqual(before,self.read());self.command('story_read',{'node_id':'chapter_1_01'})
        self.assertEqual(self.view()['story']['read_count'],1)

    def test_stale_revision_generation_and_pending_refuse(self):
        q=self.request('story_read',{'node_id':'chapter_1_01'});self.command('world_pause',{})
        with self.assertRaises(ConflictError):self.command('',{},q)
        q=self.request('story_read',{'node_id':'chapter_1_01'})
        with self.assertRaises(ConflictError):self.command('',{},replace(q,generation=q.generation+1))

    def test_running_auto_read_preserves_battle_and_pending_refuses(self):
        self.fixture(lambda s:replace(s,domains={**s.domains,'dungeon':{**s.domains['dungeon'],'cleared_floor':1}}))
        self.command('dungeon_auto',{'enabled':True,'mode':'farm','floor':1})
        before=self.read();self.command('story_read',{'node_id':'chapter_1_01'});after=self.read()
        self.assertEqual(before.time,after.time);self.assertEqual(before.domains['dungeon'],after.domains['dungeon'])
        self.assertEqual(before.domains.get('combat'),after.domains.get('combat'))
        self.clock.advance(60000);s=self.read()
        with self.app() as app:app.settle(SettlementRequest(self.sid,s.generation,s.revision,str(uuid4()),1,None))
        pending=self.read();self.assertIsNotNone(pending.time['pending'])
        with self.assertRaises(ConflictError):self.command('story_read',{'node_id':'chapter_1_01'})
        self.assertEqual(pending,self.read())

    def test_read_id_survives_text_revision_append_and_retirement(self):
        self.command('story_read',{'node_id':'chapter_1_01'});state=self.read();data=thaw_json(catalog())
        data['nodes'][0]['lines'][0]['text']='修订后的文字'
        with patch('src.systems.sect.story.catalog',return_value=data):
            v=story.projection(state,self.registry);self.assertTrue(v['nodes'][0]['read']);self.assertEqual(v['nodes'][0]['lines'][0]['text'],'修订后的文字')
        data['nodes'].pop(0)
        with patch('src.systems.sect.story.catalog',return_value=data):
            changed=story.observe(state,self.registry);self.assertIn('chapter_1_01',story.ledger(changed)['read'])

    def test_reject_duplicate_packages_bad_condition_and_missing_text(self):
        original=thaw_json(catalog())
        for change in [lambda d:d['nodes'].append(d['nodes'][0]),lambda d:d['nodes'][0].update(condition={'kind':'grant_reward'}),lambda d:d['nodes'][0].update(lines=[])]:
            data=json.loads(json.dumps(original));change(data)
            with self.assertRaises(ValidationError):validate(data)

    def test_append_package_can_extend_without_changing_existing_ids(self):
        with TemporaryDirectory(dir=self.root) as tmp:
            root=Path(tmp);(root/'catalog.json').write_text(json.dumps({'schema_version':1,'packages':['one.json','two.json']}))
            one=thaw_json(catalog());one.update(schema_version=1,release='one');(root/'one.json').write_text(json.dumps(one))
            node=dict(one['nodes'][0]);node.update(id='chapter_6_01',chapter='chapter_6',order=2000)
            two={'schema_version':1,'release':'two','chapters':[{'id':'chapter_6','title':'后续章节'}],'nodes':[node]}
            (root/'two.json').write_text(json.dumps(two));extended=load_catalog(root)
            self.assertEqual(len(extended['nodes']),37);self.assertEqual(extended['nodes'][0]['id'],'chapter_1_01')


class StoryHTTPTests(fixtures.RestockHTTPTests):
    # Reuse the protected HTTP fixture, not its unrelated restock test cases.
    test_http_configure_workforce_purchase_and_replay=None
    test_http_invalid_locked_csrf_and_stale_are_atomic=None

    def test_story_read_real_command_and_pure_views(self):
        before=self.read();v=self.client.get('/api/view');self.assertEqual(v.status_code,200);self.assertEqual(before,self.read())
        body=self.body('story_read',{'node_id':'chapter_1_01'});first=self.post(body)
        self.assertEqual(first.status_code,200,first.json);self.assertEqual(first.json,self.post(body).json)
        self.assertEqual(self.view()['story']['read_count'],1);self.assertEqual(before.time,self.read().time)
        self.assertEqual(self.post(self.body('story_read',{'node_id':'chapter_5_07'})).status_code,422)

    def test_read_without_csrf_does_not_mutate(self):
        before=self.read();body=self.body('story_read',{'node_id':'chapter_1_01'})
        self.assertEqual(self.client.post('/api/command',json=body).status_code,403);self.assertEqual(before,self.read())

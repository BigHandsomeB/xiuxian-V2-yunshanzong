"""Batch-one boundaries and atomic commands against isolated SQLite, no simulation."""
import json
import unittest
from dataclasses import replace
from unittest.mock import patch
from src.core.state.envelope import thaw_json
from src.core.validation import ValidationError
from src.data.items.resources import load_resources
from src.data.registry import DefinitionKey
from src.data.economy.sect_rules import settings
from src.systems.cultivation import growth
from src.systems.sect import rules
from src.systems.resources import jobs
from src.application import equipment as equip
from src.application.sect_economy import defaults
from src.application.production import ProductionSettlement
from tests.systems import test_sect_economy as fixtures

class BatchTests(unittest.TestCase):
    # Share only the existing isolated fixture/command helpers, not its test methods.
    for _name in ('setUp','create','state','bid','request','command','assign','settle','assertRejected','rich'):
        locals()[_name]=getattr(fixtures.SectEconomyTests,_name)

    def assign(self,kind,count=1):
        from src.systems.disciples import work
        state=self.state()
        gid=next(k for k,v in state.domains['disciples']['groups'].items() if v['count']-sum(work.allocations(state.domains['disciples'],k).values())>=count)
        return self.command('work_assign',{'worker_id':gid,'building_id':self.bid(kind),'count':count})

    def rank_fixture(self,level=3,cleared=30):
        from src.systems.dungeons import progress
        domains=thaw_json(defaults(self.s,self.r).domains)
        domains['dungeon']=thaw_json(progress.initial());domains['dungeon']['cleared_floor']=cleared
        for row in domains['sect']['buildings'].values():
            if row['definition_id'] in settings(self.r)['building_upgrade']['materials']:row['level']=level
        self.s=replace(self.s,domains=domains)

    def test_tiers_and_legacy_definition_default(self):
        self.assertEqual(self.r.lookup(DefinitionKey('resources','ore')).display_name,'凡铁矿')
        self.assertEqual(self.r.lookup(DefinitionKey('resources','ingot')).tier,'凡')
        self.assertEqual(self.r.lookup(DefinitionKey('resources','spirit_iron_ore')).tier,'灵')
        for key in ('grain','spirit_plank','refined_iron_ingot','pill_1_0','gu_yuan_pill'):
            self.assertEqual(self.r.lookup(DefinitionKey('resources',key)).tier,'待定')
        from pathlib import Path
        source=json.loads(Path('src/data/items/resources.json').read_text())
        for row in source['definitions']:row.pop('tier')
        r=load_resources(json.dumps(source));self.assertEqual(r.lookup(DefinitionKey('resources','ore')).tier,'待定')

    def test_foundation_boundaries_and_only_hp_attack(self):
        for n,bonus in [(1999,0),(2000,800),(3999,800),(4000,1600),(5999,1600),(6000,1600)]:
            p={**growth.initial(self.sid),'current_realm':'realm_1','growth_revision':1,'progress':n}
            self.assertEqual(growth.stage(p,self.r)['bonus_bps'],bonus)
            hero=growth.projection(p,self.r,self.sid)
            self.assertEqual(hero['max_hp_milli'],210000*(10000+bonus)//10000)
            self.assertEqual(hero['attack_milli'],26000*(10000+bonus)//10000)
            self.assertEqual(hero['armor_milli'],1000)
        with self.assertRaises(ValidationError):growth.validate({**p,'progress':6001},self.r,self.sid)

    def test_qi_cannot_use_any_foundation_pill(self):
        stock={k:1 for k in settings(self.r)['foundation_cultivation']['pills']};self.create(stock)
        for key in stock:self.assertRejected('cultivation_use_pill',{'item_id':key})

    def test_pill_atomic_replay_and_receipt_rollback(self):
        self.create({'pill_1_0':10},realm='realm_1',progress=1990)
        q=self.request('cultivation_use_pill',{'item_id':'pill_1_0','count':2});before=self.state()
        with patch.object(self.store,'_insert_receipt',side_effect=RuntimeError('injected failure')):
            with self.assertRaises(RuntimeError):self.app.execute(q)
        self.assertEqual(before,self.state())
        receipt=self.app.execute(q);after=self.state()
        self.assertEqual(after.domains['cultivation']['progress'],2050)
        self.assertEqual(after.domains['inventory']['holdings']['pill_1_0'],8)
        self.assertEqual(receipt,self.app.execute(q));self.assertEqual(after,self.state())
        self.assertRejected('cultivation_use_pill',{'item_id':'pill_1_0','count':9})
        self.assertRejected('cultivation_use_pill',{'item_id':'pill','count':1})
        for invalid_item in (None,True,[],{},123):self.assertRejected('cultivation_use_pill',{'item_id':invalid_item})
        for count in (0,-1,True,1.5):self.assertRejected('cultivation_use_pill',{'item_id':'pill_1_0','count':count})
        self.command('world_pause',{});self.assertRejected('cultivation_use_pill',{'item_id':'pill_1_0'})
        self.assertEqual(receipt,self.app.execute(q))
        self.assertFalse(next(r for r in self.app.view(self.sid)['cultivation']['foundation_pills'] if r['item_id']=='pill_1_0')['can_use'])

    def test_full_stops_consumption(self):
        self.create({'yang_yuan_pill':10},realm='realm_1',progress=5999)
        self.command('cultivation_use_pill',{'item_id':'yang_yuan_pill','count':10})
        self.assertEqual(self.state().domains['cultivation']['progress'],6000)
        self.assertEqual(self.state().domains['inventory']['holdings']['yang_yuan_pill'],9)
        self.assertRejected('cultivation_use_pill',{'item_id':'yang_yuan_pill'})

    def test_legacy_foundation_read_is_zero_no_stat_loss_or_equipment_change(self):
        self.s,identity=equip.acquire(self.s,self.r,'thorn_fang_blade','old-roll',roll_version='thorn-roll-v2')
        self.create(legacy=True,realm='realm_1');before=self.state();v=self.app.view(self.sid)
        self.assertEqual(v['cultivation']['progress'],0)
        self.assertEqual(growth.projection(before.domains['cultivation'],self.r,self.sid)['max_hp_milli'],210000)
        self.assertEqual(before,self.state());self.assertEqual(before.domains['equipment']['instances'][identity],self.state().domains['equipment']['instances'][identity])

    def test_every_rank_building_count_level_and_floor_boundaries(self):
        cfg=settings(self.r);kinds=list(cfg['building_upgrade']['materials'])
        for r in cfg['sect_levels']:
            good={'buildings':{str(i):{'definition_id':kind,'level':r['building_level']} for i,kind in enumerate(kinds[:r['building_count']])}}
            self.assertEqual(rules.development(good,self.r,r['cleared_floor'])['level'],r['level'])
            self.assertLess(rules.development(good,self.r,r['cleared_floor']-1)['level'],r['level'])
            part=thaw_json(good);part['buildings'].pop('0');self.assertLess(rules.development(part,self.r,r['cleared_floor'])['level'],r['level'])
            part=thaw_json(good);part['buildings']['0']['level']-=1;self.assertLess(rules.development(part,self.r,r['cleared_floor'])['level'],r['level'])
        closed={'buildings':{str(i):{'definition_id':'forge','level':10} for i in range(9)}}
        self.assertEqual(rules.development(closed,self.r,100)['level'],1)

    def test_old_rank_read_and_paused_read_no_mutation(self):
        self.rank_fixture(9,100);self.create(legacy=True);before=self.state()
        self.assertEqual(self.app.view(self.sid)['sect_development']['level'],5);self.assertEqual(before,self.state())
        self.command('world_pause',{});before=self.state()
        v=self.app.view(self.sid);self.assertEqual(v['sect_development']['level'],5);self.assertEqual(before,self.state())

    def test_garden_grain_no_seed_and_auto_selectable(self):
        self.create();self.assign('garden');bid=self.bid('garden')
        self.assertEqual(jobs.definition(self.r,'grain').building_kind,'garden')
        q=self.request('production_start',{'building_id':bid,'recipe_id':'grain'});receipt=self.app.execute(q);self.assertEqual(receipt,self.app.execute(q))
        self.settle(30000);self.assertEqual(self.state().domains['inventory']['holdings']['grain'],3)
        self.assertNotIn('seed_grain',self.state().domains['inventory']['holdings'])
        self.command('automation_production',{'building_id':bid,'policy':{'enabled':True,'recipe_id':'grain','target':6,'max_consumption':0,'reserves':{}}})
        self.settle(30000);self.assertEqual(self.state().domains['inventory']['holdings']['grain'],6)

    def test_processing_ratios_and_real_finish(self):
        self.create({'wood':9,'ingot':9});self.assign('smelter');bid=self.bid('smelter')
        for key,ingredient in [('spirit_plank','wood'),('refined_iron_ingot','ingot')]:
            d=jobs.definition(self.r,key);self.assertEqual(dict(d.inputs),{ingredient:3});self.assertEqual(dict(d.outputs),{key:1})
            self.command('production_start',{'building_id':bid,'recipe_id':key});self.settle(d.duration_ms)
            self.assertEqual(self.state().domains['inventory']['holdings'][key],1)

    def test_spirit_and_all_pill_opening_gates(self):
        self.rank_fixture();self.create({'herb':1000,'grain':1000,'spirit_iron_ore':1000});self.assign('alchemy');self.assign('mine');self.assign('smelter')
        state=self.state();domains=thaw_json(state.domains)
        for key,minimum in [('spirit_iron_ore',4),('spirit_iron_ingot',4),*[(k,5+i) for i,k in enumerate(settings(self.r)['foundation_cultivation']['pills'])]]:
            kind=jobs.definition(self.r,key).building_kind;bid=self.bid(kind)
            domains['sect']['buildings'][bid]['level']=minimum-1
            with self.assertRaises(ValidationError):self.app.start_candidate(replace(state,domains=domains),bid,key)
            domains['sect']['buildings'][bid]['level']=minimum
            self.app.start_candidate(replace(state,domains=domains),bid,key)
        domains['dungeon']['cleared_floor']=29
        # Seven level-3+ buildings alone cannot satisfy the floor criterion.
        for key in ('spirit_iron_ore','spirit_iron_ingot','pill_1_0'):
            with self.assertRaises(ValidationError):self.app.start_candidate(replace(state,domains=domains),self.bid(jobs.definition(self.r,key).building_kind),key)

    def test_spirit_gather_smelting_and_pill_production_replay(self):
        self.rank_fixture(5,30);self.create({'herb':100,'grain':100,'spirit_iron_ore':100});self.assign('mine');self.assign('smelter');self.assign('alchemy')
        for key in ('spirit_iron_ore','spirit_iron_ingot','pill_1_0'):
            d=jobs.definition(self.r,key);bid=self.bid(d.building_kind);before=self.state();q=self.request('production_start',{'building_id':bid,'recipe_id':key})
            receipt=self.app.execute(q);after=self.state();self.assertEqual(receipt,self.app.execute(q));self.assertEqual(after,self.state())
            self.settle(d.duration_ms);self.assertGreater(self.state().domains['inventory']['holdings'].get(key,0),before.domains['inventory']['holdings'].get(key,0))
        self.assertRejected('production_start',{'building_id':self.bid('alchemy'),'recipe_id':'gu_yuan_pill'})

    def test_foundation_new_battle_snapshot_valid_at_each_stage(self):
        self.create(realm='realm_1')
        for n in (0,2000,4000):
            domains=thaw_json(self.state().domains);domains['cultivation']['progress']=n
            state=replace(self.state(),domains=domains)
            from src.systems.combat import battle
            projected=self.app.player_projection(state)
            part=battle.start(state.domains.get('combat',battle.initial()),self.r,self.sid,f'{self.sid}:1:i:{state.identity["instance_counter"]+1}','thorn_path_v2_001',player_snapshot=projected)
            candidate=replace(state,domains={**state.domains,'combat':part},identity={**state.identity,'instance_counter':state.identity['instance_counter']+1})
            self.app.foundation.validate_state(candidate)

    def test_generated_cost_gain_ratio_and_six_hour_budget(self):
        cfg=settings(self.r)['foundation_cultivation'];base=cfg['pills']['pill_1_0']['gain'];costs=[]
        for i,(key,row) in enumerate(cfg['pills'].items()):
            self.assertEqual(row['gain'],base*2**i);d=jobs.definition(self.r,key)
            self.assertEqual(d.min_level,5+i);self.assertEqual(set(dict(d.inputs)),{'herb','grain','spirit_iron_ore'})
            costs.append(sum(dict(d.inputs).values()))
        self.assertEqual(sorted(costs),costs)
        self.assertLess(costs[-1]/(base*16),costs[0]/base)
        self.assertEqual(cfg['threshold']//base*jobs.definition(self.r,'pill_1_0').duration_ms//settings(self.r)['new_save_production']['alchemy']['workers'],6*3600*1000)

    def test_legacy_120_second_jobs_work_ready_and_complete_remain_valid(self):
        self.rank_fixture(5,30);self.create({'herb':100,'ingot':100});self.assign('alchemy')
        self.command('production_start',{'building_id':self.bid('alchemy'),'recipe_id':'breakthrough_pill'})
        state=self.state();part=thaw_json(state.domains['production']);j=part['jobs'][self.bid('alchemy')]
        j['due_ms']=j['started_ms']+120000
        for status,progress in [('WORKING',0),('OUTPUT_READY',120000000),('COMPLETE',120000000)]:
            j.update(status=status,progress_milli=progress);jobs.validate(part,self.r)
        j.update(status='WORKING',progress_milli=0)
        candidate=replace(state,domains={**state.domains,'production':part})
        self.app.foundation.validate_state(candidate)
        after=self.app.engine.advance(candidate,max_events=32,now_ms=state.time['last_settled_at_ms']+120000)[0]
        self.assertEqual(after.domains['production']['jobs'][self.bid('alchemy')]['status'],'COMPLETE')
        self.assertEqual(after.domains['inventory']['holdings']['breakthrough_pill'],1)
        self.assertEqual(jobs.definition(self.r,'breakthrough_pill').duration_ms,600000)

    def test_legacy_field_grain_job_still_valid(self):
        self.create();s=self.state();part=thaw_json(s.domains);counter=s.identity['instance_counter']+1
        bid=f'{self.sid}:1:i:{counter}';part['sect']['buildings'][bid]={'definition_id':'field','level':1,'construction_target':None}
        part['production']=thaw_json(jobs.start(part['production'],self.r,building_id=bid,recipe_id='grain',job_id=f'{self.sid}:1:i:{counter+1}',event_id=f'{self.sid}:1:e:{s.identity["event_counter"]+1}',sim_ms=s.time['sim_time_ms'],workers=1,yield_milli=1000,work_rate_milli=1000))
        # Historical direct-production saves need not have a Work commitment here.
        ProductionSettlement(self.r).validate_state(replace(s,domains=part,identity={**s.identity,'instance_counter':counter+1,'event_counter':s.identity['event_counter']+1}))

    def test_authenticated_http_pill_replay_read_and_pause(self):
        from pathlib import Path
        from contextlib import contextmanager
        from src.transport.danding import create_app
        from src.rendering.game import present
        from src.rendering.game_runtime import GameRuntimeAssets
        self.rank_fixture();self.create({'pill_1_0':10},realm='realm_1',progress=1990)
        @contextmanager
        def application():yield self.app
        assets=GameRuntimeAssets(self.root/'assets')
        web=create_app(application,self.sid,lambda v:present(v,assets),assets.file,'test-only-sect-foundation-batch-token',secure=False,ui_root=Path('src/ui/pages/game').resolve(),cookie_path='/game/')
        web.config['SESSION_COOKIE_PATH']='/'
        client=web.test_client();client.post('/login',data={'token':'test-only-sect-foundation-batch-token'})
        csrf=client.get('/api/view').json['csrf']
        def post(q):
            body={'protocol_version':1,'save_id':q.save_id,'generation':q.generation,'expected_revision':q.expected_revision,'request_id':q.request_id,'command':{'name':q.name,'version':1,'payload':thaw_json(q.payload)}}
            return client.post('/api/command',json=body,headers={'X-CSRF-Token':csrf,'Origin':'http://localhost'})
        q=self.request('cultivation_use_pill',{'item_id':'pill_1_0','count':2});first=post(q)
        self.assertEqual(first.status_code,200);self.assertEqual(first.json,post(q).json)
        v=client.get('/api/view').json['view'];self.assertEqual(v['cultivation']['progress'],2050);self.assertEqual(v['holdings']['pill_1_0']['quantity'],8)
        self.assertEqual(v['sect_development']['level'],2)
        self.command('world_pause',{});before=self.state()
        self.assertEqual(post(self.request('cultivation_use_pill',{'item_id':'pill_1_0'})).status_code,422)
        self.assertEqual(client.get('/api/view').status_code,200);self.assertEqual(before,self.state())

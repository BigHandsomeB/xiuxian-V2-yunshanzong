"""Only formal manuals, source transactions and growth settlement; isolated SQLite."""
import unittest
from dataclasses import replace
from src.core.state.envelope import thaw_json
from src.core.validation import ValidationError
from src.core.save.sqlite import SQLiteSave
from src.application.ecology import EcologyApplication
from src.application.cultivation import partition
from src.systems.cultivation import techniques,leveling
from src.systems.combat import battle
from tests.systems import test_ecology as fixtures
from tests.systems import test_techniques as prior

class FormalTechniqueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):fixtures.EcologyTests.setUpClass.__func__(cls)
    def setUp(self):fixtures.EcologyTests.setUp(self)
    read=fixtures.EcologyTests.read
    view=fixtures.EcologyTests.view
    fixture=fixtures.EcologyTests.fixture
    request=fixtures.EcologyTests.request
    execute=fixtures.EcologyTests.execute
    command=fixtures.EcologyTests.command
    def grant(self):
        s=self.read();grown=techniques.migrate(partition(s),self.registry)
        if grown!=partition(s):self.fixture(lambda s:replace(s,domains={**s.domains,'cultivation':grown}))
    def row(self,grade):return next(r for r in techniques.config(self.registry)['techniques'] if r['grade']==grade)
    def stock(self,**values):
        def change(s):
            stock=thaw_json(s.domains['inventory']);stock['holdings'].update(values)
            return replace(s,domains={**s.domains,'inventory':stock})
        self.fixture(change)
    def progress(self,floor):
        self.fixture(lambda s:replace(s,domains={**s.domains,'dungeon':{**thaw_json(s.domains['dungeon']),'cleared_floor':floor}}))
    def test_catalog_budgets_and_all_grade_boundaries(self):
        c=techniques.config(self.registry);self.assertEqual(len(c['techniques']),150)
        self.assertEqual(len({r['asset_id'] for r in c['techniques']}),150)
        for r in c['techniques']:
            M=c['grades'][r['grade']];self.assertEqual(techniques.effective_bonus(c,r,1),{k:n//4 for k,n in r['max_bonus'].items()});self.assertEqual(techniques.effective_bonus(c,r,M),r['max_bonus'])
            for L in range(1,M+1):
                self.assertEqual(techniques.level(c,r,techniques.threshold(c,L,r)),L)
                if L>1:self.assertEqual(techniques.level(c,r,techniques.threshold(c,L,r)-1),L-1)
    def test_test_retirement_preserves_old_snapshot_and_pure_read(self):
        s=self.read();p=techniques.grant_test(partition(s),self.registry)
        p['techniques'].pop('formal_version',None)
        q=techniques.migrate(p,self.registry);self.assertEqual(len(q['techniques']['owned']),2);self.assertEqual(techniques.migrate(q,self.registry),q)
        leveling.validate(p,self.registry,self.sid);self.assertGreater(leveling.projection(p,self.registry,self.sid)['max_hp_milli'],leveling.projection(q,self.registry,self.sid)['max_hp_milli'])
        self.assertEqual(self.read(),s);self.assertEqual(len(self.view()['techniques']['instances']),2);self.assertEqual(self.read(),s)
        self.assertEqual(q['current_realm'],p['current_realm']);self.assertEqual(q.get('total_xp',q.get('progress')),p.get('total_xp',p.get('progress')))
    def test_purchase_single_charge_duplicate_owned_and_replay(self):
        self.grant();row=next(r for r in techniques.config(self.registry)['techniques'] if r['grade']=='green');before=self.read();q=self.request('technique_buy',{'technique_id':row['id']})
        receipt=self.execute(q);after=self.read();self.assertEqual(after.domains['inventory']['holdings']['coins'],before.domains['inventory']['holdings']['coins']-1200)
        self.assertEqual(self.execute(q),receipt);self.assertEqual(self.read(),after)
        with self.assertRaises(ValidationError):self.command('technique_buy',{'technique_id':row['id']})
        self.assertEqual(self.read(),after)
    def test_claim_progress_gate_and_once_per_grade(self):
        self.grant();r=self.row('blue');before=self.read()
        with self.assertRaises(ValidationError):self.command('technique_claim',{'technique_id':r['id']})
        self.assertEqual(self.read(),before);self.progress(60);q=self.request('technique_claim',{'technique_id':r['id']});receipt=self.execute(q);after=self.read()
        self.assertEqual(self.execute(q),receipt);self.assertEqual(self.read(),after)
        another=next(row for row in techniques.config(self.registry)['techniques'] if row['grade']=='blue' and row['id']!=r['id'])
        with self.assertRaises(ValidationError):self.command('technique_claim',{'technique_id':another['id']})
        self.assertEqual(self.read(),after);self.command('technique_claim',{'technique_id':self.row('purple')['id']})
    def test_page_exchange_exact_cost_and_rollback(self):
        self.grant();r=self.row('red');before=self.read()
        with self.assertRaises(ValidationError):self.command('technique_exchange',{'technique_id':r['id']})
        self.assertEqual(self.read(),before);self.stock(manual_page=400,spirit_stone_immortal=10);q=self.request('technique_exchange',{'technique_id':r['id']});self.execute(q);after=self.read()
        self.assertEqual(after.domains['inventory']['holdings'].get('manual_page',0),0);self.assertEqual(after.domains['inventory']['holdings'].get('spirit_stone_immortal',0),0);self.execute(q);self.assertEqual(self.read(),after)
        with self.assertRaises(ValidationError):self.command('technique_buy',{'technique_id':self.row('orange')['id']})
        self.assertEqual(self.read(),after)
    def test_no_equipped_gate_low_floor_experience_and_pause(self):
        self.grant()
        for slot in list(partition(self.read())['techniques']['slots']):self.command('technique_unequip',{'slot':slot})
        p=partition(self.read());q,result=leveling.kill(p,self.registry,self.sid,1,'normal','gate');self.assertEqual(result['xp_gained'],0);self.assertEqual(sum(q['techniques']['owned'].values()),0)
        key=techniques.config(self.registry)['starter_ids'][0];self.command('technique_equip',{'slot':'movement','technique_id':key})
        p=thaw_json(partition(self.read()));p.pop('progress',None);p['total_xp']=leveling.table(leveling.config(self.registry))[400]
        q,_=leveling.kill(p,self.registry,self.sid,1,'normal','penalty');self.assertEqual(q['techniques']['owned'][key],10)
        self.command('world_pause',{});before=self.read()
        with self.assertRaises(ValidationError):self.command('technique_buy',{'technique_id':self.row('green')['id']})
        self.assertEqual(self.read(),before)
    def test_boss_page_reward_once_old_drops_preserved(self):
        self.grant();self.progress(99);c=techniques.config(self.registry);names=['逍遥无极身','万劫不坏身','乾坤破界斩','混沌葬仙经','先天一气诀','鸿蒙养气经','混沌归元功','大道长生诀']
        s=self.read();p=thaw_json(partition(s));p.pop('progress',None);p.update(current_realm='realm_1',total_xp=leveling.table(leveling.config(self.registry))[1000],growth_revision=10)
        rows=[next(r for r in c['techniques'] if r['name']==name) for name in names];p['techniques']['owned']={r['id']:techniques.threshold(c,c['grades'][r['grade']],r) for r in rows};p['techniques']['slots']=dict(zip(c['slots'],[r['id'] for r in rows]));p['techniques']['claims']={};p['techniques']['boss_wins']=9
        s=replace(s,domains={**s.domains,'cultivation':p});app=EcologyApplication(None,self.registry,self.clock);counter=s.identity['instance_counter']+1
        fight=battle.start(battle.initial(),self.registry,self.sid,f'{self.sid}:1:i:{counter}','thorn_path_v2_100',player_snapshot=app.player_projection(s),growth_snapshot=p);fight,_,_=battle.result_only(fight,self.registry,self.sid);self.assertEqual(fight['battle']['status'],'PLAYER_WIN')
        original=super(EcologyApplication,app).reward_amounts(fight['battle']);reward=app.reward_amounts(fight['battle']);self.assertEqual({k:n for k,n in reward.items() if k!='manual_page'},original);self.assertEqual(reward['manual_page'],1)
        s=replace(s,identity={**s.identity,'instance_counter':counter},domains={**s.domains,'combat':fight});self.fixture(lambda _:s)
        q=self.request('combat_reward',{'battle_id':fight['battle']['battle_id']});receipt=self.execute(q);after=self.read();self.assertEqual(after.domains['inventory']['holdings']['manual_page'],1);self.assertEqual(after.domains['inventory']['holdings']['spirit_stone_supreme'],1);self.assertEqual(partition(after)['techniques']['boss_wins'],10);self.assertEqual(self.execute(q),receipt);self.assertEqual(self.read(),after)
    def test_64_event_and_result_growth_parity(self):
        a=techniques.migrate(partition(self.read()),self.registry);b=a
        for i in range(64):
            identity=f'formal:{i}';fight=battle.start(battle.initial(),self.registry,self.sid,identity,'thorn_path_v2_001',player_snapshot=leveling.projection(a,self.registry,self.sid),growth_snapshot=a);one=fight
            while one['battle']['status']=='ACTIVE':one=battle.attack(one,self.registry,self.sid,identity)
            compact,_,_=battle.result_only(fight,self.registry,self.sid);self.assertEqual(one['battle']['status'],compact['battle']['status'])
            if one['battle']['status']=='PLAYER_WIN':a,_=leveling.kill(a,self.registry,self.sid,1,'normal',identity)
            if compact['battle']['status']=='PLAYER_WIN':b,_=leveling.kill(b,self.registry,self.sid,1,'normal',identity)
        self.assertEqual(a,b)
    def test_one_hour_battle_production_parity(self):prior.TechniqueTests.test_one_hour_battle_and_auto_production_parity(self)

    def test_stone_sources_and_partial_green_exchange(self):
        self.grant();c=techniques.config(self.registry);key=c['sources']['green_stone_ids'][0];self.stock(spirit_stone_low=60)
        q=self.request('technique_exchange',{'technique_id':key});self.execute(q);s=self.read();self.assertEqual(s.domains['inventory']['holdings'].get('spirit_stone_low',0),0);self.execute(q);self.assertEqual(self.read(),s)
        app=EcologyApplication(None,self.registry,self.clock)
        from src.systems.dungeons import progress
        b={'battle_id':'cold-1','encounter_id':progress.definition(self.registry,'cold_jade_cave').encounters[-1]}
        self.assertEqual(app.stone_reward_quote(s,b).get('spirit_stone_immortal'),5)
        p=thaw_json(partition(s));p['techniques']['stone_first_claimed']=['cold_jade_cave']
        self.assertNotIn('spirit_stone_immortal',app.stone_reward_quote(replace(s,domains={**s.domains,'cultivation':p}),b))
    def test_stone_mining_level_gates_and_real_completion(self):
        from src.systems.resources import jobs
        from src.application.settlement import SettlementRequest
        from uuid import uuid4
        self.grant();bid=next(k for k,r in self.read().domains['sect']['buildings'].items() if r['definition_id']=='mine');self.command('work_assign',{'building_id':bid,'count':1})
        with SQLiteSave(self.path,allowed_root=self.root) as store:
            app=EcologyApplication(store,self.registry,self.clock);s=app.query(self.sid)
            with self.assertRaises(ValidationError):app.start_candidate(s,bid,'sect_spirit_stone_mid')
        for L,rid,recipe in [(3,'spirit_stone_mid','sect_spirit_stone_mid'),(5,'spirit_stone_high','sect_spirit_stone_high')]:
            def grow(s):
                sect=thaw_json(s.domains['sect']);sect['buildings'][bid]['level']=L;return replace(s,domains={**s.domains,'sect':sect})
            self.fixture(grow);self.command('production_start',{'building_id':bid,'recipe_id':recipe});before=self.read();j=before.domains['production']['jobs'][bid];self.clock.advance(j['due_ms']-before.time['sim_time_ms'])
            with SQLiteSave(self.path,allowed_root=self.root) as store:
                app=EcologyApplication(store,self.registry,self.clock);app.settle(SettlementRequest(self.sid,before.generation,before.revision,str(uuid4()),4096));after=app.query(self.sid)
                self.assertGreater(after.domains['inventory']['holdings'].get(rid,0),before.domains['inventory']['holdings'].get(rid,0))

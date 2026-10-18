"""TEST ONLY zero-grant first-stage observation through the actual application.

Manual battles accrue their saved attack interval after each completed fight;
this models game time, never phone interaction time. No automatic battle can
silently exceed the explicit fight/turn limits. Strategies and identities are
fixed before running; a gameplay block is an observation, not a passed goal.
"""
from collections import Counter
from dataclasses import dataclass
import hashlib
from pathlib import Path
import time
from unittest.mock import patch
from uuid import UUID, uuid4

from src.application.danding import initial_slice
from src.application.ecology import EcologyApplication
from src.application.memory import Command
from src.application.settlement import SettlementRequest
from src.application.sect_economy import craft_cost
from src.application.sect import capacity_source
from src.systems.inventory.holdings import stock_size
from src.core.save.sqlite import V2_ROOT
from src.core.state.envelope import thaw_json
from src.core.time.model import Continuation
from src.core.validation import ValidationError
from src.data.content_compatibility import package_evidence
from src.data.registry import DefinitionKey
from src.systems.combat.equipment_effects import interval
from src.systems.cultivation import leveling
from src.systems.sect import market, rules
from tests.fixtures.time import ManualClock

SEEDS = (1, 2, 3)
IDS = tuple(f'00000000-0000-4000-8000-{seed:012d}' for seed in SEEDS)
STRATEGY = 'zero-grant-manual-v1'
STAGES = ('blade','floor10','spring','supply_rotation','floor30','sect2')


class FlowStop(Exception):
    """Expected gameplay/strategy block or an explicit budget boundary."""
    def __init__(self, reason, category='BLOCKED'):
        super().__init__(reason)
        self.reason, self.category = reason, category


@dataclass(frozen=True)
class Limits:
    sim_ms: int = 6*60*60*1000
    requests: int = 3000
    fights: int = 300
    turns: int = 256


def input_fingerprint():
    result = hashlib.sha256()
    for path in sorted((V2_ROOT/'src').rglob('*')):
        if path.is_file() and (path.suffix=='.py' or (path.suffix=='.json' and 'data' in path.parts)):
            result.update(path.relative_to(V2_ROOT).as_posix().encode()+b'\0'+path.read_bytes()+b'\0')
    return result.hexdigest()


def check_test_store(store):
    root = store.path.parent
    if not root.resolve().is_relative_to(V2_ROOT/'tests') or root.resolve()==V2_ROOT/'tests':
        raise ValidationError('dedicated tests SQLite required')


class Flow:
    def __init__(self, store, registry, seed, *, deadline, limits=Limits()):
        check_test_store(store)
        if seed not in SEEDS:
            raise ValidationError('only predeclared first-stage identities allowed')
        self.store, self.registry, self.seed = store, registry, seed
        self.sid, self.clock = IDS[seed-1], ManualClock(1000)
        self.app = EcologyApplication(store,registry,self.clock)
        self.deadline, self.limits = deadline, limits
        self.requests = self.fights = self.turns = self.moves = 0
        self.ledger, self.combats, self.checkpoints, self.water_days = [], [], [], []
        self.errors, self.reserve = [], {'wood':15,'stone':10,'ordinary_wood':10,'ingot':15,'thorn_boar_bone':15,'spirit_stone_low':1}
        self.receipts = []
        self.nodes = {key:{'status':'UNTESTED'} for key in STAGES}
        self.started = time.monotonic()
        self.check()
        with patch('src.core.state.envelope.uuid4',return_value=UUID(self.sid)):
            state = initial_slice(registry,last_settled_at_ms=self.clock.now_ms())
        self.app.create(state)
        self._state = self.app.query(self.sid)
        self.initial = self.state()
        self.minimum_coins = self.stock().get('coins',0)
        self.mark('initial')

    def state(self, *, refresh=False):
        # Immutable observation cache only; execute/settle still validate in the real app.
        if refresh:self._state = self.app.query(self.sid)
        return self._state

    def stock(self):
        return self.state().domains['inventory']['holdings']

    def check(self, *, fight=False):
        if time.monotonic() >= self.deadline:
            raise FlowStop('WALL_BUDGET','TRUNCATED')
        if self.requests >= self.limits.requests:
            raise FlowStop('REQUEST_BUDGET','TRUNCATED')
        if fight and self.fights >= self.limits.fights:
            raise FlowStop('FIGHT_BUDGET','TRUNCATED')

    def record(self, name, before, after, *, payload=None, result=None):
        a,b = before.domains['inventory']['holdings'],after.domains['inventory']['holdings']
        delta = {key:b.get(key,0)-a.get(key,0) for key in a.keys()|b.keys() if b.get(key,0)!=a.get(key,0)}
        if name in ('market_buy','material_sell'):
            rid,n=payload['resource_id'],payload['quantity']
            product=payload['price_milli']*n
            coins=(product+999)//1000 if name=='market_buy' else product//1000
            expected={rid:n if name=='market_buy' else -n,'coins':-coins if name=='market_buy' else coins}
            assert delta==expected, 'trade receipt/stock mismatch'
            if name=='material_sell':
                assert b.get(rid,0)>=self.reserve.get(rid,0), 'sale consumed planned reserve'
        if name=='equipment_craft':
            expected={k:-n for k,n in craft_cost(self.registry,payload['equipment_id']).items()}
            assert delta==expected, 'craft did not charge exact actual cost'
            added=set(after.domains['equipment']['instances'])-set(before.domains['equipment']['instances'])
            assert len(added)==1, 'craft created wrong number of instances'
        if name=='building_upgrade':
            expected={k:-n for k,n in rules.quote_upgrade(before.domains['sect'],self.registry,payload['building_id'])['cost'].items()}
            assert delta==expected, 'upgrade cost disagrees with quote'
        self.minimum_coins = min(self.minimum_coins,b.get('coins',0))
        self.ledger.append({'operation':name,'revision':[before.revision,after.revision],
            'sim_ms':[before.time['sim_time_ms'],after.time['sim_time_ms']],
            'delta':delta,'payload':thaw_json(payload or {}),
            'result':thaw_json(result or {}) if name in ('equipment_craft','building_upgrade','market_buy','material_sell') else {}})

    def command(self, name, payload):
        self.check();before=self.state();self.requests+=1
        q=Command(self.sid,before.generation,before.revision,str(uuid4()),name,payload)
        try:
            receipt=self.app.execute(q)
        except ValidationError as exc:
            assert self.state(refresh=True)==before, 'failed command changed state'
            self.errors.append({'command':name,'payload':payload,'error':str(exc)})
            raise FlowStop(name+': '+str(exc),'STRATEGY_BLOCKED') from exc
        after=self.state(refresh=True);self.record(name,before,after,payload=payload,result=receipt.result)
        if name.startswith('work_'):self.moves+=1
        if name in ('equipment_craft','combat_reward','market_buy','production_start') and len(self.receipts)<3:
            self.receipts.append((q,receipt))
        return receipt

    def advance(self, elapsed):
        self.check()
        if elapsed < 0:raise AssertionError('negative planned time')
        if self.clock.value-1000+elapsed > self.limits.sim_ms:
            raise FlowStop('SIM_BUDGET','TRUNCATED')
        self.clock.advance(elapsed)
        while True:
            self.check();before=self.state();self.requests+=1
            q=SettlementRequest(self.sid,before.generation,before.revision,str(uuid4()),256,
                Continuation.for_state(before) if before.time['pending'] else None)
            self.app.settle(q)
            after=self.state(refresh=True);self.record('settle',before,after)
            if after.time['pending'] is None:return

    def building(self, kind):
        return next(key for key,row in self.state().domains['sect']['buildings'].items() if row['definition_id']==kind)

    def policy(self, kind, recipe, target):
        self.command('automation_production',{'building_id':self.building(kind),'policy':{
            'enabled':True,'recipe_id':recipe,'target':target,'max_consumption':1000,'reserves':{}}})

    def replan(self, rows):
        # Disable future starts; already funded work is completed before unassigning.
        for bid,row in list(self.state().domains['automation']['production'].items()):
            if row['enabled']:
                self.command('automation_production',{'building_id':bid,'policy':{**thaw_json(row),'enabled':False}})
        pending=[j['due_ms'] for j in self.state().domains['production']['jobs'].values() if j['status']=='WORKING']
        if pending:self.advance(max(0,max(pending)-self.state().time['sim_time_ms']))
        if any(j['status'] not in ('COMPLETE',) for j in self.state().domains['production']['jobs'].values()):
            raise FlowStop('FUNDED_OUTPUT_BLOCKED')
        assigned={bid for by_building in self.state().domains['disciples']['assignments'].values() for bid in by_building}
        for bid in sorted(assigned):self.command('work_unassign',{'building_id':bid})
        for kind,count,recipe,target in rows:
            self.command('work_assign',{'building_id':self.building(kind),'count':count})
            self.policy(kind,recipe,target)
        self.advance(0)

    def mark(self, name):
        s=self.state();p=s.domains;gear=p['equipment']
        self.checkpoints.append({'name':name,'sim_ms':s.time['sim_time_ms'],'wall_accepted_ms':s.time['last_settled_at_ms']-1000,
            'requests':self.requests,'moves':self.moves,'fights':self.fights,'stock':thaw_json(p['inventory']['holdings']),
            'level':leveling.level(p['cultivation'],leveling.config(self.registry)),
            'cleared':p['dungeon']['cleared_floor'],'population':sum(g['count'] for g in p['disciples']['groups'].values()),
            'assignments':thaw_json(p['disciples']['assignments']),'supply':thaw_json(p['ecology']['supply']),
            'jobs':thaw_json(p['production']['jobs']),'player':thaw_json(self.app.player_projection(s)),
            'equipment':{k:thaw_json(v) for k,v in gear['instances'].items() if v['equipped']},
            'manuals':thaw_json(p['cultivation'].get('techniques',{})),
            'capacity':{**thaw_json(capacity_source(s,self.registry)),'used':stock_size(p['inventory'],self.registry)}})

    def reached(self, key):
        self.nodes[key]={'status':'REACHED','sim_ms':self.state().time['sim_time_ms']}
        self.mark(key)

    def gear_and_pills(self):
        state=self.state();gear=state.domains['equipment'];best={}
        def score(row):
            d=row['stats'];return d.get('max_hp_milli',0)+10*d.get('armor_milli',0)+4*d.get('attack_milli',0)
        for key,row in gear['instances'].items():
            definition=self.registry.lookup(DefinitionKey('equipment',row['definition_id']))
            slot=definition.slot
            if slot not in best or (score(row),key)>(score(best[slot][1]),best[slot][0]):best[slot]=(key,row)
        for slot,(key,row) in sorted(best.items()):
            if not row['equipped']:self.command('equipment_equip',{'instance_id':key})
        n=self.stock().get('ju_qi_pill',0)
        p=self.state().domains['cultivation']
        if n and leveling.level(p,leveling.config(self.registry))<=100:
            self.command('cultivation_use_pill',{'item_id':'ju_qi_pill','count':n})

    def fight(self, floor):
        self.check(fight=True);self.fights+=1
        self.command('combat_start',{'encounter_id':f'thorn_path_v2_{floor:03d}'})
        b=self.state().domains['combat']['battle'];bid=b['battle_id'];start_player=thaw_json(b['player_snapshot'])
        tick=interval(b['player_snapshot'])
        for _ in range(self.limits.turns):
            b=self.state().domains['combat']['battle']
            if b['status']!='ACTIVE':break
            self.command('combat_attack',{'battle_id':bid});self.turns+=1
        b=self.state().domains['combat']['battle']
        if b['status']=='ACTIVE':raise FlowStop('TURN_BUDGET','TRUNCATED')
        won=b['status']=='PLAYER_WIN'
        self.combats.append({'floor':floor,'id':bid,'won':won,'steps':b['step'],'player':start_player,
                             'level':leveling.level(self.state().domains['cultivation'],leveling.config(self.registry))})
        if won:self.command('combat_reward',{'battle_id':bid})
        # Same interval as the automatic scheduler; jobs continue through real settlement.
        self.advance(b['step']*tick)
        return won

    def push(self, target):
        while self.state().domains['dungeon']['cleared_floor']<target:
            self.gear_and_pills()
            if not self.fight(self.state().domains['dungeon']['cleared_floor']+1):return False
        return True

    def sell_surplus(self, target_coins):
        if self.stock().get('coins',0)>=target_coins:return
        s=self.state();rid='wood';quantity=max(0,self.stock().get(rid,0)-self.reserve[rid])
        if quantity:
            price=market.price(self.registry,self.sid,market.day(s),rid)['sell_price_milli']
            if quantity*price>=1000:
                self.command('material_sell',{'resource_id':rid,'quantity':quantity,'market_day':market.day(s),'price_milli':price})

    def water(self):
        s=self.state();day=market.day(s);offers=market.current_offers(s,self.registry)
        if not any(row['day']==day for row in self.water_days):
            self.water_days.append({'day':day,'water_offered':'spring_water' in offers,'coins':self.stock().get('coins',0)})
        if self.stock().get('spring_water',0)>=8 or 'spring_water' not in offers:return
        price=market.price(self.registry,self.sid,day,'spring_water')['buy_price_milli']
        n=min(8-self.stock().get('spring_water',0),market.stock_remaining(s,self.registry,'spring_water'),self.stock().get('coins',0)*1000//price)
        if n>0:self.command('market_buy',{'resource_id':'spring_water','quantity':n,'market_day':day,'price_milli':price})

    def run(self):
        try:
            self.push(9)
            self.mark('before_preparation')
            if self.state().domains['dungeon']['cleared_floor']<6:
                raise FlowStop('FLOOR6_NOT_REACHED_WITH_OWNED_GEAR')
            for rid,n in self.reserve.items():self.command('material_reserve',{'resource_id':rid,'quantity':n})
            self.replan((('mine',1,'ore',60),('smelter',1,'ingot',15),('quarry',1,'stone',20),
                         ('forest',3,'wood',240),('alchemy',1,'ju_qi_pill',30),('garden',1,'herb',100)))
            for _ in range(80):
                self.sell_surplus(500);self.water();self.gear_and_pills()
                cost=craft_cost(self.registry,'thorn_fang_blade')
                if all(self.stock().get(k,0)>=n for k,n in cost.items()):break
                if not self.fight(6):raise FlowStop('FARM6_DEFEATED')
                self.advance(120000)
            else:raise FlowStop('PREPARATION_ITERATION_BOUND','TRUNCATED')
            if not all(self.stock().get(k,0)>=n for k,n in cost.items()):raise FlowStop('BLADE_RESOURCES')
            receipt=self.command('equipment_craft',{'equipment_id':'thorn_fang_blade'})
            self.command('equipment_equip',{'instance_id':receipt.result['instance_id']})
            self.reached('blade')
            if not self.push(10):raise FlowStop('FLOOR10_DEFEATED_AFTER_PREPARATION')
            self.reached('floor10')
            # Ordinary wood and the first stone are produced, never bought for free.
            self.replan((('forest',3,'sect_ordinary_wood',12),('quarry',1,'stone',20),
                         ('mine',1,'sect_spirit_stone_low',3),('smelter',1,'ingot',15),
                         ('garden',1,'herb',100),('alchemy',1,'ju_qi_pill',30)))
            self.advance(120000)
            self.policy('forest','wood',240)
            for _ in range(40):
                self.sell_surplus(180);quote=self.app.facility_quote(self.state(),'spring')
                if quote['can_build']:break
                self.advance(120000)
            else:raise FlowStop('SPRING_FUNDS_OR_INPUTS')
            self.command('sect_facility_build',{'building_kind':'spring'});self.reached('spring')
            food_rows=(('garden',1,'grow_sect_crop_01',24),('canteen',1,'meal_qingling_rice',32),
                       ('spring',1,'sect_spring_water',60),('forest',3,'wood',240),
                       ('mine',1,'ore',100),('smelter',1,'ingot',30))
            self.replan(food_rows)
            for _ in range(20):
                if self.stock().get('meal_qingling_rice',0)>=24:break
                self.advance(120000)
            else:raise FlowStop('PREFILL24_NOT_REACHED')
            self.command('ecology_supply',{'enabled':True,'target_days':3});self.mark('supply_enabled')
            # Same workers switch away from rice; no second garden or spare workforce.
            medicine_rows=(('garden',1,'herb',30),('alchemy',1,'ju_qi_pill',12),
                           ('canteen',1,'meal_qingling_rice',32),('spring',1,'sect_spring_water',60),
                           ('forest',2,'wood',240),('mine',1,'ore',100),('smelter',1,'ingot',30))
            self.replan(medicine_rows);self.advance(120000);self.mark('medicine_window')
            self.replan(food_rows);self.advance(240000);self.reached('supply_rotation')
            if not self.push(30):raise FlowStop('PROGRESSION_DEFEATED_AFTER_SUPPLY')
            self.reached('floor30')
            for kind in ('garden','alchemy','smelter'):
                while self.state().domains['sect']['buildings'][self.building(kind)]['level']<3:
                    quote=rules.quote_upgrade(self.state().domains['sect'],self.registry,self.building(kind))
                    for _ in range(40):
                        if all(self.stock().get(k,0)>=n for k,n in quote['cost'].items()):break
                        self.sell_surplus(quote['cost']['coins']);self.advance(120000)
                    if not all(self.stock().get(k,0)>=n for k,n in quote['cost'].items()):raise FlowStop('UPGRADE_INPUTS_OR_CASH')
                    self.command('building_upgrade',{'building_id':self.building(kind)})
            self.reached('sect2')
            self.stop={'category':'COMPLETE','reason':'ALL_PLANNED_NODES_REACHED'}
        except FlowStop as stop:
            self.stop={'category':stop.category,'reason':stop.reason}
            next_key=next((key for key in STAGES if self.nodes[key]['status']!='REACHED'),None)
            if next_key:self.nodes[next_key]={'status':stop.category,'reason':stop.reason}
        self.mark('final')
        return self.report()

    def report(self):
        final=self.state(refresh=True);initial_stock=self.initial.domains['inventory']['holdings'];end=final.domains['inventory']['holdings']
        total=Counter()
        for row in self.ledger:total.update(row['delta'])
        assert all(initial_stock.get(k,0)+total[k]==end.get(k,0) for k in initial_stock.keys()|end.keys()|total.keys()), 'stock ledger mismatch'
        for row in self.ledger:
            if row['operation']=='material_sell':
                assert row['payload']['quantity']>=1
        return {'seed':self.seed,'save_id':self.sid,'strategy':STRATEGY,'version':self.registry.content_version,
            'package_fingerprint':package_evidence(self.registry)['fingerprint'],'stop':self.stop,'nodes':self.nodes,
            'requests':self.requests,'fights':self.fights,'turns':self.turns,'moves':self.moves,
            'wall_seconds':round(time.monotonic()-self.started,3),'sim_ms':final.time['sim_time_ms'],
            'clock_requested_ms':self.clock.value-1000,'minimum_coins':self.minimum_coins,
            'coin_income':sum(max(0,row['delta'].get('coins',0)) for row in self.ledger),
            'coin_outgo':sum(max(0,-row['delta'].get('coins',0)) for row in self.ledger),
            'stock_delta':dict(total),'water_days':self.water_days,'checkpoints':self.checkpoints,
            'combats':self.combats,'errors':self.errors,
            'money_operations':[row for row in self.ledger if row['delta'].get('coins') or row['operation']=='equipment_craft']}

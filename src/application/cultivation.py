"""Atomic Inventory/Growth/Receipt orchestration and readonly Growth→Combat input."""
from dataclasses import replace
from src.application.game import GameApplication,GamePersistence
from src.application.danding import SliceRequestError,envelope
from src.application.memory import Command,Receipt
from src.application.work import references
from src.application import sect
from src.systems.resources import jobs
from src.systems.disciples import work
from src.core.save.codec import StoredReceipt
from src.core.state.envelope import freeze_json,thaw_json
from src.core.validation import ValidationError,ConflictError
from src.systems.cultivation import growth,item_effects
from src.data.item_effects import bindings_for
CultivationBlocked=growth.CultivationBlocked
from src.systems.inventory import operations

def partition(state):return state.domains.get('cultivation',growth.initial(state.save_id))
def active(state):
    if state.domains.get('cultivation',{}).get('attribute_trial',{}).get('running'):return True
    return state.domains.get('combat',{}).get('battle',{}).get('status')=='ACTIVE' if state.domains.get('combat',{}).get('battle') else False
def validate_growth(state,registry):
    p=partition(state);growth.validate(p,registry,state.save_id)
    b=state.domains.get('combat',{}).get('battle')
    if b and b.get('player_snapshot'):
        start=growth.realm(registry,growth.START);end=growth.realm(registry,start.next_realm_id)
        possible=[growth.projection({**p,'current_realm':d.machine_id,'progress':0,'growth_revision':max(1,p['growth_revision'])},registry,state.save_id) for d in (start,end)]
        if b['player_snapshot'] not in possible:raise ValidationError('battle snapshot outside registered growth projections')
    return state
class CultivationPersistence(GamePersistence):
    def _validate(self,state):return validate_growth(super()._validate(state),self.registry)
class CultivationApplication(GameApplication):
    def __init__(self,store,registry,clock):
        self.item_use_bindings=bindings_for(registry)
        item_effects.validate_handlers(self.item_use_bindings)
        super().__init__(store,registry,clock)
    def _application(self,specs):
        validators={**sect.validators(self.registry),'production':lambda p:jobs.validate(p,self.registry),'disciples':lambda p:work.validate(p,self.registry)}
        return CultivationPersistence(self.store,self.registry,specs,references=lambda s:references(s,self.registry),validators=validators,settlement_engine=self.engine,clock=self.clock)
    def player_source(self):return "境界基础属性 · 战斗使用开战快照"
    def player_projection(self,state):return growth.projection(partition(state),self.registry,state.save_id)
    def project_cultivation(self,state):return growth.view(partition(state),self.registry,state.save_id,state.domains['inventory']['holdings'],active(state),state.time['pending'] is not None,world_ms=state.time['sim_time_ms'])
    def view(self,save_id):
        state=self.query(save_id)
        return freeze_json({**self.project_view(state),'combat':self.project_combat(state),'cultivation':self.project_cultivation(state)})
    def act(self,save_id,body):
        envelope(save_id,body,'command');c=body['command']
        if type(c) is not dict or set(c)!={'name','version','payload'} or type(c['version']) is not int or c['version']!=1 or type(c['payload']) is not dict:raise SliceRequestError('invalid growth command')
        if c['name'] not in growth.COMMANDS:return super().act(save_id,body)
        try:q=Command(save_id,body['generation'],body['expected_revision'],body['request_id'],c['name'],c['payload'])
        except ValidationError as exc:raise SliceRequestError('invalid growth envelope') from exc
        return self.execute(q)
    def execute(self,q):
        if not isinstance(q,Command):raise ValidationError('Command required')
        if q.name not in growth.COMMANDS:return super().execute(q)
        with self.store.transaction():
            state=self.query(q.save_id)
            if q.generation!=state.generation:raise ConflictError('generation mismatch')
            previous=self.store.receipt(state.save_id,state.generation,q.request_id)
            if previous:
                if previous.kind!='command' or previous.intent!=q.digest() or previous.committed_revision>state.revision:raise ConflictError('request identity conflict')
                return self.foundation._decode_receipt(previous)
            if q.expected_revision!=state.revision or state.time['pending'] is not None:raise ConflictError('stale or pending')
            allowed=({'item_id'},{'item_id','count'}) if q.name=='cultivation_use_pill' else (set(),{'count'}) if q.name=='cultivation_train' else (set(),)
            if q.version!=1 or set(q.payload) not in allowed:raise ValidationError('exact pill count/breakthrough intent required')
            from src.core.time.world import require_running
            require_running(state.time)
            p=partition(state);stock=state.domains['inventory'];before=growth.stats(self.player_projection(state))
            if q.name in ('cultivation_train','cultivation_use_pill'):
                item_id='pill' if q.name=='cultivation_train' else q.payload['item_id']
                effect=item_effects.apply(self.item_use_bindings,q.name,item_id,p,self.registry,state.save_id,stock['holdings'],active(state),count=q.payload.get('count',1),world_ms=state.time['sim_time_ms'])
                new,events,cost=effect.cultivation,effect.events,effect.costs
            else:
                new,events=growth.breakthrough(p,self.registry,state.save_id,stock['holdings'],active(state));cost=dict(growth.realm(self.registry,p['current_realm']).cost)
            inventory,_=operations.consume(stock,self.registry,cost)
            candidate=replace(state,revision=state.revision+1,domains={**state.domains,'cultivation':new,'inventory':inventory})
            self.foundation.validate_state(candidate)
            receipt=Receipt(q.request_id,candidate.revision,{'operation':q.name,'cultivation':self.project_cultivation(candidate),'events':events,'stats_before':before,'stats_after':growth.stats(self.player_projection(candidate))})
            self.store.commit(state,candidate,StoredReceipt(candidate.save_id,candidate.generation,q.request_id,q.digest(),candidate.revision,'command',thaw_json(receipt.result)))
        return receipt

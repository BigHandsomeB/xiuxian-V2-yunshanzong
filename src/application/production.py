"""@module application/production
@purpose Atomic deterministic job start and settlement delivery, using existing authority.
@depends application/persistent,sect,inventory; systems/resources,sect,inventory; Core/Data
@usedBy tests/systems/test_production; future explicitly authorized source coordination
@see ./INDEX.md
"""
from src.core.time.world import require_running
from dataclasses import replace
from src.application import sect, inventory
from src.application.memory import Command, Receipt
from src.application.persistent import PersistentApplication
from src.core.save.codec import StoredReceipt
from src.core.state.envelope import thaw_json
from src.core.time.engine import SettlementEngine
from src.core.time.model import Continuation
from src.core.validation import ValidationError, ConflictError, integer
from src.data.registry import DefinitionKey
from src.systems.inventory import holdings, operations
from src.systems.sect import buildings
from src.systems.resources import jobs


def references(state):
    return sect.references(state)+tuple(DefinitionKey('production',j['recipe_id'])
                                       for j in state.domains['production']['jobs'].values())


def new_state(registry, *, last_settled_at_ms):
    state=sect.new_state(registry,last_settled_at_ms=last_settled_at_ms)
    return replace(state,domains={**state.domains,'production':{'jobs':{}}})


class ProductionSettlement:
    """Application composition, not a second clock or settlement authority.

    Core orders/accrues/consumes events. Delivery uses current building-derived
    capacity. A full batch stays OUTPUT_READY until it fits; no output truncation.
    """
    def __init__(self,registry):
        self.registry=registry
        self.core=SettlementEngine({'production':jobs.simulation(registry)})

    def validate_state(self,state):
        self.core.validate_state(state)
        for building,job in state.domains['production']['jobs'].items():
            row=buildings.get_building(state.domains['sect'],self.registry,building)
            d=jobs.definition(self.registry,job['recipe_id'])
            from src.data.economy.sect_rules import settings
            cfg=settings(self.registry)
            legacy=cfg.get('legacy_production_buildings',{}).get(d.machine_id,()) if cfg else ()
            if row['definition_id'] not in (d.building_kind,*legacy) or row['level']<d.min_level:
                raise ValidationError('job requires an operational matching building')
            for field,marker,counter in [('job_id','i','instance_counter'),('event_id','e','event_counter')]:
                parts=job[field].split(':')
                if len(parts)!=4 or parts[0]!=state.save_id or parts[2]!=marker:
                    raise ValidationError('job identity outside save namespace')
                try:g,n=int(parts[1]),int(parts[3])
                except ValueError as exc:raise ValidationError('invalid job identity') from exc
                if str(g)!=parts[1] or str(n)!=parts[3] or not 1<=g<=state.generation or not 1<=n<=state.identity[counter]:
                    raise ValidationError('job identity outside allocated counters')
                if field=='job_id' and job[field] in state.domains['sect']['buildings']:
                    raise ValidationError('job identity overlaps building instance')
            elapsed=state.time['sim_time_ms']-job['started_ms']
            if elapsed<0 or job['progress_milli']!=min(d.duration_ms*1000,elapsed*job['work_rate_milli']):
                raise ValidationError('job work disagrees with simulation cursor')
        return state

    def advance(self,state,**kwargs):
        candidate,result=self.core.advance(state,**kwargs)
        production=thaw_json(candidate.domains['production'])
        stock=candidate.domains['inventory']
        capacity=sect.capacity_source(candidate,self.registry)['effective']
        for job in sorted(production['jobs'].values(),key=lambda j:(j['due_ms'],j['event_id'])):
            if job['status']!='OUTPUT_READY':continue
            amounts=jobs.outputs(job,self.registry)
            used=holdings.stock_size(stock,self.registry)
            needed=sum(n for key,n in amounts.items() if holdings.definition(self.registry,key).warehouse_counted)
            if needed and used+needed>capacity:continue
            stock,delivery=operations.grant(stock,self.registry,amounts,capacity=capacity)
            if any(delivery['discarded'].values()):raise ValidationError('production cannot discard output')
            job['status']='COMPLETE'
        candidate=replace(candidate,domains={**candidate.domains,'inventory':stock,'production':production})
        if candidate!=state:candidate=replace(candidate,revision=state.revision+1)
        self.validate_state(candidate)
        if result.continuation is not None:result=replace(result,continuation=Continuation.for_state(candidate))
        return candidate,result


class ProductionApplication:
    """Trusted internal source capability; no player grant/start API or automation.

    Workforce and unlock context are trusted external rule inputs. They are not
    a Disciple, unlock or management authority. All receipts use Foundation storage.
    """
    start_commands=('production_start',)

    def __init__(self,store,registry,clock):
        self.store,self.registry,self.clock=store,registry,clock
        if type(self) is ProductionApplication and registry.contains(DefinitionKey('work_sources','initial')):
            raise ValidationError('formal workforce content requires WorkApplication')
        self.engine=self._settlement_engine()
        self.foundation=self._application({})

    def _settlement_engine(self):return ProductionSettlement(self.registry)

    def _prepare_start(self,state,p,*,command_name='production_start'):
        """Legacy Phase10 trusted adapter; formal WorkApplication derives these inputs."""
        if set(p)!={'building_id','recipe_id','workers','worker_power_milli','work_rate_milli','unlock_floor','unlock_realm'}:
            raise ValidationError('exact trusted production intent required')
        for key in ('workers','worker_power_milli','work_rate_milli'):integer(p[key],key,1)
        for key in ('unlock_floor','unlock_realm'):integer(p[key],key)
        return p

    def _start_domains(self,state,production,stock,job_id,p):
        return {**state.domains,'inventory':stock,'production':production}

    def _application(self,commands):
        validators={**sect.validators(self.registry),'production':lambda p:jobs.validate(p,self.registry)}
        return PersistentApplication(self.store,self.registry,commands,references=references,
                                     validators=validators,settlement_engine=self.engine,clock=self.clock)

    def create(self,state):return self.foundation.create(state)
    def query(self,save_id):return self.foundation.query(save_id)
    def checkpoint(self,save_id):return self.foundation.checkpoint(save_id)
    def settle(self,request):return self.foundation.settle(request)
    def query_building(self,save_id,building_id):
        state=self.query(save_id)
        buildings.get_building(state.domains['sect'],self.registry,building_id)
        return jobs.project(state.domains['production'],self.registry,building_id)

    def execute(self,request):
        if not isinstance(request,Command):raise ValidationError('Command required')
        if request.name not in self.start_commands:
            state=self.query(request.save_id)
            capacity=sect.capacity_source(state,self.registry)['effective']
            return self._application(inventory.commands(self.registry,capacity=capacity)).execute(request)
        with self.store.transaction():
            state=self.query(request.save_id)
            if request.generation!=state.generation:raise ConflictError('save generation mismatch')
            previous=self.store.receipt(state.save_id,state.generation,request.request_id)
            if previous is not None:
                if previous.kind!='command' or previous.intent!=request.digest():raise ConflictError('request intent conflict')
                if previous.committed_revision>state.revision:raise ValidationError('receipt ahead of State')
                return self.foundation._decode_receipt(previous)
            require_running(state.time)
            if request.expected_revision!=state.revision or state.time['pending'] is not None:
                raise ConflictError('stale revision or pending settlement')
            if request.version!=1:raise ValidationError('unsupported production command version')
            p=self._prepare_start(state,request.payload,command_name=request.name)
            row=buildings.get_building(state.domains['sect'],self.registry,p['building_id'])
            d=jobs.definition(self.registry,p['recipe_id'])
            if (row['definition_id']!=d.building_kind or row['level']<d.min_level or
                p['unlock_floor']<d.unlock_floor or p['unlock_realm']<d.unlock_realm):
                raise ValidationError('production building/capability/unlock requirement not met')
            stock,_=operations.consume(state.domains['inventory'],self.registry,
                                      {key:n*p['workers'] for key,n in d.inputs})
            counters={**state.identity,'instance_counter':state.identity['instance_counter']+1,
                      'event_counter':state.identity['event_counter']+1}
            job_id=f"{state.save_id}:{state.generation}:i:{counters['instance_counter']}"
            event_id=f"{state.save_id}:{state.generation}:e:{counters['event_counter']}"
            effective_yield=jobs.yield_for_level(p['worker_power_milli'],row['level'])
            production=jobs.start(state.domains['production'],self.registry,building_id=p['building_id'],
                        recipe_id=p['recipe_id'],job_id=job_id,event_id=event_id,sim_ms=state.time['sim_time_ms'],
                        workers=p['workers'],yield_milli=effective_yield,work_rate_milli=p['work_rate_milli'])
            candidate=replace(state,domains=self._start_domains(state,production,stock,job_id,p),
                              identity=counters,revision=state.revision+1)
            self.foundation.validate_state(candidate)
            receipt=Receipt(request.request_id,candidate.revision,{'job_id':job_id,'status':'WORKING'})
            record=StoredReceipt(candidate.save_id,candidate.generation,request.request_id,request.digest(),
                                 candidate.revision,'command',thaw_json(receipt.result))
            self.store.commit(state,candidate,record)
        return receipt

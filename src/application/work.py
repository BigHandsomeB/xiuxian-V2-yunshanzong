"""@module application/work
@purpose Formal cohort-to-Production composition with one Assignment/commitment authority.
@depends application/production,persistent; systems/disciples,sect; Core/Data
@usedBy tests/systems/test_work; future explicitly authorized application
@see ./INDEX.md
"""
from dataclasses import replace
from src.application.production import ProductionApplication,ProductionSettlement,references as production_references,new_state as production_state
from src.application.persistent import PersistentApplication
from src.application.memory import Command,CommandSpec
from src.application import sect
from src.core.state.envelope import thaw_json,freeze_json
from src.core.time.model import Continuation
from src.core.validation import ValidationError,ConflictError,integer,text
from src.data.registry import DefinitionKey
from src.systems.disciples import work
from src.systems.sect import buildings
from src.systems.resources import jobs


def references(state,registry):
    # Reject malformed owned shapes before iterating their reference fields.
    if not {'disciples','production'}<=state.domains.keys():raise ValidationError('Work partitions required')
    work.validate(state.domains['disciples'],registry)
    jobs.validate(state.domains['production'],registry)
    return production_references(state)+tuple(DefinitionKey('work_groups',row['definition_id'])
                                               for row in state.domains['disciples']['groups'].values())


def new_state(registry,*,last_settled_at_ms):
    state=production_state(registry,last_settled_at_ms=last_settled_at_ms)
    partition,counter=work.initial(registry,state.save_id,state.generation,state.identity['instance_counter'])
    return replace(state,domains={**state.domains,'disciples':partition},
                   identity={**state.identity,'instance_counter':counter})


class WorkSettlement:
    """Compose work release with production event, never a second time algorithm."""
    def __init__(self,registry):
        self.registry=registry;self.production=ProductionSettlement(registry)

    def validate_state(self,state):
        self.production.validate_state(state)
        partition=state.domains['disciples'];work.validate(partition,self.registry)
        reserved=partition['commitments'];active={}
        occupied_ids=set(state.domains['sect']['buildings'])
        occupied_ids.update(j['job_id'] for j in state.domains['production']['jobs'].values())
        for group in partition['groups']:
            owner=buildings.instance_id(group)
            _,generation,_,counter=group.split(':')
            if owner!=state.save_id or int(generation)>state.generation or int(counter)>state.identity['instance_counter'] or group in occupied_ids:
                raise ValidationError('worker cohort identity outside allocated save namespace')
        targets=set()
        for group in partition['groups']:
            targets.update(work.allocations(partition,group))
        for target in targets:
            capacity=buildings.work_slots(state.domains['sect'],self.registry,target)
            occupied=sum(work.allocations(partition,g).get(target,0) for g in partition['groups'])
            if capacity==0 or occupied>capacity:raise ValidationError('invalid/inactive building or exceeded work slots')
        for bid,recipes in partition.get('recipe_assignments',{}).items():
            row=buildings.get_building(state.domains['sect'],self.registry,bid)
            if any(jobs.definition(self.registry,rid).building_kind!=row['definition_id'] for rid in recipes):raise ValidationError('recipe assignment target mismatch')
        for building,job in state.domains['production']['jobs'].items():
            if job['status']=='WORKING':active[job['job_id']]=(building,job)
        if set(reserved)!=set(active):raise ValidationError('working jobs require exactly matching labor commitments')
        for job_id,c in reserved.items():
            building,job=active[job_id]
            if c['building_id']!=building or sum(c['workers'].values())!=job['workers'] or ('recipe_id' in c and c['recipe_id']!=job['recipe_id']):
                raise ValidationError('job and work commitment disagree')
        return state

    def advance(self,state,**kwargs):
        self.validate_state(state)
        candidate,result=self.production.advance(state,**kwargs)
        active={j['job_id'] for j in candidate.domains['production']['jobs'].values() if j['status']=='WORKING'}
        partition=work.release_finished(candidate.domains['disciples'],self.registry,active)
        candidate=replace(candidate,domains={**candidate.domains,'disciples':partition})
        if candidate!=state:candidate=replace(candidate,revision=state.revision+1)
        self.validate_state(candidate)
        if result.continuation is not None:result=replace(result,continuation=Continuation.for_state(candidate))
        return candidate,result


def commands(registry):
    def transition(name):
        def apply(partition,p):
            fields={'worker_id','building_id','count'} if name=='work_assign' else {'worker_id','building_id'} if name=='work_unassign' else {'worker_id','from_building_id','to_building_id'}
            if set(p)!=fields:raise ValidationError('exact work intent required')
            if name=='work_assign':candidate=work.assign(partition,registry,p['worker_id'],p['building_id'],p['count'])
            elif name=='work_unassign':candidate=work.unassign(partition,registry,p['worker_id'],p['building_id'])
            else:candidate=work.reassign(partition,registry,p['worker_id'],p['from_building_id'],p['to_building_id'])
            partition.clear();partition.update(thaw_json(candidate))
            return {'operation':name,'worker_id':p['worker_id']}
        return apply
    return {name:CommandSpec('disciples',transition(name)) for name in ('work_assign','work_unassign','work_reassign')}


class WorkApplication(ProductionApplication):
    """Formal entry: work amounts are projected under the same start transaction.

    No public roster mutation/recruitment or management scheduler. New-state census
    comes from real V1 initial groups; future Disciple lifecycle extends this owner.
    """
    def __init__(self,store,registry,clock):
        if type(self) is WorkApplication and registry.contains(DefinitionKey('alchemy','recipes')):
            raise ValidationError('alchemy content requires AlchemyApplication coordination')
        super().__init__(store,registry,clock)

    def _settlement_engine(self):return WorkSettlement(self.registry)

    def _application(self,specs):
        validators={**sect.validators(self.registry),'production':lambda p:jobs.validate(p,self.registry),
                    'disciples':lambda p:work.validate(p,self.registry)}
        return PersistentApplication(self.store,self.registry,specs,references=lambda s:references(s,self.registry),validators=validators,
                                     settlement_engine=self.engine,clock=self.clock)

    def _prepare_start(self,state,p,*,command_name='production_start'):
        if set(p)!={'building_id','recipe_id','unlock_floor','unlock_realm'}:
            raise ValidationError('formal Production does not accept external worker power/count/rate')
        for key in ('building_id','recipe_id'):text(p[key],key)
        for key in ('unlock_floor','unlock_realm'):integer(p[key],key)
        cap=work.capability(state.domains['disciples'],self.registry,p['building_id'],p.get('recipe_id'))
        if cap['workers']==0:raise ValidationError('Production requires assigned workforce')
        return {**p,**cap}

    def _start_domains(self,state,production,stock,job_id,p):
        domains=super()._start_domains(state,production,stock,job_id,p)
        domains['disciples']=work.commit_job(state.domains['disciples'],self.registry,job_id,p['building_id'],p.get('recipe_id'))
        return domains

    def execute(self,request):
        if not isinstance(request,Command):raise ValidationError('Command required')
        if request.name in ('work_assign','work_unassign','work_reassign'):
            return self._application(commands(self.registry)).execute(request)
        return super().execute(request)

    def query_work(self,save_id,building_id):
        state=self.query(save_id)
        capacity=buildings.work_slots(state.domains['sect'],self.registry,building_id)
        return freeze_json({**work.project(state.domains['disciples'],self.registry,building_id),'slot_capacity':capacity})

    def query_capability(self,save_id,building_id):
        state=self.query(save_id);buildings.get_building(state.domains['sect'],self.registry,building_id)
        return work.capability(state.domains['disciples'],self.registry,building_id)

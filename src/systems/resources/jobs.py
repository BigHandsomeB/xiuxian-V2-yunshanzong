"""@module systems/resources/jobs
@purpose Deterministic production job facts, progress, events and read-only projection.
@depends Core state/time/validation, Data recipes; no other Domain or persistence
@usedBy application/production, tests/systems/test_production
@see ./INDEX.md
"""
from collections.abc import Mapping
from src.core.state.envelope import freeze_json
from src.core.time.model import Event,SimulationDomain
from src.core.validation import ValidationError,ConflictError,integer
from src.data.registry import DefinitionKey
from src.data.recipes.production import ProductionDefinition

FIELDS={'job_id','event_id','recipe_id','status','started_ms','due_ms','workers','yield_milli','work_rate_milli','progress_milli'}


def definition(registry,key):
    value=registry.lookup(DefinitionKey('production',key))
    if not isinstance(value,ProductionDefinition):raise ValidationError('production definition required')
    from src.data.economy.sect_rules import settings
    from dataclasses import replace
    cfg=settings(registry)
    kind=cfg.get('production_building_overrides',{}).get(key) if cfg else None
    if kind:value=replace(value,building_kind=kind,references=(DefinitionKey('buildings',kind),*value.references[1:]))
    return value


def duration(job,registry):
    """Accept only declared historical deadlines, without rewriting persisted jobs."""
    d=definition(registry,job['recipe_id'])
    from src.data.economy.sect_rules import settings
    cfg=settings(registry)
    candidates=cfg.get('legacy_job_duration_ms',{}).get(d.machine_id,()) if cfg else ()
    for milliseconds in candidates:
        if job['due_ms']==job['started_ms']+(milliseconds*1000+job['work_rate_milli']-1)//job['work_rate_milli']:
            return milliseconds
    return d.duration_ms


def validate(partition,registry):
    if not isinstance(partition,Mapping) or set(partition)!={'jobs'} or not isinstance(partition['jobs'],Mapping):
        raise ValidationError('production requires jobs object keyed by building instance')
    seen=set()
    for building,job in partition['jobs'].items():
        if type(building) is not str or not isinstance(job,Mapping) or set(job)!=FIELDS:raise ValidationError('invalid job fields')
        d=definition(registry,job['recipe_id'])
        if job['status'] not in ('WORKING','OUTPUT_READY','COMPLETE'):raise ValidationError('invalid production status')
        for name in ('started_ms','due_ms','progress_milli'):integer(job[name],name)
        for name in ('workers','yield_milli','work_rate_milli'):integer(job[name],name,1)
        total=duration(job,registry)*1000
        if job['due_ms']!=job['started_ms']+(total+job['work_rate_milli']-1)//job['work_rate_milli']:
            raise ValidationError('inconsistent work deadline')
        if job['progress_milli']>total or (job['status']!='WORKING' and job['progress_milli']!=total):raise ValidationError('invalid job progress')
        for name in ('job_id','event_id'):
            if type(job[name]) is not str or job[name] in seen:raise ValidationError('job/event identity invalid or reused')
            seen.add(job[name])
    return partition


def start(partition,registry,*,building_id,recipe_id,job_id,event_id,sim_ms,workers,yield_milli,work_rate_milli):
    validate(partition,registry);d=definition(registry,recipe_id)
    for name,value in [('workers',workers),('yield_milli',yield_milli),('work_rate_milli',work_rate_milli)]:integer(value,name,1)
    integer(sim_ms,'simulation start')
    if building_id in partition['jobs'] and partition['jobs'][building_id]['status']!='COMPLETE':raise ConflictError('building already has unfinished job')
    job=dict(job_id=job_id,event_id=event_id,recipe_id=recipe_id,status='WORKING',started_ms=sim_ms,
             due_ms=sim_ms+(d.duration_ms*1000+work_rate_milli-1)//work_rate_milli,workers=workers,
             yield_milli=yield_milli,work_rate_milli=work_rate_milli,progress_milli=0)
    result={'jobs':{**partition['jobs'],building_id:job}};validate(result,registry);return freeze_json(result)


def yield_for_level(worker_power_milli,level):
    """Existing deterministic production yield rule shared with admission/query."""
    integer(worker_power_milli,'worker power',1);integer(level,'completed level',1)
    return worker_power_milli*(1000+50*(level-1))//1000


def outputs(job,registry):
    return {key:max(1,amount*job['yield_milli']//1000) for key,amount in definition(registry,job['recipe_id']).outputs}


def simulation(registry):
    def events(partition):
        return tuple(Event(job['event_id'],'production',job['due_ms'],0,{'building_id':building})
                     for building,job in partition['jobs'].items() if job['status']=='WORKING')
    def accrue(partition,start,end):
        for job in partition['jobs'].values():
            if job['status']=='WORKING':job['progress_milli']=min(duration(job,registry)*1000,
                                              job['progress_milli']+(end-start)*job['work_rate_milli'])
    def apply(partition,event):
        job=partition['jobs'][event.payload['building_id']]
        if job['event_id']!=event.event_id:raise ValidationError('event job mismatch')
        job['status']='OUTPUT_READY'
    return SimulationDomain(events,apply,accrue,lambda p:validate(p,registry))


def project(partition,registry,building_id):
    validate(partition,registry);job=partition['jobs'].get(building_id)
    if job is None:return freeze_json({'state':'IDLE'})
    total=duration(job,registry)*1000
    status='BLOCKED' if job['status']=='OUTPUT_READY' else 'COMPLETE' if job['status']=='COMPLETE' else 'FINISHING' if job['progress_milli']*10>=total*9 else 'WORKING'
    return freeze_json({'state':status,'job_id':job['job_id'],'progress_milli':job['progress_milli'],'total_work_milli':total})

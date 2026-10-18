"""Artifact ownership, training and crafting events on the shared simulation clock."""
from collections.abc import Mapping
from dataclasses import replace
from src.core.state.envelope import thaw_json
from src.core.time.model import Event, SimulationDomain
from src.core.validation import ValidationError, integer
from src.data.artifacts.definitions import definition, settings

DOMAIN = 'artifacts'
COMMANDS = ('artifact_craft', 'artifact_equip', 'artifact_unequip', 'artifact_feed', 'artifact_enhance')


def initial():
    return {'owned': {}, 'equipped': None, 'job': None}


def partition(state):
    return state.domains.get(DOMAIN, initial())


def threshold(registry, level):
    return settings(registry)['growth']['xp_step'] * level * (level-1) // 2


def level(registry, xp):
    return max(n for n in range(1, settings(registry)['growth']['max_level']+1) if threshold(registry, n) <= xp)


def validate(part, registry):
    if not isinstance(part, Mapping) or set(part) != {'owned', 'equipped', 'job'} or not isinstance(part['owned'], Mapping):
        raise ValidationError('invalid artifact state')
    cfg=settings(registry)
    if not cfg:raise ValidationError('法宝尚未开放')
    for key, row in part['owned'].items():
        definition(registry,key)
        if not isinstance(row, Mapping) or set(row) != {'xp','enhancement'}:raise ValidationError('invalid artifact ownership')
        integer(row['xp'],'artifact XP');integer(row['enhancement'],'artifact enhancement')
        if row['xp'] > threshold(registry,cfg['growth']['max_level']) or row['enhancement'] > cfg['enhancement']['max_level']:
            raise ValidationError('artifact training exceeds cap')
    if part['equipped'] is not None and (not isinstance(part['equipped'],str) or part['equipped'] not in part['owned']):raise ValidationError('法宝尚未拥有')
    job=part['job']
    if job is not None:
        if not isinstance(job,Mapping) or set(job) != {'artifact_id','event_id','started_ms','due_ms'}:raise ValidationError('invalid artifact crafting job')
        row=definition(registry,job['artifact_id'])
        integer(job['started_ms'],'artifact start');integer(job['due_ms'],'artifact due')
        if not isinstance(job['event_id'],str) or job['due_ms']-job['started_ms'] != row['duration_ms'] or job['artifact_id'] in part['owned']:raise ValidationError('invalid artifact crafting duration/identity')
    return part


def stats(registry, identity, enhancement):
    row=definition(registry,identity)
    multiplier=10000+enhancement*settings(registry)['enhancement']['bonus_bps']
    return {key:n*multiplier//10000 for key,n in row['base_stats'].items()}


def snapshot(state, registry):
    part=partition(state);key=part['equipped']
    if not key:return None
    owned=part['owned'][key]
    return {'artifact_id':key,'level':level(registry,owned['xp']),'enhancement':owned['enhancement']}


def validate_snapshot(value, registry):
    if not isinstance(value,Mapping) or set(value) != {'artifact_id','level','enhancement'}:raise ValidationError('invalid artifact snapshot')
    definition(registry,value['artifact_id']);cfg=settings(registry)
    integer(value['level'],'artifact level',1);integer(value['enhancement'],'artifact enhancement')
    if value['level'] > cfg['growth']['max_level'] or value['enhancement'] > cfg['enhancement']['max_level']:raise ValidationError('invalid artifact snapshot level')
    return value


def project(actor, registry, value):
    if value is None:return actor
    validate_snapshot(value,registry)
    result=dict(actor)
    for key,n in stats(registry,value['artifact_id'],value['enhancement']).items():result[key]=result.get(key,0)+n
    return result


def award(state, registry, battle, tier):
    value=battle.get('artifact_snapshot')
    if not value or not settings(registry):return state
    part=thaw_json(partition(state));key=value['artifact_id']
    if part['equipped'] != key or key not in part['owned']:raise ValidationError('battle artifact ownership changed')
    row=part['owned'][key];row['xp']=min(threshold(registry,settings(registry)['growth']['max_level']),row['xp']+settings(registry)['growth']['kill_xp'][tier])
    return replace(state,domains={**state.domains,DOMAIN:part})


def simulation(registry):
    def events(part):
        job=part['job']
        return (Event(job['event_id'],DOMAIN,job['due_ms'],2,{'artifact_id':job['artifact_id']}),) if job else ()
    def apply(part,event):
        key=part['job']['artifact_id'];part['owned'][key]={'xp':0,'enhancement':0};part['job']=None
    return SimulationDomain(events,apply,None,lambda part:validate(part,registry))

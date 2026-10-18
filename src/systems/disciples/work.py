"""@module systems/disciples/work
@purpose Real cohort identity/count source, single allocation/commitment authority.
@depends Core state/validation, Data work definitions; no Production or Building import
@usedBy application/work, tests/systems/test_work
@see ./INDEX.md
"""
from src.core.state.projection import checked_partition
from collections.abc import Mapping
from src.core.state.envelope import freeze_json,thaw_json
from src.core.validation import ValidationError,ConflictError,NotFoundError,integer,text
from src.data.registry import DefinitionKey
from src.data.disciples.work import WorkGroupDefinition,initial_sources


def group_definition(registry,key):
    result=registry.lookup(DefinitionKey('work_groups',key))
    if not isinstance(result,WorkGroupDefinition):raise ValidationError('work group definition required')
    return result


def initial(registry,save_id,generation,counter):
    groups={}
    for key in initial_sources(registry):
        counter+=1;d=group_definition(registry,key)
        groups[f'{save_id}:{generation}:i:{counter}']={'definition_id':key,'count':d.initial_count}
    return freeze_json({'groups':groups,'assignments':{},'commitments':{}}),counter


def allocations(partition,group_id):
    """Per-target max(configured,committed), never duplicate shared workers."""
    claims=dict(partition['assignments'].get(group_id,{}));held={}
    for c in partition['commitments'].values():
        n=c['workers'].get(group_id,0);target=c['building_id']
        held[target]=held.get(target,0)+n
    for target,n in held.items():claims[target]=max(claims.get(target,0),n)
    return claims


@checked_partition
def validate(partition,registry):
    if not isinstance(partition,Mapping) or set(partition)!={'groups','assignments','commitments'}:
        raise ValidationError('work requires groups/assignments/commitments')
    if any(not isinstance(partition[k],Mapping) for k in partition):raise ValidationError('work partitions must be objects')
    for group,row in partition['groups'].items():
        if type(group) is not str or not isinstance(row,Mapping) or set(row)!={'definition_id','count'}:
            raise ValidationError('invalid work source')
        group_definition(registry,row['definition_id']);integer(row['count'],'cohort count',1)
    def workers(rows):
        if not isinstance(rows,Mapping) or not rows:raise ValidationError('empty/non-object worker allocation')
        for group,n in rows.items():
            if group not in partition['groups']:raise NotFoundError('unknown worker cohort')
            integer(n,'assigned count',1)
    for group,targets in partition['assignments'].items():
        if group not in partition['groups']:raise NotFoundError('unknown worker cohort')
        if not isinstance(targets,Mapping) or not targets:raise ValidationError('noncanonical empty assignment')
        for target,n in targets.items():
            if type(target) is not str:raise ValidationError('assignment building reference required')
            integer(n,'assigned count',1)
    for job,c in partition['commitments'].items():
        if type(job) is not str or not isinstance(c,Mapping) or set(c)!={'building_id','workers'} or type(c['building_id']) is not str:
            raise ValidationError('invalid work commitment')
        workers(c['workers'])
    for group,row in partition['groups'].items():
        if sum(allocations(partition,group).values())>row['count']:raise ConflictError('worker already allocated or held')
    return partition


def _group(partition,group_id):
    text(group_id,'worker_id')
    if group_id not in partition['groups']:raise NotFoundError('unknown worker cohort')


def assign(partition,registry,group_id,building_id,count):
    validate(partition,registry);_group(partition,group_id);text(building_id,'building_id');integer(count,'assigned count',1)
    if building_id in partition['assignments'].get(group_id,{}):raise ConflictError('duplicate formal assignment')
    result=thaw_json(partition);result['assignments'].setdefault(group_id,{})[building_id]=count
    validate(result,registry);return freeze_json(result)


def unassign(partition,registry,group_id,building_id):
    validate(partition,registry);_group(partition,group_id);text(building_id,'building_id')
    if building_id not in partition['assignments'].get(group_id,{}):raise NotFoundError('assignment not found')
    result=thaw_json(partition);del result['assignments'][group_id][building_id]
    if not result['assignments'][group_id]:del result['assignments'][group_id]
    # Existing job commitments remain authoritative until explicit settlement.
    validate(result,registry);return freeze_json(result)


def assign_shared(partition,registry,building_id,count):
    """Allocate idle people across saved cohorts without a permanent profession."""
    validate(partition,registry);text(building_id,'building_id');integer(count,'assigned count',1)
    result=thaw_json(partition);remaining=count
    for group,row in sorted(partition['groups'].items()):
        free=row['count']-sum(allocations(partition,group).values())
        take=min(free,remaining)
        if take:
            targets=result['assignments'].setdefault(group,{})
            targets[building_id]=allocations(partition,group).get(building_id,0)+take
            remaining-=take
        if not remaining:break
    if remaining:raise ConflictError('未分配弟子数量不足')
    validate(result,registry);return freeze_json(result)


def unassign_shared(partition,registry,building_id):
    """Remove future assignments, preserving active job commitments."""
    validate(partition,registry);text(building_id,'building_id');result=partition;found=False
    for group,targets in partition['assignments'].items():
        if building_id in targets:
            result=unassign(result,registry,group,building_id);found=True
    if not found:raise NotFoundError('当前岗位没有已分配弟子')
    return result


def reassign(partition,registry,group_id,from_building,to_building):
    validate(partition,registry);_group(partition,group_id);text(from_building,'from_building_id');text(to_building,'to_building_id')
    if from_building==to_building:raise ConflictError('reassign requires another target')
    targets=partition['assignments'].get(group_id,{})
    if from_building not in targets:raise NotFoundError('assignment not found')
    if to_building in targets:raise ConflictError('duplicate destination assignment')
    if any(c['building_id']==from_building and c['workers'].get(group_id,0) for c in partition['commitments'].values()):
        raise ConflictError('committed worker cannot be reassigned yet')
    result=thaw_json(partition);n=result['assignments'][group_id].pop(from_building)
    result['assignments'][group_id][to_building]=n;validate(result,registry);return freeze_json(result)


def capability(partition,registry,building_id):
    validate(partition,registry)
    assigned={g:targets[building_id] for g,targets in partition['assignments'].items() if building_id in targets}
    count=sum(assigned.values())
    return freeze_json({'workers':count,'worker_power_milli':count*1000,'work_rate_milli':1000})


def commit_job(partition,registry,job_id,building_id):
    validate(partition,registry)
    if job_id in partition['commitments'] or any(c['building_id']==building_id for c in partition['commitments'].values()):raise ConflictError('duplicate work commitment')
    workers={g:targets[building_id] for g,targets in partition['assignments'].items() if building_id in targets}
    if not workers:raise ValidationError('no assigned workforce')
    result=thaw_json(partition);result['commitments'][job_id]={'building_id':building_id,'workers':workers}
    validate(result,registry);return freeze_json(result)


def release_finished(partition,registry,working_job_ids):
    validate(partition,registry);result=thaw_json(partition)
    result['commitments']={job:c for job,c in result['commitments'].items() if job in working_job_ids}
    validate(result,registry);return freeze_json(result)


def project(partition,registry,building_id):
    cap=capability(partition,registry,building_id)
    working=sum(sum(c['workers'].values()) for c in partition['commitments'].values() if c['building_id']==building_id)
    occupied=sum(allocations(partition,g).get(building_id,0) for g in partition['groups'])
    return freeze_json({'assigned_count':cap['workers'],'working_count':working,'occupied_count':occupied})

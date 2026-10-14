"""@module systems/alchemy/recipes
@purpose Alchemy membership, requirements and pure job read model over Production facts.
@depends Data/registry, Core/state/validation, systems/resources/jobs (read-only)
@usedBy application/alchemy, tests/systems/test_alchemy
@see ./INDEX.md
"""
from src.core.state.envelope import freeze_json
from src.core.validation import NotFoundError,ValidationError,integer
from src.data.registry import DefinitionKey
from src.systems.resources import jobs


def recipe_ids(registry):
    refs=registry.lookup(DefinitionKey('alchemy','recipes')).references
    extra=DefinitionKey('alchemy','additional_recipes')
    if registry.contains(extra):refs+=registry.lookup(extra).references
    return tuple(ref.machine_id for ref in refs)


def definition(registry,recipe_id):
    key=DefinitionKey('production',recipe_id)
    if recipe_id not in recipe_ids(registry):raise NotFoundError('unknown alchemy recipe')
    d=jobs.definition(registry,recipe_id)
    if d.building_kind!='alchemy':raise ValidationError('alchemy recipe requires 丹鼎阁')
    return d


def requirements(registry,recipe_id):
    d=definition(registry,recipe_id)
    return freeze_json({'recipe_id':d.machine_id,'display_name_zh':d.display_name,
                        'required_building_type':d.building_kind,'required_building_level':d.min_level,
                        'inputs_per_worker':dict(d.inputs),'outputs_per_base_worker':dict(d.outputs),
                        'duration_ms':d.duration_ms,'minimum_assigned_workers':1,
                        'unlock_floor':d.unlock_floor,'unlock_realm':d.unlock_realm})


def project_job(partition,registry,building_id,sim_ms):
    integer(sim_ms,'simulation cursor');jobs.validate(partition,registry)
    job=partition['jobs'].get(building_id)
    if job is None:return freeze_json({'status':'IDLE','job':None,'remaining_ms':0,'expected_outputs':{},'blocking_reason':None})
    definition(registry,job['recipe_id'])
    if sim_ms<job['started_ms']:raise ValidationError('alchemy job ahead of simulation cursor')
    return freeze_json({'status':job['status'],'job':job,'remaining_ms':max(0,job['due_ms']-sim_ms),
                        'expected_outputs':jobs.outputs(job,registry),
                        'blocking_reason':'INVENTORY_CAPACITY' if job['status']=='OUTPUT_READY' else None})

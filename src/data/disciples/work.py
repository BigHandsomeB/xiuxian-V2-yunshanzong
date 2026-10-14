"""@module data/disciples/work
@purpose Minimal real cohort source and building work rules in one existing Registry.
@depends data/registry,recipes/production,buildings/work,core/validation
@usedBy systems/disciples/work,application/work
@see ./INDEX.md
"""
from dataclasses import dataclass
import json
from pathlib import Path
from src.core.validation import ValidationError,DuplicateError,integer,schema_version
from src.data.registry import Definition,DefinitionKey,_fields
from src.data.buildings.work import BuildingWorkDefinition
from src.data.recipes.production import load_production

@dataclass(frozen=True,slots=True)
class WorkGroupDefinition(Definition):
    initial_count: int = 1
    def __post_init__(self):
        super(WorkGroupDefinition,self).__post_init__()
        if self.domain!='work_groups' or self.references:raise ValidationError('work source definition required')
        integer(self.initial_count,'initial_count',1)


def load_work(source=None, *, seal=True):
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise DuplicateError('duplicate work JSON key')
            result[key]=value
        return result
    try:p=json.loads(source if source is not None else Path(__file__).with_name('work.json').read_text(),object_pairs_hook=unique)
    except (TypeError,json.JSONDecodeError) as exc:raise ValidationError('invalid work JSON') from exc
    _fields(p,('schema_version','content_version','groups','building_work'));schema_version(p['schema_version'],'work schema')
    if type(p['groups']) is not list or not p['groups'] or type(p['building_work']) is not list:raise ValidationError('work definitions require arrays')
    production=json.loads(Path(__file__).parents[1].joinpath('recipes/production.json').read_text())
    production['content_version']=p['content_version'];registry=load_production(json.dumps(production),seal=False)
    for row in p['groups']:
        _fields(row,('machine_id','display_name','initial_count'))
        registry.register(WorkGroupDefinition('work_groups',row['machine_id'],row['display_name'],(),row['initial_count']))
    registry.register(Definition('work_sources','initial','初始弟子编制',
                      tuple(DefinitionKey('work_groups',row['machine_id']) for row in p['groups'])))
    for row in p['building_work']:
        _fields(row,('machine_id','display_name','slots_per_level','enabled'))
        registry.register(BuildingWorkDefinition('building_work',row['machine_id'],row['display_name'],
                          (DefinitionKey('buildings',row['machine_id']),),row['slots_per_level'],row['enabled']))
    if type(seal) is not bool:raise ValidationError('seal must be boolean')
    if seal:registry.seal()
    return registry


def initial_sources(registry):
    # Use the sealed package; do not re-read mutable JSON during State creation.
    return tuple(ref.machine_id for ref in registry.lookup(DefinitionKey('work_sources','initial')).references)

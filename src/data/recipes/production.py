"""@module data/recipes/production
@purpose Two real deterministic production definitions in the existing Registry.
@depends data/buildings, data/registry, core/validation, standard library
@usedBy systems/resources/jobs, application/production
@see ./INDEX.md
"""
from dataclasses import dataclass
import json
from pathlib import Path
from src.core.validation import ValidationError,DuplicateError,integer,schema_version
from src.data.registry import Definition,DefinitionKey,_fields
from src.data.buildings.definitions import load_content


@dataclass(frozen=True,slots=True)
class ProductionDefinition(Definition):
    building_kind: str = ''
    inputs: tuple = ()
    outputs: tuple = ()
    duration_ms: int = 1
    min_level: int = 1
    unlock_floor: int = 0
    unlock_realm: int = 0
    equipment_output_id: str | None = None
    facility_output_id: str | None = None

    def __post_init__(self):
        super(ProductionDefinition,self).__post_init__()
        if self.domain!='production':raise ValidationError('production namespace required')
        refs=[DefinitionKey('buildings',self.building_kind)]
        for values in (self.inputs,self.outputs):
            if type(values) is not tuple:raise ValidationError('resource amounts must be immutable')
            keys=[]
            for entry in values:
                if type(entry) is not tuple or len(entry)!=2:raise ValidationError('resource amount must be an immutable pair')
                key,quantity=entry
                integer(quantity,'production quantity',1);keys.append(key);refs.append(DefinitionKey('resources',key))
            if len(keys)!=len(set(keys)):raise DuplicateError('duplicate production resource')
        if self.equipment_output_id is not None:
            refs.append(DefinitionKey('equipment',self.equipment_output_id))
        if self.facility_output_id is not None:
            refs.append(DefinitionKey('ecology_facilities',self.facility_output_id))
            if self.outputs or self.equipment_output_id is not None:raise ValidationError('facility construction must not grant inventory output')
        if not self.outputs and self.equipment_output_id is None and self.facility_output_id is None:raise ValidationError('production output required')
        for field in ('duration_ms','min_level'):integer(getattr(self,field),field,1)
        for field in ('unlock_floor','unlock_realm'):integer(getattr(self,field),field)
        if self.references!=tuple(refs):raise ValidationError('production reference metadata mismatch')


def load_production(source=None, *, seal=True):
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise DuplicateError('duplicate production JSON key')
            result[key]=value
        return result
    try:
        package=json.loads(source if source is not None else Path(__file__).with_name('production.json').read_text(),object_pairs_hook=unique)
    except (TypeError,json.JSONDecodeError) as exc:raise ValidationError('invalid production JSON') from exc
    _fields(package,('schema_version','content_version','definitions'))
    schema_version(package['schema_version'],'data_schema_version')
    if type(package['definitions']) is not list:raise ValidationError('production definitions require array')
    building_package=json.loads(Path(__file__).parents[1].joinpath('buildings/buildings.json').read_text(),object_pairs_hook=unique)
    building_package['content_version']=package['content_version']
    registry=load_content(json.dumps(building_package),seal=False)
    register_production(registry,package['definitions'])
    if type(seal) is not bool:raise ValidationError('seal must be boolean')
    if seal:registry.seal()
    return registry


def register_production(registry,rows):
    """Compose additional recipes before seal; one schema and definition authority."""
    if type(rows) is not list:raise ValidationError('production definitions require array')
    for row in rows:
        _fields(row,('machine_id','display_name','building_kind','inputs','outputs','duration_ms','min_level','unlock_floor','unlock_realm'))
        if type(row['inputs']) is not dict or type(row['outputs']) is not dict:raise ValidationError('production resources require objects')
        inputs,outputs=tuple(sorted(row['inputs'].items())),tuple(sorted(row['outputs'].items()))
        refs=(DefinitionKey('buildings',row['building_kind']),)+tuple(DefinitionKey('resources',key) for key,_ in inputs+outputs)
        registry.register(ProductionDefinition('production',row['machine_id'],row['display_name'],refs,
                          row['building_kind'],inputs,outputs,row['duration_ms'],row['min_level'],row['unlock_floor'],row['unlock_realm']))

"""@module data/buildings/work
@purpose Immutable real building work-slot rule, not derived capacity state.
@depends data/registry,core/validation
@usedBy systems/sect/buildings, data/disciples/work
@see ./INDEX.md
"""
from dataclasses import dataclass
from src.data.registry import Definition,DefinitionKey
from src.core.validation import ValidationError,integer

@dataclass(frozen=True,slots=True)
class BuildingWorkDefinition(Definition):
    slots_per_level: int = 1
    enabled: bool = False
    def __post_init__(self):
        super(BuildingWorkDefinition,self).__post_init__()
        if self.domain!='building_work' or self.references!=(DefinitionKey('buildings',self.machine_id),):
            raise ValidationError('building work rule must reference its building')
        integer(self.slots_per_level,'slots_per_level',1)
        if type(self.enabled) is not bool:raise ValidationError('work enabled must be boolean')

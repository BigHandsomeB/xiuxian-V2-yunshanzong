"""@module data/recipes/alchemy
@purpose One real pill recipe composed into the existing Production/Work Registry.
@depends Data recipes/production,disciples/work,registry; Core/validation; stdlib
@usedBy systems/alchemy,application/alchemy
@see ./INDEX.md
"""
import json
from pathlib import Path
from src.core.validation import ValidationError,DuplicateError,schema_version
from src.data.registry import Definition,DefinitionKey,_fields
from src.data.disciples.work import load_work
from src.data.recipes.production import register_production


def load_alchemy(source=None):
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise DuplicateError('duplicate alchemy JSON key')
            result[key]=value
        return result
    try:
        p=json.loads(source if source is not None else Path(__file__).with_name('alchemy.json').read_text(),object_pairs_hook=unique)
    except (TypeError,json.JSONDecodeError) as exc:raise ValidationError('invalid alchemy JSON') from exc
    _fields(p,('schema_version','content_version','definitions'))
    schema_version(p['schema_version'],'alchemy schema')
    if type(p['definitions']) is not list or not p['definitions']:raise ValidationError('alchemy recipes require nonempty array')
    for row in p['definitions']:
        if not isinstance(row,dict) or row.get('building_kind')!='alchemy':raise ValidationError('alchemy recipe requires 丹鼎阁')
    work=json.loads(Path(__file__).parents[1].joinpath('disciples/work.json').read_text())
    work['content_version']=p['content_version']
    registry=load_work(json.dumps(work),seal=False)
    register_production(registry,p['definitions'])
    # Membership references only: quantities/duration remain solely ProductionDefinition.
    registry.register(Definition('alchemy','recipes','丹方',tuple(DefinitionKey('production',r['machine_id']) for r in p['definitions'])))
    registry.seal();return registry

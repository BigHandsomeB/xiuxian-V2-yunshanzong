"""Validated narrative packages, independent of numeric gameplay content versions."""
import json
import re
from functools import lru_cache
from pathlib import Path
from src.core.state.envelope import freeze_json
from src.core.validation import ValidationError, integer

ID = re.compile(r'[a-z][a-z0-9_]{1,79}\Z')
CONDITION_FIELDS = {
    'always': {'kind'}, 'floor': {'kind','dungeon_id','minimum'},
    'selected': {'kind','dungeon_id'}, 'entered': {'kind','dungeon_id'},
    'building_level': {'kind','building_kind','minimum'},
    'realm': {'kind','minimum'}, 'event': {'kind','event_id'},
}


def validate(catalog):
    if set(catalog) != {'chapters','nodes'}:
        raise ValidationError('invalid story catalog')
    chapter_ids=set();ids=set();orders=set()
    for row in catalog['chapters']:
        if set(row)!={'id','title'} or not ID.fullmatch(row['id']) or row['id'] in chapter_ids or not isinstance(row['title'],str) or not row['title']:
            raise ValidationError('invalid or duplicate story chapter')
        chapter_ids.add(row['id'])
    for row in catalog['nodes']:
        if set(row)!={'id','chapter','order','title','track','condition','lines'} or not ID.fullmatch(row['id']) or row['id'] in ids or row['chapter'] not in chapter_ids:
            raise ValidationError('invalid or duplicate story node')
        integer(row['order'],'story order',1)
        if row['order'] in orders or row['track'] not in ('main','side','independent') or type(row['title']) is not str or not row['title']:
            raise ValidationError('invalid story order/track/title')
        ids.add(row['id']);orders.add(row['order'])
        condition=row['condition'];kind=condition.get('kind')
        if kind not in CONDITION_FIELDS or set(condition)!=CONDITION_FIELDS[kind]:
            raise ValidationError('unknown story condition or fields')
        if 'minimum' in condition:integer(condition['minimum'],'story threshold',1)
        for key in ('dungeon_id','building_kind','event_id'):
            if key in condition and (type(condition[key]) is not str or not ID.fullmatch(condition[key])):
                raise ValidationError('invalid story condition reference')
        if not isinstance(row['lines'],(list,tuple)) or not 1<=len(row['lines'])<=30:
            raise ValidationError('story dialogue required')
        for line in row['lines']:
            if set(line)!={'speaker','text'} or any(type(v) is not str or not 1<=len(v)<=2000 for v in line.values()):
                raise ValidationError('invalid story dialogue')
    return catalog


def load_catalog(root=None):
    root=Path(root) if root is not None else Path(__file__).resolve().parents[3]/'assets'/'story'
    index=json.loads((root/'catalog.json').read_text())
    if set(index)!={'schema_version','packages'} or index['schema_version']!=1 or not isinstance(index['packages'],list) or not index['packages'] or len(set(index['packages']))!=len(index['packages']):
        raise ValidationError('invalid story package index')
    result={'chapters':[],'nodes':[]}
    for name in index['packages']:
        if type(name) is not str or Path(name).name!=name or not name.endswith('.json'):
            raise ValidationError('story package must be a local JSON file')
        package=json.loads((root/name).read_text())
        if set(package)!={'schema_version','release','chapters','nodes'} or package['schema_version']!=1 or type(package['release']) is not str:
            raise ValidationError('invalid story package')
        result['chapters'].extend(package['chapters']);result['nodes'].extend(package['nodes'])
    validate(result);result['nodes'].sort(key=lambda row:row['order'])
    return freeze_json(result)


@lru_cache(maxsize=1)
def catalog():
    return load_catalog()

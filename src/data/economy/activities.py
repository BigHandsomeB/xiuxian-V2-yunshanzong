"""Bounded first-release commission/exchange/chest rules; no new item authority."""
import json
from functools import lru_cache
from pathlib import Path
from src.core.state.envelope import freeze_json
from src.core.validation import ValidationError,integer
from src.data.registry import DefinitionKey

@lru_cache(maxsize=1)
def content():
    d=json.loads(Path(__file__).with_suffix('.json').read_text())
    if set(d)!={'schema_version','orders','exchanges','chest_choices','reputation','dungeons'} or d['schema_version']!=1:raise ValidationError('invalid activity config')
    for key in ('orders','exchanges','chest_choices'):
        rows=d[key]
        if not 1<=len(rows)<=32 or len({r['id'] for r in rows})!=len(rows):raise ValidationError('invalid activity identities')
        for r in rows:
            if not isinstance(r['id'],str) or not r['id'] or not isinstance(r['name'],str):raise ValidationError('invalid activity label')
            for field in ('cost','contribution'):
                if field in r:integer(r[field],field,1)
            amounts=r.get('items',r.get('rewards',{}))
            if not amounts:raise ValidationError('activity amounts required')
            for rid,n in amounts.items():DefinitionKey('resources',rid);integer(n,'activity quantity',1)
    if len(d['dungeons'])!=len(set(d['dungeons'])) or len(d['dungeons'])>32:raise ValidationError('invalid chest dungeons')
    if [r['threshold'] for r in d['reputation']]!=sorted({r['threshold'] for r in d['reputation']}) or d['reputation'][0]['threshold']!=0:raise ValidationError('invalid reputation tiers')
    return freeze_json(d)

@lru_cache(maxsize=16)
def settings(registry):
    d=content()
    for group in ('orders','exchanges','chest_choices'):
        for row in d[group]:
            for rid in row.get('items',row.get('rewards',{})):registry.lookup(DefinitionKey('resources',rid))
    for did in d['dungeons']:registry.lookup(DefinitionKey('dungeons',did))
    return d

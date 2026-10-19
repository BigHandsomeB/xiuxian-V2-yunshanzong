"""Small immutable exploration catalogue; resources remain registry-owned."""
import json
from functools import lru_cache
from pathlib import Path
from src.core.state.envelope import freeze_json
from src.core.validation import ValidationError, integer
from src.data.registry import DefinitionKey


@lru_cache(maxsize=1)
def content():
    data = json.loads(Path(__file__).with_name('content.json').read_text())
    if set(data) != {'schema_version', 'history_limit', 'regions'} or type(data['schema_version']) is not int or data['schema_version'] != 1:
        raise ValidationError('invalid exploration catalogue')
    integer(data['history_limit'], 'exploration history limit', 1)
    if data['history_limit'] > 100 or not 1 <= len(data['regions']) <= 16:
        raise ValidationError('exploration content exceeds bounds')
    seen = set()
    def identity(row):
        if type(row['id']) is not str or not row['id'] or row['id'] in seen:
            raise ValidationError('duplicate exploration identity')
        seen.add(row['id'])
        if type(row['name']) is not str or not row['name']:
            raise ValidationError('exploration name required')
    def amounts(value):
        if type(value) is not dict:
            raise ValidationError('exploration amounts object required')
        for rid, n in value.items():
            DefinitionKey('resources', rid)
            integer(n, 'exploration amount', 1)
    for region in data['regions']:
        if set(region) != {'id','name','dungeon_id','duration_days','description','rewards','events'}:
            raise ValidationError('invalid exploration region')
        identity(region)
        DefinitionKey('dungeons', region['dungeon_id'])
        integer(region['duration_days'], 'exploration duration', 1)
        if region['duration_days'] > 30 or not 1 <= len(region['events']) <= 16:
            raise ValidationError('invalid exploration duration/events')
        amounts(region['rewards'])
        if not region['rewards'] or type(region['description']) is not str:
            raise ValidationError('exploration description/rewards required')
        for event in region['events']:
            if set(event) != {'id','name','description','choices'}:
                raise ValidationError('invalid exploration event')
            identity(event)
            if type(event['description']) is not str or not 2 <= len(event['choices']) <= 4:
                raise ValidationError('invalid exploration choices')
            ids = set()
            for choice in event['choices']:
                if set(choice) != {'id','name','cost','rewards','success_bps','success_text','failure_text'}:
                    raise ValidationError('invalid exploration choice')
                if type(choice['id']) is not str or not choice['id'] or choice['id'] in ids:
                    raise ValidationError('duplicate exploration choice')
                ids.add(choice['id'])
                if any(type(choice[k]) is not str or not choice[k] for k in ('name','success_text')):
                    raise ValidationError('exploration result text required')
                integer(choice['success_bps'], 'exploration chance', 1)
                if choice['success_bps'] > 10000 or type(choice['failure_text']) is not str or (choice['success_bps'] < 10000 and not choice['failure_text']):
                    raise ValidationError('invalid exploration chance/result')
                amounts(choice['cost']); amounts(choice['rewards'])
            leave = next((c for c in event['choices'] if c['id'] == 'leave'), None)
            if not leave or leave['cost'] or leave['rewards'] or leave['success_bps'] != 10000:
                raise ValidationError('free exploration exit required')
    return freeze_json(data)


@lru_cache(maxsize=16)
def settings(registry):
    data = content()
    for region in data['regions']:
        registry.lookup(DefinitionKey('dungeons', region['dungeon_id']))
        amounts = [region['rewards']]
        for event in region['events']:
            for choice in event['choices']:
                amounts.extend((choice['cost'], choice['rewards']))
        for group in amounts:
            for rid in group:
                registry.lookup(DefinitionKey('resources', rid))
    return data


def region(registry, region_id):
    row = next((r for r in settings(registry)['regions'] if r['id'] == region_id), None)
    if row is None:
        raise ValidationError('请选择有效探索地点')
    return row

"""Versioned four-building content; references seal with the existing Registry."""
import json
from pathlib import Path
from src.core.validation import ValidationError, integer
from src.data.registry import Definition, DefinitionKey
from src.data.items.resources import ResourceDefinition
from src.data.recipes.production import ProductionDefinition

VERSION = 'sect-ecology-v1-6.3.0-r1'


def content():
    def unique(pairs):
        row = {}
        for key, value in pairs:
            if key in row:
                raise ValidationError('duplicate ecology content key')
            row[key] = value
        return row
    data = json.loads(Path(__file__).with_suffix('.json').read_text(), object_pairs_hook=unique)
    if data['schema_version'] != 1 or data['content_version'] != VERSION:
        raise ValidationError('unknown ecology content version')
    for collection in ('resources', 'crops', 'meals', 'species', 'facilities'):
        ids = [row['id'] for row in data[collection]]
        if len(set(ids)) != len(ids):
            raise ValidationError('duplicate ecology identity')
    if (len(data['crops']), len(data['meals']), len(data['species']), len(data['facilities'])) != (17, 27, 24, 4):
        raise ValidationError('incomplete confirmed ecology catalog')
    for row in data['species']:
        for key in ('days', 'feed_quantity', 'slots', 'purchase_coins'):
            integer(row[key], key, 1)
        if row['building_kind'] not in ('pasture', 'spring'):
            raise ValidationError('unknown husbandry building')
        for amounts in (row['periodic_outputs'], row['harvest_outputs']):
            for rid, quantity in amounts.items():
                DefinitionKey('resources', rid)
                integer(quantity, 'species output', 1)
    for row in data['meals']:
        if type(row['basic']) is not bool:
            raise ValidationError('meal category must be explicit')
        for key in ('speed_bps', 'extra_bps', 'discovery_bps'):
            integer(row[key], key)
            if row[key] > 10000:
                raise ValidationError('meal probability/rate out of bounds')
        if row['duration_days'] != (0 if row['basic'] else 8):
            raise ValidationError('confirmed meal duration required')
    return data


def register(registry, data):
    for row in data['resources']:
        registry.register(ResourceDefinition('resources', row['id'], row['name'], (), True, None, '待定'))
    for row in data['species']:
        resources = {row['feed_id'], *row['periodic_outputs'], *row['harvest_outputs']}
        refs = (DefinitionKey('buildings', row['building_kind']),) + tuple(
            DefinitionKey('resources', key) for key in sorted(resources))
        registry.register(Definition('ecology_species', row['id'], row['name'], refs))
    for row in data['facilities']:
        refs = (DefinitionKey('buildings', row['building_kind']),) + tuple(
            DefinitionKey('resources', key) for key in sorted(row['inputs']))
        registry.register(Definition('ecology_facilities', row['id'], row['name'], refs))
        refs = refs + (DefinitionKey('ecology_facilities', row['id']),)
        registry.register(ProductionDefinition(
            'production', 'build_' + row['id'], row['name'], refs,
            row['building_kind'], tuple(sorted(row['inputs'].items())), (), 120000,
            facility_output_id=row['id']))


def settings(registry):
    from src.data.economy.sect_rules import settings as sect_settings
    return (sect_settings(registry) or {}).get('ecology')


def lookup(registry, collection, identity):
    for row in settings(registry)[collection]:
        if row['id'] == identity:
            return row
    raise ValidationError('请选择已开放的正式内容')

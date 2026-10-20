"""Versioned material refinement configuration held by the sealed definition registry."""
from collections.abc import Mapping
from dataclasses import dataclass
from src.core.validation import ValidationError, integer
from src.data.economy.definitions import EQUIPMENT_STATS
from src.data.registry import Definition, DefinitionKey
from src.core.state.envelope import freeze_json

VERSION = 'material-refine-v1'
ELEMENTS = ('wood', 'earth', 'metal', 'water', 'fire', 'ice', 'poison', 'yin')
KEY = DefinitionKey('equipment_refinement', 'materials_v1')


@dataclass(frozen=True, slots=True)
class RefinementDefinition(Definition):
    values: object = None


def register(registry, cfg):
    validate_config(cfg)
    refs = tuple(DefinitionKey('resources', rid) for rid in sorted(cfg['materials']))
    registry.register(RefinementDefinition(KEY.domain, KEY.machine_id, '材料精炼', refs, freeze_json(cfg)))


def validate_config(cfg):
    if not isinstance(cfg, Mapping) or set(cfg) != {'version', 'coin_cost', 'min_forge_level', 'slots', 'materials'} or cfg['version'] != VERSION:
        raise ValidationError('invalid refinement configuration')
    integer(cfg['coin_cost'], 'refinement coin cost', 1)
    integer(cfg['min_forge_level'], 'refinement forge level', 1)
    if len(cfg['slots']) != 3:
        raise ValidationError('three refinement material slots required')
    for slot in cfg['slots']:
        if set(slot) != {'name', 'weight_bps'} or not isinstance(slot['name'], str) or not slot['name']:
            raise ValidationError('invalid refinement slot')
        integer(slot['weight_bps'], 'refinement slot weight', 1)
        if slot['weight_bps'] > 10000:
            raise ValidationError('bounded refinement slot required')
    if not isinstance(cfg['materials'], Mapping) or not cfg['materials']:
        raise ValidationError('refinement materials required')
    for row in cfg['materials'].values():
        if set(row) != {'element', 'source', 'description', 'quantity', 'stats'} or row['element'] not in ELEMENTS:
            raise ValidationError('invalid refinement material')
        if any(not isinstance(row[k], str) or not row[k] for k in ('source', 'description')):
            raise ValidationError('material provenance description required')
        integer(row['quantity'], 'refinement quantity', 1)
        if not isinstance(row['stats'], Mapping) or not row['stats']:
            raise ValidationError('refinement stats required')
        for key, value in row['stats'].items():
            if key not in EQUIPMENT_STATS:
                raise ValidationError('unknown refinement stat')
            integer(value, 'refinement stat', 1)
            if value > (20000 if key.endswith('_milli') else 600):
                raise ValidationError('bounded refinement material required')
    return cfg


def settings(registry):
    return registry.lookup(KEY).values if registry.contains(KEY) else None

"""Versioned artifact catalog: new dungeons bind content here, never in UI branches."""
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from src.core.state.envelope import freeze_json
from src.core.validation import ValidationError, integer
from src.data.registry import Definition, DefinitionKey
from src.data.content_loader import read_json

CONTENT_VERSION = 'sect-artifacts-v1-6.3.0-r1'
CATALOG_KEY = DefinitionKey('artifact_catalog', 'shipping')
MOTIONS = ('strike', 'spin', 'absorb', 'pulse', 'pour')

@dataclass(frozen=True, slots=True)
class ArtifactCatalog(Definition):
    values: object = None


def settings(registry):
    return registry.lookup(CATALOG_KEY).values if registry.contains(CATALOG_KEY) else None


def definition(registry, identity):
    cfg = settings(registry)
    if not isinstance(identity, str) or not cfg or identity not in cfg['artifacts']:
        raise ValidationError('请选择已开放法宝')
    return cfg['artifacts'][identity]


def register(registry, cfg):
    from src.data.combat.mechanics import validate_rule
    data, _ = read_json(Path(__file__).with_name('catalog.json'))
    if set(data) != {'schema_version', 'content_version', 'growth', 'enhancement', 'feed', 'effects', 'artifacts'} or data['schema_version'] != 1 or data['content_version'] != CONTENT_VERSION:
        raise ValidationError('invalid artifact package')
    growth = data['growth'];enhancement = data['enhancement']
    if set(growth) != {'max_level', 'xp_step', 'kill_xp'} or set(growth['kill_xp']) != {'normal', 'elite', 'boss'}:
        raise ValidationError('invalid artifact growth profile')
    for n in (growth['max_level'], growth['xp_step'], *growth['kill_xp'].values()):integer(n, 'artifact growth', 1)
    if growth['max_level'] > 100:raise ValidationError('unbounded artifact level')
    if set(enhancement) != {'max_level', 'cost', 'core_from_level', 'bonus_bps'}:raise ValidationError('invalid artifact enhancement')
    for key in ('max_level', 'core_from_level', 'bonus_bps'):integer(enhancement[key], key, 1)
    if enhancement['max_level'] > 20 or enhancement['bonus_bps'] > 10000:raise ValidationError('unbounded artifact enhancement')
    refs = set()
    def amounts(value):
        if not isinstance(value, Mapping) or not value:raise ValidationError('artifact amounts required')
        for key, n in value.items():
            integer(n, 'artifact quantity', 1);refs.add(DefinitionKey('resources', key))
    amounts(enhancement['cost']);amounts(data['feed'])
    if not cfg or not data['artifacts']:raise ValidationError('artifact effects require current combat')
    for key, row in data['effects'].items():
        DefinitionKey('artifact_effects',key)
        if set(row) != {'description', 'rules'}:raise ValidationError('invalid artifact effect')
        ids=set()
        for rule in row['rules']:
            validate_rule(rule, cfg['statuses'])
            if rule['id'] in ids:raise ValidationError('duplicate artifact effect rule')
            ids.add(rule['id'])
    for key, row in data['artifacts'].items():
        DefinitionKey('artifacts', key)
        expected={'name','glyph','source_dungeon_id','source_boss_id','core_material_id','recipe_id','inputs','duration_ms','unlock_floor','min_forge_level','effect_id','motion_profile_id','base_stats'}
        if set(row) != expected or row['effect_id'] not in data['effects'] or row['motion_profile_id'] not in MOTIONS:
            raise ValidationError('invalid artifact definition/binding')
        for field in ('source_dungeon_id','source_boss_id','core_material_id','recipe_id','effect_id','motion_profile_id'):
            DefinitionKey('artifact_refs',row[field])
        if not isinstance(row['name'],str) or not row['name'].strip() or not isinstance(row['glyph'],str) or not 1<=len(row['glyph'])<=2:raise ValidationError('artifact name/glyph required')
        integer(row['duration_ms'], 'artifact duration', 1);integer(row['unlock_floor'], 'artifact unlock', 1);integer(row['min_forge_level'], 'forge level', 1)
        if row['duration_ms'] > 7*86400000 or row['unlock_floor'] > 100:raise ValidationError('artifact duration/unlock outside bounds')
        dungeon=registry._definitions.get(DefinitionKey('dungeons',row['source_dungeon_id']))
        if dungeon is None:raise ValidationError('unknown artifact source dungeon')
        bosses=[registry._definitions[DefinitionKey('encounters',enc)].monster_id for enc,tier in zip(dungeon.encounters,dungeon.tiers) if tier=='boss']
        if row['source_boss_id'] not in bosses or row['core_material_id'] not in row['inputs']:raise ValidationError('artifact Boss/core source mismatch')
        # Verify provenance against the actual dungeon material catalog.
        from src.data.dungeons import loot, expeditions
        package=loot.content() if row['source_dungeon_id']=='thorn_path' else expeditions.content(row['source_dungeon_id'])
        if not any(m['id']==row['core_material_id'] and m['boss_only'] for m in package['materials']):raise ValidationError('artifact core must be a Boss-only drop')
        if set(row['base_stats']) - {'attack_milli','armor_milli','max_hp_milli'}:raise ValidationError('unsupported artifact base stat')
        for n in row['base_stats'].values():integer(n, 'artifact base stat', 1)
        amounts(row['inputs']);refs.add(DefinitionKey('monsters',row['source_boss_id']))
        refs.add(DefinitionKey('dungeons',row['source_dungeon_id']))
        registry.register(Definition('artifacts',key,row['name'],tuple(DefinitionKey('resources',rid) for rid in row['inputs'])))
    recipes=[r['recipe_id'] for r in data['artifacts'].values()]
    if len(set(recipes)) != len(recipes):raise ValidationError('duplicate artifact recipe ID')
    for key in recipes:DefinitionKey('artifact_recipes', key)
    registry.register(ArtifactCatalog('artifact_catalog','shipping','法宝目录',tuple(sorted(refs,key=lambda k:(k.domain,k.machine_id))),freeze_json(data)))
    return {identity:{'name':row['name'],'max_level':growth['max_level'],'rules':data['effects'][row['effect_id']]['rules']} for identity,row in data['artifacts'].items()}

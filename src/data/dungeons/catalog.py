"""Controlled dungeon declarations; historical cohorts are frozen compatibility data.

Add same-template content to ENTRIES with profile ecology_current. A declaration
is not a new gameplay mechanism and never selects an executable Python import.
"""
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from src.core.validation import ValidationError, integer
from src.data.registry import DefinitionKey


@dataclass(frozen=True, slots=True)
class DungeonEntry:
    machine_id: str
    kind: str
    source: str
    profile: str = 'ecology_current'


_THORN = DungeonEntry('thorn_path', 'thorn', 'thorn_path.json', 'historical')
_MINE = DungeonEntry('red_copper_mine', 'expedition', 'red_copper_mine.json', 'historical')
_MARSH = DungeonEntry('mist_marsh', 'expedition', 'mist_marsh.json', 'historical')
_CAVE = DungeonEntry('cold_jade_cave', 'expedition', 'cold_jade_cave.json', 'historical')
ENTRIES = (_THORN, _MINE, _MARSH, _CAVE, DungeonEntry('fire_elixir_ruins','expedition','fire_elixir_ruins.json'))
# Appending current declarations must not extend a historical content version.
HISTORICAL_IDS = (_MINE.machine_id, _MARSH.machine_id)
HISTORICAL_COLD_JADE_IDS = (*HISTORICAL_IDS, _CAVE.machine_id)
# Existing shared tables consumed by the dungeon adapters, not dungeon entries.
SUPPORT_SOURCES = frozenset(('balance.json', 'combat_tuning.json', 'equipment_ranges.json',
                             'expedition_materials.json', 'thorn_loot.json'))


def entry(machine_id):
    matches = [row for row in ENTRIES if row.machine_id == machine_id]
    if len(matches) != 1:
        raise ValidationError('unknown or duplicate dungeon ID: ' + str(machine_id))
    return matches[0]


def source_path(row):
    if not isinstance(row.source, str) or '\\' in row.source or '\x00' in row.source:
        raise ValidationError('invalid dungeon configuration filename')
    source = PurePosixPath(row.source)
    if len(source.parts) != 1 or source.is_absolute() or source.suffix != '.json':
        raise ValidationError('dungeon source must be one local JSON filename')
    base = Path(__file__).resolve().parent
    path = (base / row.source).resolve()
    if not path.is_relative_to(base):
        raise ValidationError('dungeon source escapes data directory')
    return path


def validate_entries():
    if not isinstance(ENTRIES, tuple) or not ENTRIES:
        raise ValidationError('nonempty immutable dungeon catalog required')
    seen, sources = set(), set()
    for row in ENTRIES:
        if not isinstance(row, DungeonEntry):
            raise ValidationError('dungeon declaration required')
        DefinitionKey('dungeons', row.machine_id)
        if row.machine_id in seen:
            raise ValidationError('duplicate dungeon ID: ' + row.machine_id)
        seen.add(row.machine_id)
        if row.kind not in ('thorn', 'expedition') or row.profile not in ('historical', 'ecology_current'):
            raise ValidationError('unsupported dungeon kind/profile')
        if row.profile == 'historical' and row not in (_THORN, _MINE, _MARSH, _CAVE):
            raise ValidationError('new declarations require the current profile')
        if row.kind == 'thorn' and row != _THORN:
            raise ValidationError('thorn adapter is reserved for the historical thorn dungeon')
        path = source_path(row)
        if path in sources:
            raise ValidationError('duplicate dungeon configuration path')
        sources.add(path)
    # Historical declarations, paths and adapters cannot be silently reclassified.
    for row in (_THORN, _MINE, _MARSH, _CAVE):
        if entry(row.machine_id) != row:
            raise ValidationError('historical dungeon declaration changed')
    for left in seen:
        if any(right != left and right.startswith(left + '_') for right in seen):
            raise ValidationError('ambiguous dungeon encounter prefix: ' + left)


def all_ids():
    return tuple(row.machine_id for row in ENTRIES)


def expedition_ids(*, cold_jade=False, current=False):
    if current:
        return tuple(row.machine_id for row in ENTRIES if row.kind == 'expedition')
    return HISTORICAL_COLD_JADE_IDS if cold_jade else HISTORICAL_IDS


def registered_ids(registry):
    return tuple(did for did in all_ids() if registry.contains(DefinitionKey('dungeons', did)))


def validate_sources(sources):
    validate_entries()
    missing = {'src/data/dungeons/' + row.source for row in ENTRIES} - set(sources)
    if missing:
        raise ValidationError('dungeon sources missing from content manifest: ' + repr(sorted(missing)))
    prefix = 'src/data/dungeons/'
    declared = {name for name in sources if name.startswith(prefix)}
    expected = {prefix + row.source for row in ENTRIES}
    unbound = declared - expected - {prefix + name for name in SUPPORT_SOURCES}
    if unbound:
        raise ValidationError('dungeon sources have no catalog entry or supported table: ' + repr(sorted(unbound)))


def validate_registry(registry):
    """Current-profile post-assembly checks; no state or cross-domain mutation."""
    validate_entries()
    if not registry.is_sealed:
        raise ValidationError('sealed dungeon registry required')
    from .definitions import DungeonDefinition
    from .expeditions import content
    expected = set(all_ids())
    actual = {key.machine_id for key in registry._definitions if key.domain == 'dungeons'}
    if actual != expected:
        raise ValidationError('registered dungeon coverage differs from catalog')
    edges = {}
    for row in ENTRIES:
        dungeon = registry.lookup(DefinitionKey('dungeons', row.machine_id))
        if not isinstance(dungeon, DungeonDefinition):
            raise ValidationError('registered dungeon definition required')
        if row.kind == 'thorn':
            continue
        condition = content(row.machine_id)['unlock']
        parent = condition['dungeon_id']
        if parent not in actual:
            raise ValidationError('unregistered dungeon unlock target: ' + parent)
        target = registry.lookup(DefinitionKey('dungeons', parent))
        integer(condition['cleared_floor'], 'unlock floor', 1)
        if condition['cleared_floor'] > len(target.encounters):
            raise ValidationError('unlock floor outside target dungeon')
        edges[row.machine_id] = parent
    for start in edges:
        seen, cursor = set(), start
        while cursor in edges:
            if cursor in seen:
                raise ValidationError('cyclic dungeon unlock graph')
            seen.add(cursor)
            cursor = edges[cursor]
    market_key = DefinitionKey('market_rules', 'shipping')
    if registry.contains(market_key):
        for resource, rule in registry.lookup(market_key).values['items'].items():
            for did, floor in rule['unlock'].items():
                if did not in actual:
                    raise ValidationError('unregistered market dungeon source: ' + resource)
                integer(floor, 'market source floor', 1)
                if floor > len(registry.lookup(DefinitionKey('dungeons', did)).encounters):
                    raise ValidationError('market source floor outside dungeon')

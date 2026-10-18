"""Strict current-content startup assembly; historical factories remain independent.

No save, UI or tool dependencies. A loader pins one validated disk snapshot for
its lifetime. Changed inputs require a new process, never an in-process reload.
"""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
from threading import RLock

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = 'src/data/content_manifest.json'
PROFILES = ('ecology_current',)


class ContentInputError(ValueError):
    pass


def read_json(path):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ContentInputError('duplicate JSON key: ' + key)
            value[key] = item
        return value
    def invalid(value):
        raise ContentInputError('non-finite JSON value: ' + value)
    raw = path.read_bytes()
    return json.loads(raw.decode('utf-8'), object_pairs_hook=unique,
                      parse_constant=invalid), hashlib.sha256(raw).hexdigest()


def checked_path(root, value, *, source=False):
    if not isinstance(value, str) or not value or '\x00' in value:
        raise ContentInputError('path must be a nonempty string')
    pure = PurePosixPath(value)
    if '..' in pure.parts or (source and pure.is_absolute()):
        raise ContentInputError('absolute source paths and parent traversal are forbidden')
    if source and (pure.parts[:2] != ('src', 'data') or pure.suffix != '.json'):
        raise ContentInputError('sources must be explicit src/data/*.json paths')
    path = (root / value).resolve()
    if not path.is_relative_to(root):
        raise ContentInputError('path escapes project root')
    if not source and (pure.suffix != '.json' or any(part.startswith('.') for part in path.relative_to(root).parts)):
        raise ContentInputError('manifest must be a JSON file outside private/hidden directories')
    if source and not path.is_relative_to((root / 'src/data').resolve()):
        raise ContentInputError('source escapes data directory')
    if not path.is_file():
        raise ContentInputError('file does not exist: ' + value)
    return path


def validate_manifest(data):
    if not isinstance(data, dict) or set(data) != {'schema_version', 'profile', 'content_version', 'packages'}:
        raise ContentInputError('manifest requires schema_version, profile, content_version and packages only')
    if type(data['schema_version']) is not int or data['schema_version'] != 1:
        raise ContentInputError('unsupported manifest schema version')
    if data['profile'] not in PROFILES:
        raise ContentInputError('unsupported manifest profile')
    if not isinstance(data['content_version'], str) or not data['content_version'].strip():
        raise ContentInputError('content_version must be a nonempty string')
    if not isinstance(data['packages'], list) or not data['packages']:
        raise ContentInputError('packages must be a nonempty list')
    ids, sources = set(), set()
    for row in data['packages']:
        if not isinstance(row, dict) or set(row) != {'id', 'sources'}:
            raise ContentInputError('package requires id and sources only')
        key = row['id']
        if not isinstance(key, str) or not re.fullmatch('[a-z][a-z0-9_]*', key):
            raise ContentInputError('invalid package ID')
        if key in ids:
            raise ContentInputError('duplicate package ID: ' + key)
        ids.add(key)
        if not isinstance(row['sources'], list) or not row['sources']:
            raise ContentInputError('package sources must be a nonempty list')
        for path in row['sources']:
            if not isinstance(path, str):
                raise ContentInputError('source path must be a string')
            if path in sources:
                raise ContentInputError('duplicate source declaration: ' + path)
            sources.add(path)
    return sorted(sources)


def discover_sources(root, manifest):
    """Enumerate names only, excluding the manifest itself; no directory symlinks."""
    result = set()
    data_root = root / 'src/data'
    if data_root.is_dir() and data_root.resolve().is_relative_to(root):
        for directory, _, names in os.walk(data_root, followlinks=False):
            for name in names:
                path = Path(directory) / name
                if name.endswith('.json') and path != manifest:
                    result.add(path.relative_to(root).as_posix())
    return result


def content_snapshot(root, manifest):
    """Validate all declared inputs before executing a trusted assembly adapter."""
    path = checked_path(root, str(manifest))
    data, digest = read_json(path)
    sources = validate_manifest(data)
    hashes = {str(path): digest}
    resolved = {path}
    for name in sources:
        source = checked_path(root, name, source=True)
        if source in resolved:
            raise ContentInputError('duplicate resolved source or manifest declared as content: ' + name)
        resolved.add(source)
        value, digest = read_json(source)
        if not isinstance(value, dict):
            raise ContentInputError('source JSON must be an object: ' + name)
        if 'schema_version' in value and (type(value['schema_version']) is not int or value['schema_version'] != 1):
            raise ContentInputError('unsupported source schema_version: ' + name)
        hashes[str(source)] = digest
    discovered = discover_sources(root, path)
    if discovered != set(sources):
        raise ContentInputError('source coverage mismatch; undeclared=' + repr(sorted(discovered-set(sources))) +
                                '; undiscovered=' + repr(sorted(set(sources)-discovered)))
    return data, hashes


def _assemble_profile(profile):
    if profile != 'ecology_current':
        raise ContentInputError('unsupported profile')
    from src.data.dungeons import catalog
    catalog.validate_entries()
    # Startup only: old factory users may have populated these JSON caches.
    # Clear before the first pinned assembly so validated disk input is used.
    # Existing immutable registries and player snapshots are never mutated.
    from src.data.dungeons import loot, expeditions, durability
    from src.data.economy import activities
    for reader in (loot.content, expeditions.content, durability.settings, activities.content):
        reader.cache_clear()
    from src.data.dungeons.definitions import load_dungeons
    registry = load_dungeons(management=True, cold_jade=True, ecology=True, mechanics=True, skill_timing=True, artifacts=True)
    catalog.validate_registry(registry)
    from src.data.item_effects import bindings_for
    bindings_for(registry)
    return registry


class ContentLoader:
    """Startup loader; assembler is a trusted Python seam, never a JSON import."""
    def __init__(self, *, root=ROOT, manifest=DEFAULT_MANIFEST, assembler=_assemble_profile):
        self.root = Path(root).resolve()
        self.manifest = manifest
        self.assembler = assembler
        if assembler is _assemble_profile and self.root != ROOT:
            raise ContentInputError('built-in profile requires the project data root')
        self._hashes = None
        self._registry = None
        self._lock = RLock()

    def load(self):
        with self._lock:
            data, before = content_snapshot(self.root, self.manifest)
            if self._hashes is not None:
                if before != self._hashes:
                    raise ContentInputError('content changed in this process; restart required')
                return self._registry
            if self.assembler is _assemble_profile:
                from src.data.dungeons import catalog
                catalog.validate_sources(validate_manifest(data))
            registry = self.assembler(data['profile'])
            if not registry.is_sealed:
                raise ContentInputError('assembled registry must be sealed')
            if registry.content_version != data['content_version']:
                raise ContentInputError('manifest content_version differs from assembled registry')
            after_data, after = content_snapshot(self.root, self.manifest)
            if before != after or data != after_data:
                raise ContentInputError('inputs changed during assembly; restart required')
            self._hashes, self._registry = before, registry
            return registry


_current = ContentLoader()


def load_current():
    """Capture once when composing an application, not inside GET/view handlers."""
    return _current.load()

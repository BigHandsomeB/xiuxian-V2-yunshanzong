"""Read-only content audit. Shared manifest drives current startup; this command reports audit coverage."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if __name__ == '__main__':
    sys.dont_write_bytecode = True
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
from src.data.content_loader import (
    DEFAULT_MANIFEST, PROFILES, ContentInputError as AuditInputError,
    checked_path, read_json, validate_manifest, discover_sources, load_current,
)


def load_profile(profile):
    if profile not in PROFILES:
        raise AuditInputError('unsupported profile')
    from src.data.economy.sect_rules import settings
    registry = load_current()
    return registry, tuple(settings(registry)['production_whitelist'])


def audit(manifest=DEFAULT_MANIFEST, *, root=ROOT, loader=load_profile):
    """loader is a trusted test seam; JSON and CLI cannot select executable imports."""
    root = Path(root).resolve()
    report = {'schema_version': 1, 'status': 'ERROR', 'target': {}, 'counts': {},
              'coverage': {'declared_sources': [], 'checked_sources': [], 'undeclared_sources': []},
              'source_sha256': {}, 'issues': []}
    def issue(severity, code, path, message):
        report['issues'].append({'severity': severity, 'code': code, 'path': path, 'message': message})
    def finish():
        rank = {'ERROR': 0, 'WARNING': 1, 'NOT_CHECKED': 2}
        report['issues'].sort(key=lambda x: (rank[x['severity']], x['code'], x['path'], x['message']))
        report['status'] = ('ERROR' if any(x['severity']=='ERROR' for x in report['issues']) else
                            'WARNING' if any(x['severity']=='WARNING' for x in report['issues']) else 'PASS')
        return report
    for code, text in (
        ('ASSET_BINDINGS', 'Approved art, runtime images and UI binding completeness are not checked.'),
        ('SOURCE_USE_SEMANTICS', 'Functional acquisition/consumption reachability is not checked.'),
        ('SAVE_COMPATIBILITY', 'Player saves, migrations and rollback compatibility are not checked.'),
        ('EFFECT_EXECUTION', 'Item effect handlers and transaction behavior are not checked.'),
        ('BALANCE', 'Combat and economy balance are not simulated.')):
        issue('NOT_CHECKED', code, '', text)
    try:
        path = checked_path(root, str(manifest))
        data, digest = read_json(path)
        manifest_name = path.relative_to(root).as_posix()
        sources = validate_manifest(data)
        report['target'] = {'profile': data['profile'], 'expected_content_version': data['content_version']}
        report['manifest_sha256'] = digest
        report['coverage']['declared_sources'] = sources
        report['counts']['packages'] = len(data['packages'])
    except (OSError, ValueError, TypeError) as exc:
        issue('ERROR', 'MANIFEST_INVALID', str(manifest), str(exc))
        issue('NOT_CHECKED', 'REGISTRY', '', 'Registry was not loaded because manifest validation failed.')
        return finish()
    for name in sources:
        try:
            path = checked_path(root, name, source=True)
            content, digest = read_json(path)
            if not isinstance(content, dict):
                raise AuditInputError('source JSON must be an object')
            if 'schema_version' in content and (type(content['schema_version']) is not int or content['schema_version'] != 1):
                raise AuditInputError('unsupported source schema_version for this audit profile')
            report['source_sha256'][name] = digest
            report['coverage']['checked_sources'].append(name)
        except (OSError, ValueError, TypeError) as exc:
            issue('ERROR', 'SOURCE_INVALID', name, str(exc))
    # Exclude the canonical runtime manifest and the selected audit manifest.
    discovered = discover_sources(root, root / DEFAULT_MANIFEST)
    discovered.discard(manifest_name)
    for name in sorted(discovered-set(sources)):
        report['coverage']['undeclared_sources'].append(name)
        issue('WARNING', 'SOURCE_UNDECLARED', name, 'Not independently parsed or hashed by this audit manifest. Current runtime loading requires complete coverage.')
    if any(x['severity']=='ERROR' for x in report['issues']):
        issue('NOT_CHECKED', 'REGISTRY', '', 'Registry was not loaded because declared source validation failed.')
        return finish()
    try:
        registry, whitelist = loader(data['profile'])
        report['target']['loaded_content_version'] = registry.content_version
        if registry.content_version != data['content_version']:
            issue('ERROR', 'CONTENT_VERSION_MISMATCH', '', 'Manifest content_version differs from the loaded registry.')
        if not registry.is_sealed:
            issue('ERROR', 'REGISTRY_UNSEALED', '', 'Registry must be sealed before audit.')
            return finish()
        # Existing code has no public iterator. Read the sealed mapping; do not mutate Foundation.
        definitions = tuple(registry._definitions.values())
        counts = Counter(d.domain for d in definitions)
        report['counts'].update(definitions=len(definitions), by_domain=dict(sorted(counts.items())))
        seen = set()
        for definition in definitions:
            identity = definition.domain+':'+definition.machine_id
            if definition.key in seen:
                issue('ERROR', 'DEFINITION_DUPLICATE', identity, 'Duplicate registered definition ID.')
            seen.add(definition.key)
            for ref in definition.references:
                if not registry.contains(ref):
                    issue('ERROR', 'REFERENCE_MISSING', identity, 'Missing '+ref.domain+':'+ref.machine_id)
        whitelist = tuple(whitelist)
        report['counts']['production_whitelist'] = len(whitelist)
        production_ids = {d.machine_id for d in definitions if d.domain=='production'}
        seen_recipes = set()
        for key in whitelist:
            if not isinstance(key, str):
                issue('ERROR', 'RECIPE_INVALID', '', 'Whitelist recipe IDs must be strings.')
                continue
            if key in seen_recipes:
                issue('ERROR', 'RECIPE_DUPLICATE', key, 'Recipe appears more than once in the whitelist.')
            seen_recipes.add(key)
            if key not in production_ids:
                issue('ERROR', 'RECIPE_UNREGISTERED', key, 'Whitelisted recipe has no registered production definition.')
        report['counts']['registered_recipes_not_whitelisted'] = len(production_ids-seen_recipes)
        # Registered but unopened/historical recipes are not errors and are never auto-enabled.
        pending = sorted(d.machine_id for d in definitions if d.domain=='resources' and getattr(d,'tier',None)=='待定')
        if pending:
            issue('WARNING', 'RESOURCE_TIER_PENDING', 'resources',
                  f'{len(pending)} resources have an explicit pending tier; review design, not save corruption. Examples: '+', '.join(pending[:8]))
    except Exception as exc:
        issue('ERROR', 'REGISTRY_LOAD_FAILED', data['profile'], type(exc).__name__+': '+str(exc))
    watched = [(str(manifest), report['manifest_sha256'], False)]
    watched += [(name, digest, True) for name, digest in report['source_sha256'].items()]
    for name, digest, is_source in watched:
        try:
            path = checked_path(root, name, source=is_source)
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise AuditInputError('file changed during audit; rerun against a stable content snapshot')
        except (OSError, ValueError) as exc:
            issue('ERROR', 'INPUT_CHANGED', name, str(exc))
    return finish()


def exit_code(report):
    return 1 if report['status']=='ERROR' else 0


def main(argv=None):
    sys.dont_write_bytecode = True
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', default=DEFAULT_MANIFEST, help='manifest path within this project')
    parser.add_argument('--json', action='store_true', help='emit stable JSON to stdout')
    args = parser.parse_args(argv)
    report = audit(args.manifest)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    else:
        print('Content audit: '+report['status'])
        print('Target: '+str(report['target'].get('profile','unavailable')))
        print('Counts: '+json.dumps(report['counts'], ensure_ascii=False, sort_keys=True))
        print('Source coverage: '+str(len(report['coverage']['checked_sources']))+'/'+str(len(report['coverage']['declared_sources'])))
        for item in report['issues']:
            print(f"[{item['severity']}] {item['code']} {item['path']}: {item['message']}")
    return exit_code(report)


if __name__ == '__main__':
    raise SystemExit(main())

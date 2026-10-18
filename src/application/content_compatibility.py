"""Pure compatibility report, never an upgrade, recovery or readiness permit."""
from dataclasses import replace

from src.core.state.envelope import StateEnvelope
from src.core.validation import ConflictError, NotFoundError, ValidationError
from src.data import content_compatibility as content


class _ReadOnlyClock:
    def now_ms(self):
        raise AssertionError('compatibility analysis must not read wall time')


def load_registry(version):
    row = content.profile(version)
    if row.loader == 'current':
        from src.data.content_loader import load_current
        return load_current()
    from src.data.dungeons.definitions import load_dungeons
    return load_dungeons(**dict(row.flags))


def validate_snapshot(state, registry):
    row = content.profile(registry.content_version)
    if set(state.domains) - row.domains:
        raise ValidationError('snapshot contains unsupported Domain partitions')
    from src.application.ecology import EcologyApplication
    from src.application.sect_management import ManagementApplication
    application = {'ecology': EcologyApplication, 'management': ManagementApplication}[row.application]
    return application(None, registry, _ReadOnlyClock()).foundation.validate_state(state)


def inspect_compatibility(state, target_version, *, source_registry=None, target_registry=None):
    if not isinstance(state, StateEnvelope):
        raise ValidationError('StateEnvelope required')
    report = {'report_schema_version': 1, 'input_sha256': content.digest(state.to_dict()),
              'source': {'content_version': state.content_version, 'save_schema_version': state.save_schema_version,
                         'data_schema_version': state.data_schema_version, 'validation': 'NOT_CHECKED'},
              'target': {'content_version': target_version, 'save_schema_version': state.save_schema_version,
                         'validation': 'NOT_CHECKED'},
              'transition': 'BLOCKED', 'provenance': 'CURRENT_TREE_ONLY',
              'differences': {}, 'issues': [],
              'not_checked': ['HISTORICAL_RELEASE_CODE_AND_PACKAGE', 'UNFINGERPRINTED_RULES',
                              'SQLITE_RECEIPTS', 'WALL_CLAIM', 'PREVIOUS', 'DATABASE_INTEGRITY']}
    def issue(code, message):
        report['issues'].append({'code': code, 'message': message})
    try:
        content.profile(state.content_version)
    except ValidationError:
        report['source']['validation'] = 'UNSUPPORTED'
        issue('UNSUPPORTED_SOURCE', 'Source version has no declared runtime adapter.')
        return report
    try:
        policy = content.transition(state.content_version, target_version)
    except ValidationError:
        report['target']['validation'] = 'UNSUPPORTED'
        issue('UNSUPPORTED_TARGET', 'Target version has no declared runtime adapter.')
        return report
    failures = (ValidationError, ConflictError, NotFoundError, KeyError, TypeError, ValueError)
    try:
        source = source_registry if source_registry is not None else load_registry(state.content_version)
        if source.content_version != state.content_version:
            raise ValidationError('source package version differs')
        validate_snapshot(state, source)
        before = content.package_evidence(source)
    except failures:
        report['source']['validation'] = 'INVALID'
        issue('SOURCE_INVALID', 'Source snapshot or package failed its owning validator; analysis stopped.')
        return report
    report['source'].update(validation='VALID', fingerprint=before['fingerprint'])
    try:
        target = target_registry if target_registry is not None else load_registry(target_version)
        if target.content_version != target_version:
            raise ValidationError('target package version differs')
        after = content.package_evidence(target)
    except failures:
        report['target']['validation'] = 'INVALID'
        issue('TARGET_PACKAGE_INVALID', 'Target package or effect bindings failed validation.')
        return report
    report['target'].update(data_schema_version=target.schema_version, fingerprint=after['fingerprint'])
    delta = content.differences(before, after)
    report['differences'] = delta
    changed = any(values for group in delta.values() for values in group.values())
    if state.content_version == target_version and changed:
        issue('SAME_VERSION_DIFFERENT_PACKAGE', 'The same content version has different definitions or effect bindings.')
        policy = 'BLOCKED'
    if any(delta[group]['removed'] or delta[group]['modified'] for group in delta):
        issue('SEMANTIC_REVIEW_REQUIRED', 'Changed or removed IDs require an explicit preservation/conversion policy.')
    if any(delta[group]['added'] for group in delta):
        issue('ADDITIONS_NOT_UNLOCKS', 'Registered new IDs do not grant, unlock or migrate saved content.')
    if state.content_version != target_version and state.time['pending'] is not None:
        issue('PENDING_WINDOW', 'Finish the old window before planning this transition; report does not settle or rebind it.')
        report['transition'] = 'BLOCKED'
        return report
    candidate = replace(state, content_version=target_version)
    try:
        validate_snapshot(candidate, target)
        report['target']['validation'] = 'VALID'
    except failures:
        report['target']['validation'] = 'INVALID'
        issue('TARGET_CANDIDATE_INVALID', 'Untransformed in-memory candidate failed target validation; no conversion was attempted.')
        if policy == 'NOT_NEEDED':
            policy = 'BLOCKED'
    report['transition'] = policy
    if state.content_version != target_version and content.transition(state.content_version, target_version) == 'BLOCKED':
        issue('DOWNGRADE_NOT_SUPPORTED', 'No declared downgrade exists; target validation cannot authorize rollback.')
    if policy == 'REQUIRES_EXPLICIT_MIGRATION':
        issue('DEDICATED_MIGRATION_REQUIRED', 'Use the separately authorized ecology_content_upgrade, not this report.')
    return report

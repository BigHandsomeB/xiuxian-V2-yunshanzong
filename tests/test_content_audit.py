"""Read-only audit contracts and injected defects; no player state or SQLite fixtures."""
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools.economy import check_content as audit_tool
from src.data.registry import Definition, DefinitionKey
from src.data.items.resources import ResourceDefinition


VERSION = 'test-content-v1'


def registry(definitions=(), *, version=VERSION, sealed=True):
    values = {i: item for i, item in enumerate(definitions)}
    keys = {item.key for item in definitions}
    return SimpleNamespace(content_version=version, is_sealed=sealed,
                           _definitions=values, contains=lambda key: key in keys)


class ContentAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='content-audit-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root/'src/data/sample.json'
        self.source.parent.mkdir(parents=True)
        self.source.write_text('{"schema_version":1}')
        self.manifest = self.root/'manifest.json'
        self.data = {'schema_version':1, 'profile':'ecology_current', 'content_version':VERSION,
                     'packages':[{'id':'sample','sources':['src/data/sample.json']}]}
        self.write_manifest()

    def write_manifest(self):
        self.manifest.write_text(json.dumps(self.data))

    def run_audit(self, definitions=(), whitelist=(), *, fake=None):
        return audit_tool.audit('manifest.json', root=self.root,
                                loader=lambda profile:(fake or registry(definitions), whitelist))

    def codes(self, report):
        return {item['code'] for item in report['issues'] if item['severity']=='ERROR'}

    def test_valid_inputs_are_stable_and_read_only(self):
        before = {p.relative_to(self.root).as_posix():p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with patch.object(Path,'write_text',side_effect=AssertionError('unexpected write')), \
             patch.object(Path,'write_bytes',side_effect=AssertionError('unexpected write')), \
             patch('sqlite3.connect',side_effect=AssertionError('unexpected DB')):
            first=self.run_audit();second=self.run_audit()
        self.assertEqual(first,second)
        self.assertEqual(first['status'],'PASS')
        self.assertEqual(audit_tool.exit_code(first),0)
        self.assertEqual(first['coverage']['checked_sources'],['src/data/sample.json'])
        self.assertEqual(before,{p.relative_to(self.root).as_posix():p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        self.assertTrue(any(x['severity']=='NOT_CHECKED' and x['code']=='SAVE_COMPATIBILITY' for x in first['issues']))

    def test_bad_manifests_fail_before_loading(self):
        mutations = [
            lambda d:d.update(schema_version=2), lambda d:d.update(schema_version=True),
            lambda d:d.update(profile='python.module'),lambda d:d.update(unknown=True),
            lambda d:d.update(content_version=''),lambda d:d.update(packages=[]),
            lambda d:d['packages'].append({'id':'sample','sources':['src/data/other.json']}),
            lambda d:d['packages'].append({'id':'other','sources':['src/data/sample.json']}),
            lambda d:d['packages'][0].update(id='../invalid'),
            lambda d:d['packages'][0].update(sources=[123]),
        ]
        original=json.loads(json.dumps(self.data))
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                self.data=json.loads(json.dumps(original));mutate(self.data);self.write_manifest()
                loader=lambda _:self.fail('invalid manifest loaded registry')
                report=audit_tool.audit('manifest.json',root=self.root,loader=loader)
                self.assertIn('MANIFEST_INVALID',self.codes(report));self.assertEqual(audit_tool.exit_code(report),1)

    def test_duplicate_manifest_keys_and_nonfinite_values_are_rejected(self):
        for raw in ('{"schema_version":1,"schema_version":1}', '{"schema_version":NaN}'):
            with self.subTest(raw=raw):
                self.manifest.write_text(raw)
                report=self.run_audit()
                self.assertIn('MANIFEST_INVALID',self.codes(report))

    def test_bad_source_json_and_schema_fail_without_loading_registry(self):
        for raw in ('{"x":1,"x":2}', '{"x":NaN}', '{', '[]', '{"schema_version":2}', '{"schema_version":true}'):
            with self.subTest(raw=raw):
                self.source.write_text(raw)
                report=audit_tool.audit('manifest.json',root=self.root,loader=lambda _:self.fail('bad source loaded registry'))
                self.assertIn('SOURCE_INVALID',self.codes(report))
                self.assertEqual(audit_tool.exit_code(report),1)

    def test_missing_and_traversal_source_paths_are_rejected(self):
        for path in ('src/data/missing.json','../outside.json','/etc/passwd','src/data/../../manifest.json','src/ui/data.json'):
            with self.subTest(path=path):
                self.data['packages'][0]['sources']=[path];self.write_manifest()
                report=self.run_audit();self.assertIn('SOURCE_INVALID',self.codes(report))

    def test_symlink_escape_is_rejected_and_external_source_is_not_read(self):
        outside=self.root/'outside.json';outside.write_text('{"value":"not data"}')
        self.source.unlink();self.source.symlink_to(outside)
        report=self.run_audit();self.assertIn('SOURCE_INVALID',self.codes(report))
        self.assertEqual(report['coverage']['checked_sources'],[])

    def test_manifest_outside_root_or_private_state_is_rejected_before_read(self):
        private=self.root/'.game/save.json';private.parent.mkdir();private.write_text(json.dumps(self.data))
        database=self.root/'state.sqlite3';database.write_text('not a manifest')
        for path in ('../manifest.json','.game/save.json','state.sqlite3'):
            with self.subTest(path=path), patch.object(Path,'read_bytes',side_effect=AssertionError('private input read')):
                report=audit_tool.audit(path,root=self.root)
                self.assertIn('MANIFEST_INVALID',self.codes(report))

    def test_loader_failure_is_an_error_not_an_empty_pass(self):
        def fail(_):raise ValueError('broken registered reference')
        report=audit_tool.audit('manifest.json',root=self.root,loader=fail)
        self.assertIn('REGISTRY_LOAD_FAILED',self.codes(report))
        self.assertEqual(report['status'],'ERROR')
        self.assertEqual(audit_tool.exit_code(report),1)

    def test_unsealed_registry_and_content_version_mismatch_fail(self):
        self.assertIn('REGISTRY_UNSEALED',self.codes(self.run_audit(fake=registry(sealed=False))))
        self.assertIn('CONTENT_VERSION_MISMATCH',self.codes(self.run_audit(fake=registry(version='future'))))

    def test_duplicate_definition_and_missing_reference_are_located(self):
        item=Definition('resources','sample','Sample',(DefinitionKey('resources','missing'),))
        report=self.run_audit((item,item))
        self.assertTrue({'DEFINITION_DUPLICATE','REFERENCE_MISSING'}<=self.codes(report))
        self.assertTrue(any(x['path']=='resources:sample' and x['code']=='REFERENCE_MISSING' for x in report['issues']))

    def test_recipe_whitelist_detects_missing_duplicate_and_invalid_ids(self):
        recipe=Definition('production','known','Known')
        report=self.run_audit((recipe,),('known','known','missing',123))
        self.assertTrue({'RECIPE_DUPLICATE','RECIPE_UNREGISTERED','RECIPE_INVALID'}<=self.codes(report))

    def test_registered_unopened_recipe_is_counted_not_auto_enabled(self):
        report=self.run_audit((Definition('production','unopened','Unopened'),))
        self.assertEqual(report['status'],'PASS')
        self.assertEqual(report['counts']['registered_recipes_not_whitelisted'],1)

    def test_undeclared_json_is_warned_without_independent_parsing(self):
        (self.source.parent/'unlisted.json').write_text('this is deliberately invalid JSON')
        report=self.run_audit()
        self.assertEqual(report['status'],'WARNING')
        self.assertEqual(report['coverage']['undeclared_sources'],['src/data/unlisted.json'])
        self.assertEqual(report['coverage']['checked_sources'],['src/data/sample.json'])
        self.assertEqual(audit_tool.exit_code(report),0)

    def test_profile_failure_on_unlisted_dependency_cannot_report_success(self):
        unlisted=self.source.parent/'unlisted.json';unlisted.write_text('invalid JSON')
        def load(_):
            json.loads(unlisted.read_text())
            return registry(), ()
        report=audit_tool.audit('manifest.json',root=self.root,loader=load)
        self.assertIn('REGISTRY_LOAD_FAILED',self.codes(report))
        self.assertEqual(report['status'],'ERROR')
        self.assertTrue(any(x['code']=='SOURCE_UNDECLARED' for x in report['issues']))

    def test_source_or_manifest_changed_during_load_is_rejected(self):
        for target in (self.source,self.manifest):
            with self.subTest(target=target):
                self.write_manifest();self.source.write_text('{"schema_version":1}')
                def load(_):
                    target.write_text(target.read_text()+' ')
                    return registry(), ()
                report=audit_tool.audit('manifest.json',root=self.root,loader=load)
                self.assertIn('INPUT_CHANGED',self.codes(report))
                self.assertEqual(audit_tool.exit_code(report),1)

    def test_manifest_removed_during_source_read_returns_structured_error(self):
        original = audit_tool.read_json
        def read(path):
            result = original(path)
            if path == self.source:
                self.manifest.unlink()
            return result
        with patch.object(audit_tool, 'read_json', side_effect=read):
            report = self.run_audit()
        self.assertIn('INPUT_CHANGED', self.codes(report))
        self.assertEqual(report['status'], 'ERROR')

    def test_pending_resource_tier_is_explicit_nonblocking_warning(self):
        item=ResourceDefinition('resources','sample','Sample')
        report=self.run_audit((item,))
        self.assertEqual(report['status'],'WARNING');self.assertEqual(audit_tool.exit_code(report),0)
        self.assertTrue(any(x['code']=='RESOURCE_TIER_PENDING' for x in report['issues']))

    def test_cli_failure_has_json_report_and_nonzero_exit(self):
        stream=io.StringIO()
        with redirect_stdout(stream):status=audit_tool.main(['--manifest','../outside.json','--json'])
        report=json.loads(stream.getvalue())
        self.assertEqual(status,1);self.assertEqual(report['status'],'ERROR')

    def test_current_registry_sources_unchanged_and_report_deterministic(self):
        root=audit_tool.ROOT
        files=tuple(sorted(p for p in (root/'src/data').rglob('*.json')
                           if p != root/audit_tool.DEFAULT_MANIFEST))
        before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
        first=audit_tool.audit();second=audit_tool.audit()
        self.assertEqual(first,second)
        self.assertEqual(self.codes(first),set())
        self.assertEqual(first['target']['loaded_content_version'],first['target']['expected_content_version'])
        self.assertGreater(first['counts']['by_domain']['resources'],0)
        self.assertGreater(first['counts']['by_domain']['equipment'],0)
        self.assertGreater(first['counts']['production_whitelist'],0)
        self.assertEqual(first['coverage']['undeclared_sources'],[])
        self.assertEqual(len(first['coverage']['checked_sources']),len(files))
        self.assertEqual(before,{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files})

    def test_direct_cli_from_other_directory_creates_no_files(self):
        root=audit_tool.ROOT
        watch=[root/'src',root/'tools/economy']
        caches={str(p) for base in watch for p in base.rglob('*.pyc')}
        child=subprocess.run([sys.executable,'-B',str(Path(audit_tool.__file__)),'--json'],
                             cwd=self.root,capture_output=True,text=True,timeout=30)
        self.assertEqual(child.returncode,0,child.stderr)
        report=json.loads(child.stdout)
        self.assertNotEqual(report['status'],'ERROR')
        self.assertEqual(child.stderr,'')
        self.assertEqual(caches,{str(p) for base in watch for p in base.rglob('*.pyc')})
        self.assertEqual(sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*') if p.is_file()),
                         ['manifest.json','src/data/sample.json'])


if __name__ == '__main__':
    unittest.main()

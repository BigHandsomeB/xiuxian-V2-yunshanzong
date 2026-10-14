"""Current item exports and immutable generation provenance; no live asset mutations."""
import copy,hashlib,io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from tools.asset_manager.catalog import Catalog,PROJECT
from tools.asset_manager.model import REVIEW,AssetError,templates
from tools.asset_manager.specs import freeze_spec,export_spec
from tools.asset_manager.workflow import prepare,confirm
from tools.asset_manager.web import create_app

ITEMS=['resource_icon_v1','material_icon_v1','pill_icon_v1','equipment_icon_v1','herb_icon_v1']
class ItemExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=PROJECT/'tests');self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.path=self.root/'templates.json'
        self.doc=json.loads((PROJECT/'assets/templates/templates.json').read_text())
        # Simulate a historical source generated under the old resource profile.
        old=copy.deepcopy(self.doc);p=old['pixel_size_profiles']['material_icon_v1']
        p.update(version=1,subject_logic_size=[24,24],subject_options=[[24,24],[32,32]])
        p['runtime_profile']['frame_size']=[24,24]
        for t in old['templates']:
            if t['template_id']=='resource_icon_v1':t['template_version']=2;t.pop('runtime_export_policy',None)
        self.path.write_text(json.dumps(old));self.c=Catalog(self.root/'assets',self.path)
        self.a=self.c.create_named('resource_icon_v1','玄铁矿')
        self.p=self.c.prompt('resource_icon_v1',{},asset_id=self.a['asset_id'])
        im=Image.new('RGBA',(96,96));im.paste((200,80,30,255),(36,36,60,60))
        # Distinct source pixels ensure nearest export never invents intermediate colors.
        im.putpixel((40,40),(30,200,80,255));out=io.BytesIO();im.save(out,format='PNG')
        self.s=self.c.upload('ore.png',out.getvalue(),'resource_icon_v1',prompt_id=self.p['prompt_id'])
        self.v=self.c.import_version(self.a['asset_id'],self.c.plan(self.s['source_id'],mode='independent'),True)
        self.c.review(self.a['asset_id'],1,'needs_review');self.c.review(self.a['asset_id'],1,'approved',dict.fromkeys(REVIEW,True));self.c.select(self.a['asset_id'],1)
        self.old_build=self.c.build(self.a['asset_id'],1);self.c.publish()
        self.path.write_text(json.dumps(self.doc));self.c=Catalog(self.root/'assets',self.path)
    def rebuild(self):return self.c.build(self.a['asset_id'],1,export_policy='current_item_profile')
    def test_all_five_item_defaults_and_source_cells(self):
        current=templates(self.doc)
        for tid in ITEMS:
            with self.subTest(template=tid):
                s=freeze_spec(current[tid]);self.assertEqual(s['subject_logic_size'],[48,48]);self.assertEqual(s['runtime_profile']['frame_size'],[48,48]);self.assertEqual(s['source_cell_size'],[96,96]);self.assertEqual(s['inner_safe_padding'],24)
    def test_navigation_and_scene_and_sprite_profiles_unchanged(self):
        ts=templates(self.doc)
        for tid,opts,target in [('environment_scene_v1',{'family':'navigation'},[24,24]),('character_compact_v1',{},[128,128]),('building_interior_scene_v1',{},[256,144])]:
            self.assertEqual(freeze_spec(ts[tid],opts)['runtime_profile']['frame_size'],target)
    def test_old_prompt_source_and_mapping_immutable_after_export(self):
        before=self.c.get('asset',self.a['asset_id'])['versions'][0];self.rebuild();after=self.c.get('asset',self.a['asset_id'])
        self.assertEqual(self.c.get('prompt',self.p['prompt_id']),self.p);self.assertEqual(self.c.get('source',self.s['source_id']),self.s)
        for k in ('version','files','plan','frozen_spec','source_id','prompt_id','review','approved_at'):self.assertEqual(after['versions'][0][k],before[k])
        self.assertEqual(after['asset_id'],self.a['asset_id']);self.assertEqual(len(after['versions']),1)
    def test_new_build_is_48_and_old_file_and_history_retained(self):
        b=self.rebuild();self.assertEqual(b['build_version'],2)
        with Image.open(self.c.path(b['files'][0]['file'])) as im:self.assertEqual(im.size,(48,48))
        history=self.c.get('asset',self.a['asset_id'])['versions'][0]['runtime_build_history']
        self.assertEqual([h['profile']['frame_size'] for h in history],[[24,24],[48,48]])
        f=self.old_build['files'][0];self.assertEqual(hashlib.sha256(self.c.path(f['file']).read_bytes()).hexdigest(),f['sha256'])
    def test_manifest_current_profile_and_build_version(self):
        b=self.rebuild();m=self.c.publish()['assets'][self.a['asset_id']]
        self.assertEqual(m['runtime_profile']['frame_size'],[48,48]);self.assertEqual(m['build_version'],2)
        self.assertEqual(m['export_origin']['template_version'],4);self.assertEqual(m['export_origin']['pixel_profile_version'],2);self.assertEqual(m['files'],b['files'])
    def test_nearest_preserves_palette_and_original_crop_fraction(self):
        b=self.rebuild()
        with Image.open(self.c.path(b['files'][0]['file'])) as im:
            self.assertNotIn((0,0,0,0),set(im.get_flattened_data()))
            self.assertEqual(set(im.get_flattened_data()),{(200,80,30,255),(30,200,80,255)})
    def test_explicit_historical_build_can_still_use_frozen_policy(self):
        b=self.c.build(self.a['asset_id'],1,export_policy='frozen');self.assertEqual(b['profile']['frame_size'],[24,24]);self.assertEqual(b['export_origin']['policy'],'frozen')
    def test_export_rejects_wrong_size_or_unknown_policy(self):
        for params in ({'width':24,'height':24,'export_policy':'current_item_profile'},{'export_policy':'guess'}):
            with self.assertRaises(AssetError):self.c.build(self.a['asset_id'],1,**params)
    def test_export_failure_retains_previous_build_and_manifest(self):
        before=self.c.get('asset',self.a['asset_id']);manifest=self.c.path('manifest.json').read_bytes()
        with patch('tools.asset_manager.images.profiled_runtime',side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):self.rebuild()
        self.assertEqual(self.c.get('asset',self.a['asset_id']),before);self.assertEqual(self.c.path('manifest.json').read_bytes(),manifest)
    def test_quick_preview_shows_new_export_and_generation_stays_24(self):
        p=prepare(self.c,targets=[{'asset_id':self.a['asset_id'],'version':1}]);item=p['items'][0]
        self.assertTrue(item['valid']);self.assertEqual(item['frozen_spec']['runtime_profile']['frame_size'],[24,24]);self.assertEqual(item['runtime_spec']['runtime_profile']['frame_size'],[48,48])
        r=confirm(self.c,p['preview_id'],True);self.assertEqual(r['assets'][0]['status'],'approved')
        self.assertEqual(self.c.get('prompt',self.p['prompt_id']),self.p);self.assertEqual(self.c.publish()['assets'][self.a['asset_id']]['runtime_profile']['frame_size'],[48,48])
    def test_export_profile_change_after_preview_requires_new_preview(self):
        p=prepare(self.c,targets=[{'asset_id':self.a['asset_id'],'version':1}]);self.c.templates['resource_icon_v1']['template_version']+=1
        r=confirm(self.c,p['preview_id'],True);self.assertEqual(r['assets'][0]['status'],'needs_review');self.assertEqual(self.c.get('asset',self.a['asset_id'])['versions'][0]['runtime'],self.old_build)
    def test_web_detail_exposes_generation_and_current_export_and_prompt_sizes(self):
        app=create_app(self.root/'assets','x'*32);client=app.test_client();h={'Authorization':'Bearer '+'x'*32}
        data=client.get('/api/state',headers=h).get_json();a=next(a for a in data['assets'] if a['asset_id']==self.a['asset_id'])
        self.assertEqual(a['size_provenance']['spec']['runtime_profile']['frame_size'],[24,24]);self.assertEqual(a['runtime_export_spec']['runtime_profile']['frame_size'],[48,48])
        for tid in ITEMS:
            p=client.post('/api/prompts',json={'template_id':tid,'options':{}},headers=h).get_json()
            self.assertIn('48x48',p['text']);self.assertEqual(p['frozen_spec']['source_cell_size'],[96,96])
    def test_export_disallowed_for_navigation_or_dynamic(self):
        for tid,options in [('environment_scene_v1',{'family':'navigation'}),('character_compact_v1',{})]:
            ts=templates(self.doc);s=freeze_spec(ts[tid],options)
            with self.assertRaises(AssetError):export_spec(ts[tid],s,'current_item_profile')
    def test_restart_retains_build_history_and_selected_manifest(self):
        self.rebuild();self.c.publish();fresh=Catalog(self.root/'assets',self.path)
        self.assertEqual(fresh.get('asset',self.a['asset_id'])['versions'][0]['runtime_build_history'][-1]['profile']['frame_size'],[48,48]);self.assertEqual(fresh.get('prompt',self.p['prompt_id']),self.p)

    def test_item_master_in_state_is_not_a_runtime_icon(self):
        self.c.create_asset('icon.ore.master','矿石视觉基准','resource_icon_v1',state='master')
        app=create_app(self.root/'assets','x'*32);r=app.test_client().get('/api/state',headers={'Authorization':'Bearer '+'x'*32})
        self.assertEqual(r.status_code,200);a=next(a for a in r.get_json()['assets'] if a['asset_id']=='icon.ore.master')
        self.assertEqual(a['runtime_export_origin']['policy'],'frozen')

    def test_default_builder_also_uses_current_item_authority(self):
        b=self.c.build(self.a['asset_id'],1)
        self.assertEqual(b['profile']['frame_size'],[48,48]);self.assertEqual(b['export_origin']['policy'],'current_item_profile')

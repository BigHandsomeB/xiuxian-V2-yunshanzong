"""Lifecycle tests use isolated V2 fixtures; no real user assets are modified."""
import copy,hashlib,io,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from tools.asset_manager.catalog import Catalog,PROJECT
from tools.asset_manager.model import REVIEW,AssetError
from tools.asset_manager.web import create_app
from tools.asset_manager.lifecycle import prepare,apply,inspect,safe_file

class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=PROJECT/'tests');self.addCleanup(self.tmp.cleanup)
        self.c=Catalog(Path(self.tmp.name)/'assets');self.g=self.c.create_named('resource_icon_v1','宗门矿石','set',['玄铁矿','赤铜矿','寒铁矿','灵晶矿','赤炎矿','星陨矿'],'sheet')
        self.p=self.c.prompt('resource_icon_v1',{},set_id=self.g['set_id']);self.ids=self.g['asset_ids'];self.aid=self.ids[0]
        image=Image.new('RGBA',(352,224),(80,120,50,255));out=io.BytesIO();image.save(out,format='PNG');self.bytes=out.getvalue()
        self.s=self.c.upload('ore.png',self.bytes,'resource_icon_v1',self.g['set_id'],self.p['prompt_id'])
        self.c.import_static_set(self.c.plan(self.s['source_id']),True)
        for aid in self.ids:
            self.c.review(aid,1,'needs_review');self.c.review(aid,1,'approved',dict.fromkeys(REVIEW,True));self.c.build(aid,1);self.c.select(aid,1)
        # These lifecycle cases exercise retained originals; auto-retirement is tested separately.
        with patch.object(self.c, "clean_source_files"):
            self.c.publish()
        self.s=self.c.get("source",self.s["source_id"])
    def preview(self,op,key=None,kind='asset'):return prepare(self.c,kind,key or self.aid,op)
    def do(self,op,key=None,kind='asset',**opts):
        p=self.preview(op,key,kind);return apply(self.c,p['confirmation_id'],True,**opts)
    def manifest(self):return json.loads(self.c.path('manifest.json').read_text())['assets']
    def test_deprecate_single_retains_files_and_other_five(self):
        before=self.c.get('asset',self.aid);self.do('deprecate_asset')
        self.assertNotIn(self.aid,self.manifest());self.assertEqual(set(self.manifest()),set(self.ids[1:]));self.assertEqual(len(self.c.search()),len(self.c.list('asset'))-1)
        a=self.c.get('asset',self.aid);self.assertEqual(a['lifecycle_status'],'deprecated');self.assertTrue(self.c.path(before['versions'][0]['runtime']['files'][0]['file']).exists());self.assertEqual(self.c.get('source',self.s['source_id']),self.s)
        with self.assertRaises(AssetError):self.c.build(self.aid,1)
    def test_restore_stable_id_needs_review_without_republish(self):
        self.do('deprecate_asset');self.do('restore_asset');a=self.c.get('asset',self.aid)
        self.assertEqual(a['asset_id'],self.aid);self.assertEqual(a['versions'][0]['art_status'],'needs_review');self.assertIsNone(a['current_approved_version']);self.assertNotIn(self.aid,self.c.publish()['assets']);self.assertTrue(a['versions'][0]['runtime'])
    def test_empty_asset_deprecation_hidden_and_restorable(self):
        a=self.c.create_named('resource_icon_v1','空素材');self.do('deprecate_asset',a['asset_id']);self.assertNotIn(a['asset_id'],[a['asset_id'] for a in self.c.search()]);self.do('restore_asset',a['asset_id']);self.assertEqual(self.c.get('asset',a['asset_id'])['lifecycle_status'],'active')
    def test_explicit_filter_includes_deprecated(self):
        self.do('deprecate_asset');self.assertIn(self.aid,[a['asset_id'] for a in self.c.search(art_status='deprecated')]);self.assertIn(self.aid,[a['asset_id'] for a in self.c.search(include_deprecated=True)])
    def test_detach_preserves_asset_source_runtime_prompt(self):
        before=self.c.get('asset',self.aid);m=self.manifest();self.do('detach_asset');a=self.c.get('asset',self.aid)
        self.assertIsNone(a['set_id']);self.assertEqual(a['versions'],before['versions']);self.assertEqual(m,self.manifest());self.assertEqual(self.c.get('prompt',self.p['prompt_id']),self.p);self.assertEqual(self.c.get('source',self.s['source_id']),self.s);self.assertEqual(self.c.completeness(self.g['set_id'])['total'],5)
    def scene_bootstrap(self):
        # Standalone distributions intentionally ship an empty seed; this test owns its fixture.
        self.scene_seed=self.c.root.parent/'scene-seed.json'
        row={'set_id':'scene_set.danding.interior.v1','name_zh':'测试丹鼎阁','template_id':'building_interior_scene_v1',
             'states':['prepare','measure','add_herbs','stable','high_fire','finish'],'asset_prefix':'scene.building.test.danding'}
        self.scene_seed.write_text(json.dumps({'schema_version':1,'sets':[row]}))
        self.c=Catalog(self.c.root,seed_file=self.scene_seed)
    def test_scene_detach_keeps_required_empty_slot(self):
        self.scene_bootstrap()
        g=self.c.get('set','scene_set.danding.interior.v1');aid=g['asset_prefix']+'.prepare';self.do('detach_asset',aid);s=self.c.completeness(g['set_id']);self.assertIsNone(s['slots']['prepare']['asset_id']);self.assertEqual(s['total'],6)
    def test_source_reference_blocks_delete_even_after_deprecation(self):
        p=self.preview('delete_source',self.s['source_id'],'source');self.assertTrue(p['force_blockers'])
        with self.assertRaises(AssetError):apply(self.c,p['confirmation_id'],True)
        self.do('deprecate_set_members',self.g['set_id'],'set')
        with self.assertRaises(AssetError):self.c.delete_source(self.s['source_id'])
        self.assertTrue(self.c.path(self.s['file']).exists())
    def test_unreferenced_source_delete_preserves_prompt_and_assets(self):
        s=self.c.upload('unused.png',self.bytes,'resource_icon_v1');ids=list(self.ids);self.do('delete_source',s['source_id'],'source');self.assertIsNone(self.c.get('source',s['source_id'],missing=True));self.assertFalse(self.c.path(s['file']).exists());self.assertEqual(self.c.get('prompt',self.p['prompt_id']),self.p);self.assertEqual(set(self.manifest()),set(ids))
    def test_referenced_approved_asset_cannot_hard_delete(self):
        p=self.preview('purge_asset');self.assertTrue(p['blockers']);self.assertTrue(p['force_blockers'])
        with self.assertRaises(AssetError):apply(self.c,p['confirmation_id'],True,force=True,force_confirmed=True,confirmation_text='永久删除')
        self.assertIsNotNone(self.c.get('asset',self.aid))
    def test_unreferenced_draft_hard_delete_and_id_reservation(self):
        a=self.c.create_named('resource_icon_v1','可删除草稿');self.do('purge_asset',a['asset_id'],confirmation_text='永久删除');self.assertIsNone(self.c.get('asset',a['asset_id'],missing=True))
        with self.assertRaises(AssetError):self.c.create_asset(a['asset_id'],'重复ID','resource_icon_v1')
        again=self.c.create_named('resource_icon_v1','可删除草稿');self.assertNotEqual(again['asset_id'],a['asset_id'])
    def test_force_requires_second_confirmation_and_chinese_phrase(self):
        self.do('detach_asset');p=self.preview('purge_asset');self.assertEqual(p['confirmation_phrase'],'永久删除')
        for kwargs in [dict(confirmation_text='永久删除'),dict(force=True,confirmation_text='永久删除'),*[dict(force=True,force_confirmed=True,confirmation_text=value) for value in ('wrong','永久删',self.aid)]]:
            with self.assertRaises(AssetError):apply(self.c,p['confirmation_id'],True,**kwargs)
        apply(self.c,p['confirmation_id'],True,force=True,force_confirmed=True,confirmation_text='永久删除')
        self.assertIsNone(self.c.get('asset',self.aid,missing=True));self.assertNotIn(self.aid,self.manifest());self.assertEqual(self.c.get('source',self.s['source_id']),self.s);self.assertEqual(self.c.get('prompt',self.p['prompt_id']),self.p)
    def test_set_deprecation_does_not_deprecate_members(self):
        before=self.manifest();self.do('deprecate_set',self.g['set_id'],'set');self.assertEqual(self.c.get('set',self.g['set_id'])['status'],'deprecated');self.assertEqual(self.manifest(),before);self.assertTrue(all(self.c.get('asset',aid)['versions'][0]['art_status']=='approved' for aid in self.ids))
    def test_set_restore_keeps_member_facts(self):
        self.do('deprecate_set',self.g['set_id'],'set');self.do('restore_set',self.g['set_id'],'set');self.assertEqual(self.c.get('set',self.g['set_id'])['status'],'active');self.assertEqual(len(self.manifest()),6)
    def test_dissolve_set_keeps_six_members_and_history(self):
        self.do('dissolve_set',self.g['set_id'],'set');g=self.c.get('set',self.g['set_id']);self.assertEqual(g['status'],'dissolved');self.assertEqual(g['asset_ids'],[]);self.assertEqual(g['previous_member_ids'],self.ids);self.assertTrue(all(self.c.get('asset',aid)['set_id'] is None for aid in self.ids));self.assertEqual(len(self.manifest()),6);self.assertEqual(self.c.get('prompt',self.p['prompt_id']),self.p)
    def test_deprecate_group_and_members_is_soft(self):
        self.do('deprecate_set_members',self.g['set_id'],'set');self.assertEqual(self.manifest(),{});self.assertTrue(self.c.path(self.s['file']).exists());self.assertTrue(all(self.c.get('asset',aid)['lifecycle_status']=='deprecated' for aid in self.ids))
    def test_set_purge_lists_external_master_blocker(self):
        outside=self.c.create_named('resource_icon_v1','外部引用')
        with self.c.transaction() as conn:
            a=self.c.get('asset',outside['asset_id'],conn);v=copy.deepcopy(self.c.get('asset',self.aid,conn)['versions'][0]);v['master_asset']=self.aid;a['versions']=[v];self.c.put('asset',a['asset_id'],a,conn)
        p=self.preview('purge_set_members',self.g['set_id'],'set');self.assertTrue(any(b['asset_id']==self.aid for b in p['force_blockers']))
        with self.assertRaises(AssetError):apply(self.c,p['confirmation_id'],True,force=True,force_confirmed=True,confirmation_text='永久删除')
    def test_other_group_reference_blocks_force_delete(self):
        g=self.c.create_named('resource_icon_v1','外部组','set',['材料'])
        with self.c.transaction() as conn:g['asset_ids'].append(self.aid);self.c.put('set',g['set_id'],g,conn)
        p=self.preview('purge_set_members',self.g['set_id'],'set');self.assertTrue(p['force_blockers'])
    def test_default_set_purge_requires_force_for_approved_history(self):
        p=self.preview('purge_set_members',self.g['set_id'],'set')
        with self.assertRaises(AssetError):apply(self.c,p['confirmation_id'],True,confirmation_text='永久删除')
        apply(self.c,p['confirmation_id'],True,force=True,force_confirmed=True,confirmation_text='永久删除');self.assertTrue(all(self.c.get('asset',aid,missing=True) is None for aid in self.ids));self.assertEqual(self.manifest(),{});self.assertIsNotNone(self.c.get('prompt',self.p['prompt_id']))
    def test_empty_bootstrap_purge_does_not_resurrect_on_restart(self):
        self.scene_bootstrap()
        sid='scene_set.danding.interior.v1';self.do('purge_set_members',sid,'set',confirmation_text='永久删除');fresh=Catalog(self.c.root,seed_file=self.scene_seed);self.assertIsNone(fresh.get('set',sid,missing=True))
    def test_container_purge_retains_members(self):
        sid=self.g['set_id'];self.do('purge_set',sid,'set',force=True,force_confirmed=True,confirmation_text='永久删除');self.assertIsNone(self.c.get('set',sid,missing=True));self.assertTrue(all(self.c.get('asset',aid)['set_id'] is None for aid in self.ids));self.assertEqual(len(self.manifest()),6)
    def test_runtime_cleanup_only_after_deprecation_retains_source_and_components(self):
        file=self.c.get('asset',self.aid)['versions'][0]['runtime']['files'][0]['file']
        p=self.preview('clean_runtime')
        with self.assertRaises(AssetError):apply(self.c,p['confirmation_id'],True)
        self.do('deprecate_asset');self.do('clean_runtime');a=self.c.get('asset',self.aid);self.assertIsNone(a['versions'][0]['runtime']);self.assertFalse(self.c.path(file).exists());self.assertTrue(self.c.path(a['versions'][0]['files'][0]['file']).exists());self.assertTrue(self.c.path(self.s['file']).exists())
    def test_path_traversal_key_rejected(self):
        for key in ['../assets','/root/code']:
            with self.assertRaises(AssetError):self.preview('purge_asset',key)
    def test_registry_image_role_cannot_delete_source_code(self):
        a=self.c.create_named('resource_icon_v1','恶意路径')
        with self.c.transaction() as conn:
            a['versions']=[dict(version=1,art_status='draft',source_id=self.s['source_id'],files=[dict(file='../tools/asset_manager/catalog.py',sha256='bad')],runtime=None)];self.c.put('asset',a['asset_id'],a,conn)
        with self.assertRaises(AssetError):self.preview('purge_asset',a['asset_id'])
    def test_symlink_delete_escape_rejected(self):
        s=self.c.upload('unused.png',self.bytes,'resource_icon_v1');f=self.c.path(s['file']);f.unlink();f.symlink_to(PROJECT/'tools/asset_manager/catalog.py')
        with self.assertRaises(AssetError):self.preview('delete_source',s['source_id'],'source')
    def test_hardlink_delete_rejected(self):
        s=self.c.upload('unused.png',self.bytes,'resource_icon_v1');f=self.c.path(s['file']);other=self.c.path('source/files/hardlink.png');os.link(f,other)
        with self.assertRaises(AssetError):self.preview('delete_source',s['source_id'],'source')
    def test_stale_impact_summary_rejected(self):
        p=self.preview('deprecate_asset');self.c.rename(self.aid,'改名')
        with self.assertRaises(AssetError):apply(self.c,p['confirmation_id'],True)
        self.assertIn(self.aid,self.manifest())
    def test_explicit_action_required_and_repeat_is_not_duplicate(self):
        p=self.preview('deprecate_asset')
        for flag in [False,None,1]:
            with self.assertRaises(AssetError):apply(self.c,p['confirmation_id'],flag)
        first=apply(self.c,p['confirmation_id'],True);count=len(self.c.list('audit'));self.assertEqual(apply(self.c,p['confirmation_id'],True),first);self.assertEqual(len(self.c.list('audit')),count)
    def test_audit_impact_and_summary_six_correct(self):
        p=self.preview('deprecate_set_members',self.g['set_id'],'set');self.assertEqual((p['asset_count'],p['approved'],p['runtime'],p['manifest_count']),(6,6,6,6));self.assertEqual(p['file_count'],0)
        r=apply(self.c,p['confirmation_id'],True);event=self.c.get('audit',r['audit_id']);self.assertEqual(event['operation'],'deprecate_set_members');self.assertEqual(set(event['manifest_change']),set(self.ids));self.assertEqual(event['new_status'],'deprecated')
    def test_registry_export_and_restart_preserve_audit(self):
        r=self.do('deprecate_asset');fresh=Catalog(self.c.root);self.assertEqual(fresh.get('audit',r['audit_id'])['key'],self.aid);self.assertNotIn(self.aid,fresh.publish()['assets']);self.assertTrue(fresh.export_registry()['lifecycle_audit'])
    def test_physical_move_failure_rolls_back_metadata_and_files(self):
        self.do('detach_asset');p=self.preview('purge_asset');original=os.replace;calls=[]
        def fail(src,dst):
            if '.deletion' in Path(dst).parts:
                calls.append(str(src))
                if len(calls)==2:raise OSError('disk failure')
            return original(src,dst)
        with patch('tools.asset_manager.lifecycle.os.replace',side_effect=fail):
            with self.assertRaises(OSError):apply(self.c,p['confirmation_id'],True,force=True,force_confirmed=True,confirmation_text='永久删除')
        a=self.c.get('asset',self.aid);self.assertTrue(all(self.c.path(f['file']).exists() for f in a['versions'][0]['files']));self.assertTrue(self.c.path(a['versions'][0]['runtime']['files'][0]['file']).exists())
    def test_web_requires_auth_csrf_and_server_actor(self):
        app=create_app(self.c.root,'x'*32);client=app.test_client()
        self.assertEqual(client.post('/api/lifecycle-confirm',json={}).status_code,401)
        client.post('/login',data={'token':'x'*32});self.assertEqual(client.post('/api/lifecycle-preview',json={}).status_code,403)
        h={'Authorization':'Bearer '+'x'*32};p=client.post('/api/lifecycle-preview',json={'kind':'set','key':self.g['set_id'],'operation':'deprecate_set'},headers=h).get_json()
        self.assertEqual(client.post('/api/lifecycle-confirm',json={'confirmation_id':p['confirmation_id'],'confirmed':True,'actor':'spoof'},headers=h).status_code,400)
        self.assertEqual(client.post('/api/lifecycle-confirm',json={'confirmation_id':p['confirmation_id'],'confirmed':True},headers=h).status_code,200)
    def test_source_shared_managed_file_is_not_deleted(self):
        s=self.c.upload('unused.png',self.bytes,'resource_icon_v1')
        with self.c.transaction() as conn:
            a=self.c.get('asset',self.aid,conn);a['versions'][0]['files'][0].update(file=s['file'],sha256=s['sha256']);self.c.put('asset',self.aid,a,conn)
        p=self.preview('delete_source',s['source_id'],'source');self.assertTrue(p['force_blockers'])

    def test_source_impact_exposes_retained_assets_after_container_purge(self):
        self.do('purge_set',self.g['set_id'],'set',force=True,force_confirmed=True,confirmation_text='永久删除')
        p=self.preview('delete_source',self.s['source_id'],'source')
        refs=p['referencing_assets']
        self.assertEqual({a['asset_id'] for a in refs},set(self.ids))
        self.assertEqual(p['reference_asset_count'],6)
        self.assertTrue(all(a['set_id'] is None and a['lifecycle_status']=='active' for a in refs))
        self.assertTrue(all(a['version_numbers']==[1] and a['approved_version_numbers']==[1] for a in refs))
        with self.assertRaises(AssetError):apply(self.c,p['confirmation_id'],True)
        self.assertTrue(self.c.path(self.s['file']).exists())

    def test_source_deletable_after_retained_assets_permanently_removed(self):
        self.do('purge_set',self.g['set_id'],'set',force=True,force_confirmed=True,confirmation_text='永久删除')
        for aid in self.ids:self.do('purge_asset',aid,force=True,force_confirmed=True,confirmation_text='永久删除')
        p=self.preview('delete_source',self.s['source_id'],'source')
        self.assertEqual(p['referencing_assets'],[]);self.assertEqual(p['reference_asset_count'],0);self.assertEqual(p['force_blockers'],[])
        apply(self.c,p['confirmation_id'],True)
        self.assertIsNone(self.c.get('source',self.s['source_id'],missing=True));self.assertFalse(self.c.path(self.s['file']).exists())
        self.assertIsNotNone(self.c.get('prompt',self.p['prompt_id']))

    def test_deleted_assets_preview_no_longer_blocks_source_deletion(self):
        from tools.asset_manager.workflow import prepare as prepare_review
        review=prepare_review(self.c,targets=[dict(asset_id=aid,version=1) for aid in self.ids])
        self.do('purge_set_members',self.g['set_id'],'set',force=True,force_confirmed=True,confirmation_text='永久删除')
        p=self.preview('delete_source',self.s['source_id'],'source')
        self.assertEqual(p['force_blockers'],[])
        self.assertEqual(p['retired_preview_ids'],[review['preview_id']])
        apply(self.c,p['confirmation_id'],True)
        self.assertIsNone(self.c.get('source',self.s['source_id'],missing=True))
        self.assertEqual(self.c.get('preview',review['preview_id'])['lifecycle_status'],'retired')

    def make_review_preview(self):
        from tools.asset_manager.workflow import prepare as review_preview
        return review_preview(self.c,targets=[dict(asset_id=aid,version=1) for aid in self.ids])

    def test_pending_preview_only_cancelled_by_explicit_source_delete_confirmation(self):
        s=self.c.upload('pending.png',self.bytes,'resource_icon_v1',self.g['set_id'],self.p['prompt_id'])
        from tools.asset_manager.workflow import prepare as review_preview
        review=review_preview(self.c,source_id=s['source_id'],mode='grid',options=s['frozen_spec']['grid_spec'],regions=self.c.plan(s['source_id'])['regions'])
        p=self.preview('delete_source',s['source_id'],'source')
        self.assertEqual(p['pending_preview_count'],1);self.assertFalse(p['force_blockers']);self.assertEqual(p['retired_preview_ids'],[review['preview_id']])
        with self.assertRaises(AssetError):apply(self.c,p['confirmation_id'],False)
        self.assertTrue(self.c.path(s['file']).exists());self.assertNotEqual(self.c.get('preview',review['preview_id']).get('lifecycle_status'),'retired')
        before=[self.c.get('asset',aid) for aid in self.ids]
        apply(self.c,p['confirmation_id'],True)
        self.assertEqual([self.c.get('asset',aid) for aid in self.ids],before);self.assertEqual(self.c.get('preview',review['preview_id'])['lifecycle_status'],'retired')

    def test_expired_preview_without_asset_source_reference_can_retire(self):
        s=self.c.upload('expired.png',self.bytes,'resource_icon_v1',self.g['set_id'],self.p['prompt_id'])
        from tools.asset_manager.workflow import prepare as review_preview
        review=review_preview(self.c,source_id=s['source_id'],mode='grid',options=s['frozen_spec']['grid_spec'],regions=self.c.plan(s['source_id'])['regions'])
        with self.c.transaction() as conn:
            review['expires_at']='2000-01-01T00:00:00+00:00';self.c.put('preview',review['preview_id'],review,conn)
        p=self.preview('delete_source',s['source_id'],'source');self.assertFalse(p['force_blockers']);self.assertEqual(p['retired_preview_ids'],[review['preview_id']])
        apply(self.c,p['confirmation_id'],True)
        self.assertTrue(all(self.c.get('asset',a) for a in self.ids))

    def test_confirmed_preview_does_not_replace_real_asset_protection(self):
        review=self.make_review_preview()
        from tools.asset_manager.workflow import confirm
        confirm(self.c,review['preview_id'],True)
        p=self.preview('delete_source',self.s['source_id'],'source')
        self.assertIn(review['preview_id'],p['retired_preview_ids']);self.assertTrue(p['force_blockers']);self.assertEqual(p['reference_asset_count'],6)

    def test_invalid_previews_retire_keep_audit_and_cannot_reconfirm(self):
        review=self.make_review_preview();original=copy.deepcopy(review)
        paths=[f['runtime_preview']['file'] for i in review['items'] for f in i['preview_files'] if f.get('runtime_preview')]
        self.do('purge_set_members',self.g['set_id'],'set',force=True,force_confirmed=True,confirmation_text='永久删除')
        p=self.preview('delete_source',self.s['source_id'],'source');r=apply(self.c,p['confirmation_id'],True)
        retired=self.c.get('preview',review['preview_id']);self.assertEqual(retired['items'],original['items']);self.assertEqual(retired['lifecycle_status'],'retired');self.assertTrue(all(not self.c.path(f).exists() for f in paths))
        self.assertEqual(self.c.get('audit',r['audit_id'])['retired_preview_ids'],[review['preview_id']])
        from tools.asset_manager.workflow import confirm
        with self.assertRaisesRegex(AssetError,'历史记录'):confirm(self.c,review['preview_id'],True)
        app=create_app(self.c.root,'x'*32);response=app.test_client().get('/file/preview-runtime/'+review['preview_id']+'/0/0',headers={'Authorization':'Bearer '+'x'*32});self.assertEqual(response.status_code,400);self.assertIn('历史记录',response.get_json()['error'])
        self.assertEqual(apply(self.c,p['confirmation_id'],True),r)

    def test_source_retirement_staged_file_failure_rolls_back(self):
        review=self.make_review_preview();self.do('purge_set_members',self.g['set_id'],'set',force=True,force_confirmed=True,confirmation_text='永久删除')
        p=self.preview('delete_source',self.s['source_id'],'source');original=os.replace;calls=[]
        def fail(src,dst):
            if '.deletion' in Path(dst).parts:
                calls.append(str(src))
                if len(calls)==2:raise OSError('disk failure')
            return original(src,dst)
        with patch('tools.asset_manager.lifecycle.os.replace',side_effect=fail):
            with self.assertRaises(OSError):apply(self.c,p['confirmation_id'],True)
        self.assertTrue(self.c.path(self.s['file']).exists());self.assertNotEqual(self.c.get('preview',review['preview_id']).get('lifecycle_status'),'retired');self.assertTrue(all(self.c.path(f['file']).exists() for f in p['affected_files']))

    def test_retired_preview_shared_file_owned_by_surviving_asset_preserved(self):
        review=self.make_review_preview();f=review['items'][0]['preview_files'][0]['runtime_preview'];other=self.c.create_named('resource_icon_v1','外部素材');other_source=self.c.upload('other.png',self.bytes,'resource_icon_v1')
        with self.c.transaction() as conn:
            a=self.c.get('asset',other['asset_id'],conn);v=copy.deepcopy(self.c.get('asset',self.aid,conn)['versions'][0]);v['source_id']=other_source['source_id'];v['files']=[dict(f,action='icon',frame=1,width=48,height=48)];v['runtime']=None;v['runtime_build_history']=[];a['versions']=[v];self.c.put('asset',a['asset_id'],a,conn)
        self.do('purge_set_members',self.g['set_id'],'set',force=True,force_confirmed=True,confirmation_text='永久删除')
        p=self.preview('delete_source',self.s['source_id'],'source');self.assertNotIn(f['file'],[x['file'] for x in p['affected_files']]);apply(self.c,p['confirmation_id'],True);self.assertTrue(self.c.path(f['file']).exists())

    def test_multiple_obsolete_previews_are_not_duplicate_source_blockers(self):
        reviews=[self.make_review_preview() for _ in range(2)]
        self.do('purge_set_members',self.g['set_id'],'set',force=True,force_confirmed=True,confirmation_text='永久删除')
        p=self.preview('delete_source',self.s['source_id'],'source')
        self.assertFalse(p['blockers']);self.assertEqual(set(p['retired_preview_ids']),{r['preview_id'] for r in reviews});self.assertTrue(all(self.c.path(f['file']).exists() for f in p['affected_files']))
        self.assertTrue(all(self.c.get('preview',r['preview_id']).get('lifecycle_status')!='retired' for r in reviews))

    def test_manifest_source_file_reference_blocks_physical_cleanup(self):
        s=self.c.upload('published-source.png',self.bytes,'resource_icon_v1')
        doc=self.manifest();doc['broken.external']={'files':[{'file':s['file']}]};self.c.atomic('manifest.json',json.dumps({'schema_version':1,'assets':doc}).encode())
        p=self.preview('delete_source',s['source_id'],'source');self.assertTrue(p['force_blockers'])
        with self.assertRaises(AssetError):apply(self.c,p['confirmation_id'],True)
        self.assertTrue(self.c.path(s['file']).exists())

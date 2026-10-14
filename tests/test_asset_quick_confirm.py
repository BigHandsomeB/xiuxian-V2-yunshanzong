"""One explicit review action; per-item safety and resumable publication, no live approvals."""
import copy,io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image,ImageDraw
from tools.asset_manager.catalog import Catalog,PROJECT
from tools.asset_manager.model import REVIEW,AssetError
from tools.asset_manager.workflow import prepare,confirm
from tools.asset_manager.specs import grid_regions
from tools.asset_manager.web import create_app

NAMES=['玄铁矿','赤铜矿','寒铁矿','灵晶矿','赤炎矿','星陨矿']
class QuickConfirmTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=PROJECT/'tests');self.addCleanup(self.temp.cleanup)
        self.c=Catalog(Path(self.temp.name)/'assets');self.g=self.c.create_named('resource_icon_v1','宗门矿石','set',NAMES,'sheet')
        self.p=self.c.prompt('resource_icon_v1',{},set_id=self.g['set_id']);self.spec=self.p['frozen_spec']
        im=Image.new('RGBA',(600,400));d=ImageDraw.Draw(im)
        for row in range(2):
            for col in range(3):d.rectangle((30+col*190,30+row*190,100+col*190,110+row*190),fill=(100+col*30,80,50,255))
        out=io.BytesIO();im.save(out,format='PNG');self.s=self.c.upload('sheet.png',out.getvalue(),'resource_icon_v1',self.g['set_id'],self.p['prompt_id'])
        self.r=self.c.auto_locate(self.s['source_id'])['regions']
    def preview(self,regions=None):return prepare(self.c,source_id=self.s['source_id'],regions=regions or self.r,mode='auto')
    def test_independent_icon_preview_and_build_keep_complete_image(self):
        a=self.c.create_named('resource_icon_v1','完整建筑',source_container='single_image')
        p=self.c.prompt('resource_icon_v1',{'source_container':'single_image'},asset_id=a['asset_id'])
        image=Image.new('RGBA',(288,288));draw=ImageDraw.Draw(image)
        draw.rectangle((100,100,187,187),fill=(100,100,100,255))
        colors=[(255,0,0,255),(0,255,0,255),(0,0,255,255),(255,255,0,255)]
        for box,color in zip([(12,12,71,71),(216,12,275,71),(12,216,71,275),(216,216,275,275)],colors):draw.rectangle(box,fill=color)
        data=io.BytesIO();image.save(data,format='PNG')
        source=self.c.upload('building.png',data.getvalue(),'resource_icon_v1',prompt_id=p['prompt_id'])
        regions=self.c.plan(source['source_id'],mode='independent')['regions']
        preview=prepare(self.c,source_id=source['source_id'],asset_id=a['asset_id'],regions=regions,mode='independent')
        item=preview['items'][0];self.assertTrue(item['valid'])
        f=item['preview_files'][0]['runtime_preview']
        with Image.open(self.c.path(f['file'])) as runtime:
            self.assertEqual(runtime.size,(48,48));self.assertTrue(set(colors)<=set(runtime.get_flattened_data()))
        confirm(self.c,preview['preview_id'],True)
        f=self.c.get('asset',a['asset_id'])['versions'][0]['runtime']['files'][0]
        with Image.open(self.c.path(f['file'])) as runtime:
            self.assertEqual(runtime.size,(48,48));self.assertTrue(set(colors)<=set(runtime.get_flattened_data()))
    def test_confirmation_requires_explicit_human_action(self):
        p=self.preview()
        for flag in (False,None,1):
            with self.assertRaises(AssetError):confirm(self.c,p['preview_id'],flag)
        self.assertTrue(all(not self.c.get('asset',aid)['versions'] for aid in self.g['asset_ids']))
    def test_no_approval_without_registered_preview(self):
        with self.assertRaises(AssetError):confirm(self.c,'missing',True)
    def test_preview_creates_no_versions_or_manifest(self):
        p=self.preview();self.assertEqual(len(p['items']),6);self.assertTrue(all(i['valid'] for i in p['items']));self.assertEqual(json.loads(self.c.path('manifest.json').read_text())['assets'],{})
        self.assertTrue(all(not self.c.get('asset',aid)['versions'] for aid in self.g['asset_ids']))
    def test_batch_approves_builds_and_publishes_six(self):
        p=self.preview();r=confirm(self.c,p['preview_id'],True)
        self.assertEqual(sum(a['status']=='approved' for a in r['assets']),6);self.assertTrue(r['manifest_updated'])
        self.assertEqual(set(json.loads(self.c.path('manifest.json').read_text())['assets']),set(self.g['asset_ids']))
        for aid in self.g['asset_ids']:
            a=self.c.get('asset',aid);self.assertEqual(a['current_approved_version'],1);self.assertEqual(a['versions'][0]['art_status'],'approved');self.assertEqual(len(a['versions'][0]['runtime']['files']),1)
    def test_approval_keeps_history_and_provenance(self):
        p=self.preview();confirm(self.c,p['preview_id'],True);v=self.c.get('asset',self.g['asset_ids'][0])['versions'][0]
        self.assertEqual([(x['from_status'],x['to_status']) for x in v['review_history']],[('draft','needs_review'),('needs_review','approved')]);self.assertEqual(v['review']['preview_id'],p['preview_id']);self.assertEqual(v['review']['approval_source'],'quick_confirm_preview');self.assertEqual(v['review']['prompt_id'],self.p['prompt_id']);self.assertEqual(v['review']['source_id'],self.s['source_id']);self.assertTrue(v['approved_at']);self.assertEqual(v['approved_by'],'authenticated_operator')
    def test_excluded_remains_reviewable_and_not_published(self):
        p=self.preview();excluded=self.g['asset_ids'][4];confirm(self.c,p['preview_id'],True,[excluded]);a=self.c.get('asset',excluded)
        self.assertEqual(a['versions'][0]['art_status'],'needs_review');self.assertIsNone(a['versions'][0]['runtime']);self.assertNotIn(excluded,json.loads(self.c.path('manifest.json').read_text())['assets'])
    def test_empty_crop_does_not_block_other_five(self):
        regions=copy.deepcopy(self.r);regions[0]['rect']=[0,0,15,15];p=self.preview(regions);self.assertFalse(p['items'][0]['valid']);r=confirm(self.c,p['preview_id'],True)
        self.assertEqual(sum(a['status']=='approved' for a in r['assets']),5);self.assertEqual(self.c.get('asset',self.g['asset_ids'][0])['versions'][0]['art_status'],'needs_review')
    def test_out_of_bounds_isolated_and_diagnostic_not_approved(self):
        regions=copy.deepcopy(self.r);regions[0]['rect']=[-1,0,50,50];p=self.preview(regions);r=confirm(self.c,p['preview_id'],True)
        self.assertEqual(sum(a['status']=='approved' for a in r['assets']),5);v=self.c.get('asset',self.g['asset_ids'][0])['versions'][0];self.assertEqual(v['files'],[])
        with self.assertRaises(AssetError):self.c.review(self.g['asset_ids'][0],1,'approved',dict.fromkeys(REVIEW,True))
    def test_runtime_failure_rolls_back_only_item_approval(self):
        p=self.preview();original=self.c._build
        def fail(aid,*args):
            if aid==self.g['asset_ids'][2]:raise OSError('disk failure')
            return original(aid,*args)
        with patch.object(self.c,'_build',side_effect=fail):r=confirm(self.c,p['preview_id'],True)
        self.assertEqual(sum(a['status']=='approved' for a in r['assets']),5);a=self.c.get('asset',self.g['asset_ids'][2]);self.assertEqual(a['versions'][0]['art_status'],'needs_review');self.assertIsNone(a['current_approved_version']);self.assertNotIn(a['asset_id'],json.loads(self.c.path('manifest.json').read_text())['assets'])
    def test_replay_does_not_import_twice(self):
        p=self.preview();first=confirm(self.c,p['preview_id'],True);self.assertEqual(confirm(self.c,p['preview_id'],True),first)
        self.assertTrue(all(len(self.c.get('asset',aid)['versions'])==1 for aid in self.g['asset_ids']))
    def test_changed_exclusions_after_confirmation_conflict(self):
        p=self.preview();confirm(self.c,p['preview_id'],True)
        with self.assertRaises(AssetError):confirm(self.c,p['preview_id'],True,[self.g['asset_ids'][0]])
    def test_publish_failure_retry_is_not_duplicate_approval(self):
        p=self.preview()
        with patch.object(self.c,'publish',side_effect=OSError('manifest disk failure')):r=confirm(self.c,p['preview_id'],True)
        self.assertFalse(r['manifest_updated']);self.assertEqual(json.loads(self.c.path('manifest.json').read_text())['assets'],{})
        r=confirm(self.c,p['preview_id'],True);self.assertTrue(r['manifest_updated']);self.assertTrue(all(len(self.c.get('asset',aid)['versions'])==1 for aid in self.g['asset_ids']))
    def test_stale_asset_state_rejected_before_any_approval(self):
        p=self.preview();self.c.rename(self.g['asset_ids'][0],'矿石改名')
        with self.assertRaises(AssetError):confirm(self.c,p['preview_id'],True)
        self.assertTrue(all(not self.c.get('asset',aid)['versions'] for aid in self.g['asset_ids']))
    def test_frozen_prompt_and_source_remain_unchanged(self):
        p=self.preview();confirm(self.c,p['preview_id'],True);self.assertEqual(self.c.get('prompt',self.p['prompt_id']),self.p);self.assertEqual(self.c.get('source',self.s['source_id'])['frozen_spec'],self.s['frozen_spec'])
    def test_source_and_preview_never_in_manifest(self):
        p=self.preview();confirm(self.c,p['preview_id'],True);m=json.loads(self.c.path('manifest.json').read_text())
        for a in m['assets'].values():
            for f in a['files']:self.assertTrue(f['file'].startswith('runtime/'));self.assertNotIn('source/',f['file']);self.assertNotIn('components/',f['file'])
    def test_single_static_confirmation(self):
        p=self.c.prompt('resource_icon_v1',{},asset_id=self.g['asset_ids'][0]);im=Image.new('RGBA',(80,60),'red');out=io.BytesIO();im.save(out,format='PNG');s=self.c.upload('one.png',out.getvalue(),'resource_icon_v1',self.g['set_id'],p['prompt_id']);regions=[dict(asset_id=self.g['asset_ids'][0],action='icon',frame=1,rect=[0,0,80,60])]
        preview=prepare(self.c,source_id=s['source_id'],regions=regions,mode='manual');self.assertEqual(confirm(self.c,preview['preview_id'],True)['assets'][0]['status'],'approved')
    def sprite(self):
        a=self.c.create_named('character_compact_v1','剑修');p=self.c.prompt('character_compact_v1',{'counts':dict(idle=2,walk=4,attack=4,cast=4,hit=2,death=4)},asset_id=a['asset_id']);s=p['frozen_spec'];g=s['grid_spec'];im=Image.new('RGBA',(g['columns']*g['frame_width']+(g['columns']-1)*g['horizontal_gap'],g['rows']*g['frame_height']+(g['rows']-1)*g['vertical_gap']));d=ImageDraw.Draw(im)
        for r in grid_regions(s):
            x,y,w,h=r['rect'];d.rectangle((x+40,y+40,x+70,y+90),fill='red')
        out=io.BytesIO();im.save(out,format='PNG');source=self.c.upload('sprite.png',out.getvalue(),'character_compact_v1',prompt_id=p['prompt_id']);plan=self.c.plan(source['source_id'])
        return a,source,plan
    def test_dynamic_sprite_all_twenty_frames_one_confirmation(self):
        a,s,plan=self.sprite();p=prepare(self.c,source_id=s['source_id'],asset_id=a['asset_id'],regions=plan['regions'],mode='grid',options=plan['grid_spec'],counts=plan['counts']);r=confirm(self.c,p['preview_id'],True)
        self.assertEqual(r['assets'][0]['status'],'approved');v=self.c.get('asset',a['asset_id'])['versions'][0];self.assertEqual(len(v['runtime']['files']),20)
    def test_dynamic_action_flag_keeps_whole_sprite_unpublished(self):
        a,s,plan=self.sprite();p=prepare(self.c,source_id=s['source_id'],asset_id=a['asset_id'],regions=plan['regions'],mode='grid',options=plan['grid_spec'],counts=plan['counts']);confirm(self.c,p['preview_id'],True,excluded_actions={a['asset_id']:['attack']})
        v=self.c.get('asset',a['asset_id'])['versions'][0];self.assertEqual(v['art_status'],'needs_review');self.assertIsNone(v['runtime']);self.assertNotIn(a['asset_id'],json.loads(self.c.path('manifest.json').read_text())['assets'])
    def test_existing_advanced_review_still_works(self):
        plan=self.c.plan(self.s['source_id'],mode='auto',regions=self.r);self.c.import_static_set(plan,True);aid=self.g['asset_ids'][0];self.c.review(aid,1,'needs_review');self.c.review(aid,1,'approved',dict.fromkeys(REVIEW,True));self.c.build(aid,1);self.c.select(aid,1);self.assertIn(aid,self.c.publish()['assets'])
    def test_existing_drafts_batch_confirmation_without_new_versions(self):
        self.c.import_static_set(self.c.plan(self.s['source_id'],mode='auto',regions=self.r),True);p=prepare(self.c,targets=[dict(asset_id=aid,version=1) for aid in self.g['asset_ids']]);confirm(self.c,p['preview_id'],True)
        self.assertTrue(all(len(self.c.get('asset',aid)['versions'])==1 for aid in self.g['asset_ids']))
    def test_snapshot_mapping_corruption_rejected(self):
        bad=copy.deepcopy(self.r);bad[0]['asset_id']='icon.unknown'
        with self.assertRaises(AssetError):self.preview(bad)
    def test_empty_exclusion_does_not_require_selecting_items(self):
        r=confirm(self.c,self.preview()['preview_id'],True);self.assertTrue(all(a['status']=='approved' for a in r['assets']))
    def test_preview_images_and_confirmation_are_authenticated(self):
        app=create_app(self.c.root,'x'*32);client=app.test_client();headers={'Authorization':'Bearer '+'x'*32}
        r=client.post('/api/quick-preview',json=dict(source_id=self.s['source_id'],regions=self.r,mode='auto'),headers=headers);self.assertEqual(r.status_code,200);key=r.json['preview_id']
        self.assertEqual(client.get('/file/preview/'+key+'/0/0').status_code,401);response=client.get('/file/preview/'+key+'/0/0',headers=headers);self.assertEqual(response.status_code,200);response.close()
        self.assertEqual(client.post('/api/quick-confirm',json=dict(preview_id=key,confirmed=True)).status_code,401)
        self.assertEqual(client.post('/api/quick-confirm',json=dict(preview_id=key,confirmed=True,actor='forged'),headers=headers).status_code,400)
        self.assertEqual(client.post('/api/quick-confirm',json=dict(preview_id=key,confirmed=True),headers=headers).status_code,200)
    def test_checkpoint_restart_preserves_confirmation_result(self):
        p=self.preview();r=confirm(self.c,p['preview_id'],True);self.assertEqual(confirm(Catalog(self.c.root),p['preview_id'],True),r)

    def scene_versions(self):
        group=self.c.get('set','scene_set.danding.interior.v1');targets=[]
        for state in ['master','prepare']:
            aid=group['asset_prefix']+'.'+state;im=Image.new('RGBA',(256,144),'red');out=io.BytesIO();im.save(out,format='PNG');source=self.c.upload(state+'.png',out.getvalue(),'building_interior_scene_v1',group['set_id'],spec_options={'state':state,**({'counts':{state:1}} if state!='master' else {})})
            plan=self.c.master_plan(source['source_id']) if state=='master' else self.c.plan(source['source_id'],mode='independent',counts={state:1})
            self.c.import_version(aid,plan,True,master=state=='master');targets.append(dict(asset_id=aid,version=1))
        return targets
    def test_scene_batch_selects_viewed_master_before_state(self):
        targets=self.scene_versions();p=prepare(self.c,targets=list(reversed(targets)));r=confirm(self.c,p['preview_id'],True)
        self.assertTrue(all(a['status']=='approved' for a in r['assets']));master=self.c.get('asset',targets[0]['asset_id']);self.assertIsNone(master['versions'][0]['runtime']);state=self.c.get('asset',targets[1]['asset_id']);self.assertEqual(state['versions'][0]['master_asset'],master['asset_id']);self.assertIn(state['asset_id'],json.loads(self.c.path('manifest.json').read_text())['assets']);self.assertNotIn(master['asset_id'],json.loads(self.c.path('manifest.json').read_text())['assets'])
    def test_unviewed_master_is_never_implicitly_approved(self):
        targets=self.scene_versions();p=prepare(self.c,targets=[targets[1]]);r=confirm(self.c,p['preview_id'],True)
        self.assertEqual(r['assets'][0]['status'],'needs_review');self.assertEqual(self.c.get('asset',targets[0]['asset_id'])['versions'][0]['art_status'],'draft');self.assertEqual(json.loads(self.c.path('manifest.json').read_text())['assets'],{})
    def test_excluded_master_leaves_state_needs_review(self):
        targets=self.scene_versions();p=prepare(self.c,targets=targets);r=confirm(self.c,p['preview_id'],True,[targets[0]['asset_id']]);self.assertTrue(all(a['status']!='approved' for a in r['assets']))
    def test_changed_preview_file_cannot_be_approved(self):
        p=self.preview();item=p['items'][0];self.c.path(item['preview_files'][0]['file']).write_bytes(b'corrupt test raster');r=confirm(self.c,p['preview_id'],True)
        self.assertEqual(sum(a['status']=='approved' for a in r['assets']),5);self.assertEqual(self.c.get('asset',item['asset_id'])['versions'][0]['art_status'],'needs_review')
    def test_failed_new_version_keeps_previous_published_version(self):
        p=self.preview();confirm(self.c,p['preview_id'],True);old=json.loads(self.c.path('manifest.json').read_text())['assets'][self.g['asset_ids'][0]]
        regions=copy.deepcopy(self.r);regions[0]['rect']=[0,0,15,15];p=self.preview(regions);confirm(self.c,p['preview_id'],True)
        self.assertEqual(json.loads(self.c.path('manifest.json').read_text())['assets'][self.g['asset_ids'][0]],old);self.assertEqual(len(self.c.get('asset',self.g['asset_ids'][0])['versions']),2)

    def test_incomplete_existing_sprite_is_not_quick_approved(self):
        a,s,plan=self.sprite();self.c.import_version(a['asset_id'],plan,True)
        with self.c.transaction() as conn:
            current=self.c.get('asset',a['asset_id'],conn);current['versions'][0]['files'].pop();self.c.put('asset',a['asset_id'],current,conn)
        p=prepare(self.c,targets=[dict(asset_id=a['asset_id'],version=1)]);self.assertFalse(p['items'][0]['valid']);r=confirm(self.c,p['preview_id'],True);self.assertEqual(r['assets'][0]['status'],'needs_review');self.assertNotIn(a['asset_id'],json.loads(self.c.path('manifest.json').read_text())['assets'])

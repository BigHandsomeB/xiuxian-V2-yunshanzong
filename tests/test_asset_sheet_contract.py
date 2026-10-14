"""Unified source containers: identities and cells never depend on static/dynamic."""
import copy, io, json, tempfile, unittest
from pathlib import Path
from PIL import Image, ImageDraw
from tools.asset_manager.catalog import Catalog, PROJECT
from tools.asset_manager.model import AssetError

class UnifiedSheetTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=PROJECT/'tests');self.addCleanup(self.tmp.cleanup)
        self.c=Catalog(Path(self.tmp.name)/'assets')

    def test_character_creation_accepts_sheet(self):
        a=self.c.create_named('character_compact_v1','剑修',generation_scope='single_asset',source_container='sheet')
        p=self.c.prompt(a['template_id'],{},asset_id=a['asset_id']);s=p['frozen_spec']
        self.assertEqual(s['generation_scope'],'single_asset')
        self.assertEqual(s['source_container'],'sheet');self.assertEqual(s['sheet_semantics'],'action_frames')
        self.assertEqual(s['asset_count'],1)
        self.assertEqual((s['layout_spec']['rows'],s['layout_spec']['columns']),(6,4))
        self.assertEqual(len(s['cell_mapping']),20)

    def png(self,image):
        out=io.BytesIO();image.save(out,format='PNG');return out.getvalue()

    def source(self,p,paint=True):
        spec=p['frozen_spec'];g=spec['grid_spec']
        im=Image.new('RGBA',(g['columns']*g['frame_width']+(g['columns']-1)*g['horizontal_gap'],g['rows']*g['frame_height']+(g['rows']-1)*g['vertical_gap']))
        if paint:
            d=ImageDraw.Draw(im)
            for c in spec['cell_mapping']:
                x=c['column']*(g['frame_width']+g['horizontal_gap']);y=c['row']*(g['frame_height']+g['vertical_gap'])
                # Complete scene panels preserve framing; sprites have isolated small bodies.
                if spec['runtime_profile']['policy']=='scene_resize':d.rectangle((x,y,x+g['frame_width']-1,y+g['frame_height']-1),fill=(90,80,60,255))
                else:d.rectangle((x+40,y+40,x+65,y+65),fill=(90,80,60,255))
        return self.c.upload('sheet.png',self.png(im),p['template_id'],p['set_id'],p['prompt_id'])

    def test_monster_boss_beast_and_effect_sheet_defaults(self):
        from tools.asset_manager.specs import freeze_spec
        for t,sem in [('monster_compact_v1','action_frames'),('boss_v1','action_frames'),('spirit_beast_v1','action_frames'),('effect_compact_v1','effect_frames')]:
            with self.subTest(t=t):
                a=self.c.create_named(t,'对象',source_container='sheet');s=self.c.specification(t,{},asset_id=a['asset_id'])
                self.assertEqual(s['sheet_semantics'],sem);self.assertEqual(s['source_container'],'sheet');self.assertEqual(s['asset_count'],1)

    def test_icon_single_scope_can_use_sheet(self):
        a=self.c.create_named('resource_icon_v1','玄铁矿',source_container='sheet');p=self.c.prompt(a['template_id'],{},asset_id=a['asset_id'])
        s=p['frozen_spec'];self.assertEqual(s['generation_scope'],'single_asset');self.assertEqual(s['source_container'],'sheet');self.assertEqual(len(s['cell_mapping']),1)

    def test_scope_and_container_independent_validation(self):
        for container in ('single_image','sheet','image_set'):
            g=self.c.create_named('resource_icon_v1','矿石',generation_scope='asset_set',asset_names=['甲'],source_container=container)
            self.assertEqual(g['source_container'],container);self.assertEqual(len(g['asset_ids']),1)
        with self.assertRaises(AssetError):self.c.create_named('resource_icon_v1','多个',generation_scope='asset_set',asset_names=['甲','乙'],source_container='single_image')

    def test_six_ores_remain_independent_48px_runtime(self):
        from tools.asset_manager.workflow import prepare,confirm
        g=self.c.create_named('resource_icon_v1','宗门矿石','asset_set',['玄铁矿','赤铜矿','寒铁矿','灵晶矿','赤炎矿','星陨矿'],source_container='sheet')
        p=self.c.prompt(g['template_id'],{},set_id=g['set_id']);s=p['frozen_spec'];source=self.source(p)
        self.assertEqual((s['layout_spec']['rows'],s['layout_spec']['columns']),(2,3));self.assertEqual(s['sheet_semantics'],'independent_assets')
        plan=self.c.plan(source['source_id']);preview=prepare(self.c,source['source_id'],regions=plan['regions'],mode='grid');result=confirm(self.c,preview['preview_id'],True)
        self.assertEqual(len(result['assets']),6);manifest=self.c.publish()['assets'];self.assertEqual(set(manifest),set(g['asset_ids']))
        for m in manifest.values():self.assertEqual([(f['width'],f['height']) for f in m['files']],[(48,48)])

    def test_character_grid_is_one_asset_twenty_frames(self):
        from tools.asset_manager.workflow import prepare,confirm
        a=self.c.create_named('character_compact_v1','剑修',source_container='sheet');p=self.c.prompt(a['template_id'],{},asset_id=a['asset_id']);source=self.source(p)
        plan=self.c.plan(source['source_id']);self.assertEqual(len(plan['regions']),20)
        self.assertEqual({r['asset_id'] for r in plan['regions']},{a['asset_id']})
        imported=self.c.import_sheet(plan,True);self.assertEqual(len(imported),1);self.assertEqual(len(imported[0]['version']['files']),20)
        preview=prepare(self.c,targets=[dict(asset_id=a['asset_id'],version=1)]);result=confirm(self.c,preview['preview_id'],True)
        self.assertEqual(result['assets'][0]['status'],'approved');manifest=self.c.publish()['assets']
        self.assertEqual(list(manifest),[a['asset_id']]);self.assertEqual(len(manifest[a['asset_id']]['files']),20)
        self.assertEqual({(f['width'],f['height']) for f in manifest[a['asset_id']]['files']},{(128,128)})

    def test_unused_character_cells_are_not_imported(self):
        a=self.c.create_named('character_compact_v1','剑修',source_container='sheet');p=self.c.prompt(a['template_id'],{},asset_id=a['asset_id']);s=p['frozen_spec']
        self.assertEqual(s['row_count']*s['column_count'],24);self.assertEqual(len(s['cell_mapping']),20)
        self.assertNotIn((0,2),[(c['row'],c['column']) for c in s['cell_mapping']])

    def test_invalid_container_and_semantics_rejected(self):
        from tools.asset_manager.specs import freeze_spec
        for o in ({'source_container':'sprite_sheet'},{'source_container':'single_image'},{'source_container':'sheet','sheet_semantics':'independent_assets'}):
            with self.assertRaises(AssetError):freeze_spec(self.c.templates['character_compact_v1'],o)

    def test_master_prompt_uses_authoritative_asset_state(self):
        g=self.c.create_named('building_interior_scene_v1','新丹鼎阁',generation_scope='asset_set',source_container='image_set')
        mid=g['asset_prefix']+'.master'
        p=self.c.prompt(g['template_id'],{},asset_id=mid,set_id=g['set_id'])
        self.assertEqual(p['frozen_spec']['output_mode'],'master')
        self.assertEqual(p['frozen_spec']['frame_counts'],{'master':1})
        self.assertEqual(p['frozen_spec']['source_container'],'single_image')
        self.assertIn('one complete image',p['text'])

    def test_scene_asset_cannot_bypass_master_guard_with_user_state(self):
        g=self.c.create_named('building_interior_scene_v1','新丹鼎阁',generation_scope='asset_set',source_container='image_set')
        with self.assertRaisesRegex(AssetError,'Master reference'):
            self.c.prompt(g['template_id'],{'state':'master'},asset_id=g['asset_prefix']+'.prepare',set_id=g['set_id'])

    def test_scene_sheet_six_complete_states_and_master_guard(self):
        from tools.asset_manager.workflow import prepare,confirm
        g=self.c.get('set','scene_set.danding.interior.v1');mid=g['asset_prefix']+'.master'
        pm=self.c.prompt(g['template_id'],{'state':'master'},asset_id=mid,set_id=g['set_id'])
        master=self.c.upload('master.png',self.png(Image.new('RGBA',(256,144),'brown')),g['template_id'],g['set_id'],pm['prompt_id'])
        self.c.import_version(mid,self.c.master_plan(master['source_id']),True,True)
        approved=confirm(self.c,prepare(self.c,targets=[dict(asset_id=mid,version=1)])['preview_id'],True)
        self.assertEqual(approved['assets'][0]['status'],'approved')
        p=self.c.prompt(g['template_id'],{'master_reference':mid,'source_container':'sheet'},set_id=g['set_id']);s=p['frozen_spec'];source=self.source(p)
        self.assertEqual(s['sheet_semantics'],'scene_states');self.assertEqual((s['row_count'],s['column_count']),(2,3));self.assertEqual(s['asset_count'],6)
        self.assertEqual([c['action'] for c in s['cell_mapping']],g['states']);self.assertNotIn('master',[c['action'] for c in s['cell_mapping']])
        self.assertIn('COMPLETE independent Scene State',p['text']);self.assertIn('NOT animation frames',p['text'])
        plan=self.c.plan(source['source_id']);preview=prepare(self.c,source['source_id'],regions=plan['regions'],mode='grid');r=confirm(self.c,preview['preview_id'],True)
        self.assertTrue(all(a['status']=='approved' for a in r['assets']),r)
        self.assertEqual(len(self.c.publish()['assets']),6)
        for m in self.c.publish()['assets'].values():self.assertEqual([(f['width'],f['height']) for f in m['files']],[(256,144)])
        self.assertEqual(self.c.get('prompt',p['prompt_id']),p)

    def test_independent_scene_and_sheet_have_same_state_ids(self):
        g=self.c.create_named('building_overview_scene_v1','灵田','asset_set',source_container='sheet')
        sheet=self.c.specification(g['template_id'],{'source_container':'sheet'},set_id=g['set_id'])
        independent=self.c.specification(g['template_id'],{'source_container':'image_set'},set_id=g['set_id'])
        self.assertEqual(sheet['asset_ids'],independent['asset_ids']);self.assertEqual(sheet['asset_order'],independent['asset_order'])
        self.assertEqual(independent['source_container'],'image_set')
        p=self.c.prompt(g['template_id'],{'source_container':'single_image'},asset_id=sheet['asset_ids'][0],set_id=g['set_id'])
        self.assertEqual(len(p['frozen_spec']['cell_mapping']),1)
        src=self.c.upload('single.png',self.png(Image.new('RGBA',(160,160),'brown')),g['template_id'],g['set_id'],p['prompt_id'])
        self.assertEqual(len(self.c.import_sheet(self.c.plan(src['source_id'],mode='independent'),True)),1)

    def test_twelve_environment_variants_are_not_animation(self):
        g=self.c.create_named('environment_scene_v1','十二时辰','asset_set',family='time_of_day',source_container='sheet')
        p=self.c.prompt(g['template_id'],{'family':'time_of_day'},set_id=g['set_id']);s=p['frozen_spec'];source=self.source(p)
        self.assertEqual(s['sheet_semantics'],'environment_variants');self.assertEqual(len(s['asset_ids']),12)
        self.assertEqual([c['action'] for c in s['cell_mapping']],['zi','chou','yin','mao','chen','si','wu','wei','shen','you','xu','hai'])
        versions=self.c.import_sheet(self.c.plan(source['source_id']),True);self.assertEqual(len(versions),12);self.assertTrue(all(len(v['version']['files'])==1 for v in versions))

    def test_ui_states_share_layout_and_independent_records(self):
        g=self.c.create_named('ui_state_v1','按钮','asset_set',source_container='sheet');p=self.c.prompt(g['template_id'],{},set_id=g['set_id']);src=self.source(p)
        self.assertEqual(p['frozen_spec']['sheet_semantics'],'ui_states');self.assertEqual((p['frozen_spec']['row_count'],p['frozen_spec']['column_count']),(2,2))
        self.assertEqual(len(self.c.import_sheet(self.c.plan(src['source_id']),True)),4)

    def test_nine_slice_fixed_order(self):
        from tools.asset_manager.sheets import NINE
        g=self.c.create_named('ui_state_v1','边框','asset_set',family='nine_slice',source_container='sheet');p=self.c.prompt(g['template_id'],{'family':'nine_slice'},set_id=g['set_id']);src=self.source(p)
        s=p['frozen_spec'];self.assertEqual(s['sheet_semantics'],'nine_slice');self.assertEqual((s['row_count'],s['column_count']),(3,3));self.assertEqual(s['state_order'],list(NINE))
        self.assertEqual(len(self.c.import_sheet(self.c.plan(src['source_id']),True)),9)

    def test_tiles_use_same_layout(self):
        g=self.c.create_named('environment_scene_v1','地形','asset_set',['草地','泥土','岩石'],family='terrain',source_container='sheet')
        p=self.c.prompt(g['template_id'],{'family':'terrain'},set_id=g['set_id']);src=self.source(p)
        self.assertEqual(p['frozen_spec']['sheet_semantics'],'tiles');self.assertEqual(len(self.c.import_sheet(self.c.plan(src['source_id']),True)),3)

    def test_herb_growth_is_states_not_resources_or_frames(self):
        g=self.c.create_named('herb_icon_v1','青灵草成长','asset_set',family='growth',source_container='sheet')
        p=self.c.prompt(g['template_id'],{'family':'growth'},set_id=g['set_id'])
        self.assertEqual(p['frozen_spec']['sheet_semantics'],'state_sequence');self.assertEqual(p['frozen_spec']['frame_count'],1)
        self.assertEqual([c['action'] for c in p['frozen_spec']['cell_mapping']],['seedling','growing','flowering','mature','spiritual'])

    def test_legacy_compatibility_projection_never_writes(self):
        from tools.asset_manager.sheets import canonical_spec
        a=self.c.create_named('character_compact_v1','剑修');new=self.c.specification(a['template_id'],{},asset_id=a['asset_id'])
        for oldmode,semantic in [('static_asset_sheet','independent_assets'),('sprite_sheet','action_frames'),('scene_state_sheet','scene_states')]:
            old=copy.deepcopy(new)
            for k in ('source_container','sheet_semantics','layout_spec'):old.pop(k,None)
            old['output_mode']=oldmode;old['generation_scope']='single';old['template_snapshot'].pop('default_sheet_semantics',None)
            before=copy.deepcopy(old);view=canonical_spec(old)
            self.assertEqual(view['source_container'],'sheet');self.assertEqual(view['sheet_semantics'],semantic);self.assertEqual(old,before)
            self.assertEqual(view['grid_spec'],old['grid_spec'])

    def test_legacy_prompt_and_source_remain_identical_on_read(self):
        from tools.asset_manager.sheets import canonical_spec
        g=self.c.create_named('resource_icon_v1','矿石','set',['甲','乙'],'sheet');p=self.c.prompt(g['template_id'],{},set_id=g['set_id']);src=self.source(p)
        for obj in (p,src):
            for k in ('source_container','sheet_semantics','layout_spec'):obj['frozen_spec'].pop(k,None)
            obj['frozen_spec']['generation_scope']='set'
        with self.c.transaction() as conn:self.c.put('prompt',p['prompt_id'],p,conn);self.c.put('source',src['source_id'],src,conn)
        plan=self.c.plan(src['source_id']);self.c.import_static_set(plan,True)
        self.assertEqual(self.c.get('prompt',p['prompt_id']),p);self.assertEqual(self.c.get('source',src['source_id'])['frozen_spec'],src['frozen_spec'])

    def test_auto_locate_action_frames_uses_cell_count_not_asset_count(self):
        from tools.asset_manager.workflow import prepare,confirm
        a=self.c.create_named('character_compact_v1','剑修',source_container='sheet');p=self.c.prompt(a['template_id'],{},asset_id=a['asset_id']);src=self.source(p)
        detected=self.c.auto_locate(src['source_id']);self.assertEqual(detected['status'],'PASS');self.assertEqual(detected['expected_count'],20);self.assertEqual(detected['detected_count'],20)
        self.assertEqual({r['asset_id'] for r in detected['regions']},{a['asset_id']});self.assertEqual([(r['action'],r['frame']) for r in detected['regions']],[(c['action'],c['frame']) for c in p['frozen_spec']['cell_mapping']])
        plan=self.c.plan(src['source_id'],mode='auto',regions=detected['regions']);preview=prepare(self.c,src['source_id'],regions=plan['regions'],mode='auto');r=confirm(self.c,preview['preview_id'],True)
        self.assertEqual(r['assets'][0]['status'],'approved',r);self.assertEqual(len(self.c.publish()['assets'][a['asset_id']]['files']),20)

    def test_auto_locate_complete_scene_panels(self):
        g=self.c.create_named('building_overview_scene_v1','灵田','asset_set',states=['idle','working','busy','blocked'],source_container='sheet')
        p=self.c.prompt(g['template_id'],{},set_id=g['set_id']);src=self.source(p);r=self.c.auto_locate(src['source_id'])
        self.assertEqual(r['detected_count'],4);self.assertEqual(r['status'],'PASS');self.assertEqual([v['asset_id'] for v in r['regions']],p['frozen_spec']['asset_order'])

    def test_layout_overrides_and_mapping_cannot_duplicate_frames(self):
        a=self.c.create_named('monster_compact_v1','妖兽',source_container='sheet');p=self.c.prompt(a['template_id'],{},asset_id=a['asset_id']);src=self.source(p)
        plan=self.c.plan(src['source_id']);bad=copy.deepcopy(plan['regions']);bad[0]=copy.deepcopy(bad[1])
        with self.assertRaises(AssetError):self.c.plan(src['source_id'],mode='manual',regions=bad)

    def test_prompt_contains_semantic_meaning_for_all_modes(self):
        from tools.asset_manager.specs import freeze_spec
        from tools.asset_manager.prompts import compile_prompt
        cases=[('character_compact_v1',None,'SAME character'),('effect_compact_v1',None,'effect keyframes'),('environment_scene_v1','time_of_day','SAME location'),('ui_state_v1',None,'interaction states'),('ui_state_v1','nine_slice','Nine ordered'),('herb_icon_v1','growth','Non-animation states')]
        for t,f,phrase in cases:
            with self.subTest(t=t,f=f):
                o={'family':f} if f else {};s=freeze_spec(self.c.templates[t],o);text=compile_prompt(self.c.templates[t],o,spec=s);self.assertIn(phrase,text);self.assertIn('[Layout]',text)

    def test_template_policy_validation(self):
        from tools.asset_manager.model import templates
        d=json.loads((PROJECT/'assets/templates/templates.json').read_text());d['templates'][0]['allowed_source_containers']=['static_asset_sheet']
        with self.assertRaises(AssetError):templates(d)
        d=json.loads((PROJECT/'assets/templates/templates.json').read_text());d['templates'][0]['allowed_sheet_semantics']=['unknown']
        with self.assertRaises(AssetError):templates(d)

    def test_image_set_character_explicit_action_fallback(self):
        a=self.c.create_named('character_compact_v1','剑修',source_container='image_set')
        all_actions=self.c.prompt(a['template_id'],{'source_container':'image_set'},asset_id=a['asset_id'])
        with self.assertRaises(AssetError):self.source(all_actions)
        p=self.c.prompt(a['template_id'],{'source_container':'image_set','counts':{'walk':4}},asset_id=a['asset_id'])
        src=self.source(p);plan=self.c.plan(src['source_id']);result=self.c.import_sheet(plan,True)
        self.assertEqual(result[0]['asset_id'],a['asset_id']);self.assertEqual(len(result[0]['version']['files']),4)
        self.assertEqual(self.c.get('asset',a['asset_id'])['asset_id'],a['asset_id'])

    def test_template_upgrade_preserves_snapshot_and_source_geometry(self):
        a=self.c.create_named('character_compact_v1','剑修',source_container='sheet');p=self.c.prompt(a['template_id'],{},asset_id=a['asset_id']);src=self.source(p)
        old_plan=self.c.plan(src['source_id']);before=copy.deepcopy(src['frozen_spec'])
        self.c.templates[a['template_id']]['template_version']+=1
        self.c.templates[a['template_id']]['default_source_container']='image_set'
        self.assertEqual(self.c.plan(src['source_id']),old_plan);self.assertEqual(self.c.get('source',src['source_id'])['frozen_spec'],before);self.assertEqual(self.c.get('prompt',p['prompt_id']),p)

    def test_state_semantics_cannot_be_used_as_animation_counts(self):
        from tools.asset_manager.specs import freeze_spec
        t=copy.deepcopy(self.c.templates['monster_compact_v1']);t['default_sheet_semantics']='ui_states';t['allowed_sheet_semantics']=['ui_states']
        with self.assertRaises(AssetError):freeze_spec(t)

    def test_legacy_mode_aliases_resolve_from_frozen_data(self):
        from tools.asset_manager.sheets import canonical_spec
        a=self.c.create_named('monster_compact_v1','妖兽');s=self.c.specification(a['template_id'],{},asset_id=a['asset_id'])
        for alias,sem in [('sprite_sheet','action_frames'),('scene_state_sheet','scene_states'),('static_asset_sheet','independent_assets')]:
            old=copy.deepcopy(s)
            for k in ('source_container','sheet_semantics','layout_spec'):old.pop(k,None)
            old['generation_mode']=alias
            before=copy.deepcopy(old);adapted=canonical_spec(old)
            self.assertEqual(adapted['source_container'],'sheet');self.assertEqual(adapted['sheet_semantics'],sem);self.assertEqual(old,before)

    def test_runtime_scene_region_size_does_not_change_profile(self):
        from tools.asset_manager.images import profiled_runtime
        from tools.asset_manager.specs import freeze_spec
        spec=freeze_spec(self.c.templates['building_interior_scene_v1']);before=copy.deepcopy(spec)
        output=profiled_runtime(Image.new('RGBA',(303,171),'brown'),spec,subject_region=True)
        with Image.open(io.BytesIO(output)) as runtime:self.assertEqual(runtime.size,(256,144))
        self.assertEqual(spec,before)

    def test_http_container_creation_and_sheet_import_auth(self):
        from tools.asset_manager.web import create_app
        app=create_app(self.c.root,'x'*32);client=app.test_client();headers={'Authorization':'Bearer '+'x'*32}
        d=dict(template_id='character_compact_v1',name_zh='剑修',generation_scope='single_asset',source_container='sheet')
        a=client.post('/api/create-named',json=d,headers=headers)
        self.assertEqual(a.status_code,200)
        p=client.post('/api/prompts',json=dict(template_id=d['template_id'],options={},asset_id=a.json['asset_id']),headers=headers)
        self.assertEqual(p.status_code,200);self.assertEqual(p.json['frozen_spec']['sheet_semantics'],'action_frames')
        source=self.source(p.json);plan=self.c.plan(source['source_id'])
        self.assertEqual(client.post('/api/import-sheet',json=dict(plan=plan,confirmed=True)).status_code,401)
        response=client.post('/api/import-sheet',json=dict(plan=plan,confirmed=True),headers=headers)
        self.assertEqual(response.status_code,200);self.assertEqual(len(response.json['assets']),1)

    def test_sprite_exclusion_preserves_single_asset_and_no_manifest_entry(self):
        from tools.asset_manager.workflow import prepare,confirm
        a=self.c.create_named('character_compact_v1','剑修',source_container='sheet');p=self.c.prompt(a['template_id'],{},asset_id=a['asset_id']);source=self.source(p);plan=self.c.plan(source['source_id'])
        preview=prepare(self.c,source['source_id'],regions=plan['regions'],mode='grid');r=confirm(self.c,preview['preview_id'],True,excluded_actions={a['asset_id']:['walk']})
        self.assertEqual(r['assets'][0]['status'],'needs_review');self.assertNotIn(a['asset_id'],self.c.publish()['assets'])
        self.assertEqual(len(self.c.get('asset',a['asset_id'])['versions'][0]['files']),20)

    def test_pending_grid_restores_shared_semantic_mapping(self):
        a=self.c.create_named('effect_compact_v1','剑气',source_container='sheet');p=self.c.prompt(a['template_id'],{},asset_id=a['asset_id']);src=self.source(p)
        plan=self.c.plan(src['source_id']);self.assertEqual(plan['sheet_semantics'],'effect_frames');self.assertEqual(len(plan['regions']),2)
        versions=self.c.import_sheet(plan,True);self.assertEqual(len(versions),1);self.assertEqual(len(versions[0]['version']['files']),2)

    def test_preview_contains_scene_ids_and_confirms_once(self):
        from tools.asset_manager.workflow import prepare,confirm
        g=self.c.create_named('building_overview_scene_v1','灵田','asset_set',states=['idle','working'],source_container='sheet');p=self.c.prompt(g['template_id'],{},set_id=g['set_id']);src=self.source(p)
        plan=self.c.plan(src['source_id']);preview=prepare(self.c,src['source_id'],regions=plan['regions'],mode='grid');r=confirm(self.c,preview['preview_id'],True)
        self.assertEqual(confirm(self.c,preview['preview_id'],True),r)
        self.assertEqual(set(self.c.publish()['assets']),set(p['frozen_spec']['asset_ids']))
        self.assertTrue(all(len(self.c.get('asset',aid)['versions'])==1 for aid in p['frozen_spec']['asset_ids']))

    def test_character_master_remains_single_reference_image(self):
        g=self.c.create_set('asset_set.hero','人物基准','character_compact_v1',['idle'],'character.hero')
        p=self.c.prompt(g['template_id'],{'state':'master','source_container':'single_image'},asset_id='character.hero.master',set_id=g['set_id'])
        self.assertEqual(p['frozen_spec']['source_container'],'single_image');self.assertIsNone(p['frozen_spec']['sheet_semantics'])
        self.assertEqual(len(p['frozen_spec']['cell_mapping']),1)

    def test_sheet_import_reads_layout_spec_through_compatibility_grid_adapter(self):
        from tools.asset_manager.sheets import grid_options
        a=self.c.create_named('monster_compact_v1','妖兽',source_container='sheet');p=self.c.prompt(a['template_id'],{},asset_id=a['asset_id']);src=self.source(p)
        frozen=p['frozen_spec'];self.assertEqual(grid_options(frozen),frozen['grid_spec'])
        by_layout=self.c.plan(src['source_id'],options=frozen['layout_spec']);normal=self.c.plan(src['source_id'])
        self.assertEqual(by_layout,normal)

    def test_independent_buildings_use_shared_icon_collection_not_scene_animation(self):
        g=self.c.create_named('building_overview_scene_v1','宗门建筑','asset_set',['山门','丹鼎阁'],family='independent_buildings',source_container='sheet')
        p=self.c.prompt(g['template_id'],{'family':'independent_buildings'},set_id=g['set_id']);src=self.source(p)
        self.assertEqual(p['frozen_spec']['sheet_semantics'],'independent_assets');self.assertEqual(len(self.c.import_sheet(self.c.plan(src['source_id']),True)),2)
        self.assertEqual(len(g['asset_ids']),2)

    def test_no_prompt_image_set_upload_requires_explicit_member(self):
        g=self.c.create_named('resource_icon_v1','矿石','asset_set',['甲','乙'],source_container='image_set')
        with self.assertRaises(AssetError):self.c.upload('unbound.png',self.png(Image.new('RGBA',(96,96),'red')),g['template_id'],g['set_id'])

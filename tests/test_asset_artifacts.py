"""Artifact-specific metadata on the existing asset catalog and immutable prompt pipeline."""
import copy,io,json,tempfile,unittest
from pathlib import Path
from PIL import Image
from tools.asset_manager.catalog import Catalog,PROJECT
from tools.asset_manager.model import AssetError,REVIEW
from tools.asset_manager.web import create_app

NAMES=['斩妖飞剑','镇岳鼎','噬魂幡','寒魄印','赤焰葫']
LOOKS=['青白剑刃、獠牙护手','赤铜三足鼎，双耳；厚重','墨青幡面与幽青魂纹','寒玉方印与螭龙钮','赤红葫芦、铜箍与系绳']

class ArtifactAssetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=PROJECT/'tests');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'assets';self.c=Catalog(self.root)
    def group(self,filled=True):
        return self.c.create_named('artifact_static_v1','法宝','set',NAMES,'sheet',appearance_directions=dict(zip(NAMES,LOOKS)) if filled else None)
    def entries(self,g):
        return [{'asset_id':aid,'name_zh':self.c.get('asset',aid)['name_zh'],'appearance_direction':self.c.get('asset',aid).get('appearance_direction','')} for aid in g['asset_ids']]
    def prompt(self,g):return self.c.prompt('artifact_static_v1',{},set_id=g['set_id'])

    def test_template_single_frame_and_exact_128_export(self):
        g=self.group();p=self.prompt(g);spec=p['frozen_spec']
        self.assertEqual(spec['runtime_profile']['frame_size'],[128,128]);self.assertEqual(spec['subject_logic_size'],[128,128]);self.assertEqual(spec['frame_counts'],{'icon':1})
        self.assertEqual(len(spec['cell_mapping']),5)
        self.assertIn('program-driven',p['text']);self.assertIn('Alpha',p['text'])
        for name,look in zip(NAMES,LOOKS):self.assertIn(name,p['text']);self.assertIn(look,p['text'])

    def test_names_first_then_bulk_directions_after_reopen(self):
        g=self.group(False);self.assertEqual(len(g['asset_ids']),5)
        with self.assertRaisesRegex(AssetError,'补齐'):self.prompt(g)
        entries=self.entries(g)
        for row,look in zip(entries,LOOKS):row['appearance_direction']=look
        self.c.edit_static_set(g['set_id'],entries)
        reopened=Catalog(self.root);self.assertEqual([reopened.get('asset',aid)['appearance_direction'] for aid in g['asset_ids']],LOOKS)
        self.assertIn(LOOKS[-1],reopened.prompt('artifact_static_v1',{},set_id=g['set_id'])['text'])

    def test_preview_directions_are_read_only(self):
        before=self.c.list('asset')
        p=self.c.creation_preview('artifact_static_v1','法宝','set',NAMES,'sheet',appearance_directions=dict(zip(NAMES,LOOKS)))
        self.assertEqual([a['appearance_direction'] for a in p['asset_list']],LOOKS);self.assertEqual(self.c.list('asset'),before)

    def test_mapping_unknown_name_and_invalid_values_rejected_before_creation(self):
        for directions in ({'不存在':'说明'},{NAMES[0]:None},{NAMES[0]:'字'*1001},['方向']):
            with self.subTest(directions=str(directions)[:20]):
                before=self.c.list('asset')
                with self.assertRaises(AssetError):self.c.create_named('artifact_static_v1','法宝','set',NAMES,'sheet',appearance_directions=directions)
                self.assertEqual(self.c.list('asset'),before)

    def test_edit_reorder_rename_preserves_direction_identity(self):
        g=self.group();entries=list(reversed(self.entries(g)));entries[0]['name_zh']='赤焰葫·改名'
        self.c.edit_static_set(g['set_id'],entries)
        after=self.c.get('set',g['set_id']);self.assertEqual(after['asset_ids'],list(reversed(g['asset_ids'])))
        self.assertEqual(self.c.get('asset',g['asset_ids'][-1])['appearance_direction'],LOOKS[-1])
        text=self.prompt(g)['text'];self.assertIn('赤焰葫·改名',text);self.assertIn(LOOKS[-1],text)

    def test_invalid_bulk_edit_rolls_back_every_member(self):
        g=self.group();before=copy.deepcopy(self.c.list('asset'));entries=self.entries(g)
        entries[0]['appearance_direction']='先改第一件';entries[1]['appearance_direction']=123
        with self.assertRaises(AssetError):self.c.edit_static_set(g['set_id'],entries)
        self.assertEqual(self.c.list('asset'),before)

    def test_single_asset_can_save_direction_later_and_override_only_one_prompt(self):
        a=self.c.create_named('artifact_static_v1','斩妖飞剑',generation_scope='single_asset');aid=a['asset_id']
        self.c.rename(aid,'斩妖飞剑',appearance_direction=LOOKS[0])
        p=self.c.prompt('artifact_static_v1',{'appearance_direction':'本次改为玉剑'},asset_id=aid)
        self.assertIn('本次改为玉剑',p['text']);self.assertEqual(p['frozen_spec']['asset_list'][0]['appearance_direction'],'本次改为玉剑')
        self.assertEqual(self.c.get('asset',aid)['appearance_direction'],LOOKS[0])
        self.c.rename(aid,'斩妖飞剑·改名');self.assertEqual(self.c.get('asset',aid)['appearance_direction'],LOOKS[0])

    def test_prompt_history_is_immutable_after_metadata_change(self):
        g=self.group();old=self.prompt(g);manifest=self.c.path('manifest.json').read_bytes();entries=self.entries(g)
        entries[0]['appearance_direction']='新方向：青玉剑身';self.c.edit_static_set(g['set_id'],entries);new=self.prompt(g)
        self.assertIn('新方向：青玉剑身',new['text']);self.assertEqual(self.c.get('prompt',old['prompt_id']),old)
        self.assertEqual(old['frozen_spec']['asset_list'][0]['appearance_direction'],LOOKS[0]);self.assertEqual(self.c.path('manifest.json').read_bytes(),manifest)

    def test_old_templates_unchanged_and_reject_artifact_direction_fields(self):
        old=self.c.create_named('equipment_icon_v1','普通长剑')
        self.assertNotIn('appearance_direction',old)
        with self.assertRaises(AssetError):self.c.rename(old['asset_id'],'普通长剑',appearance_direction='不应接受')
        with self.assertRaises(AssetError):self.c.create_named('equipment_icon_v1','普通剑',appearance_directions={'普通剑':'说明'})
        g=self.c.create_named('resource_icon_v1','矿石','set',['甲','乙'])
        self.assertNotIn('法宝外观方向',self.c.prompt('resource_icon_v1',{},set_id=g['set_id'])['text'])

    def test_dynamic_and_group_wide_override_rejected(self):
        g=self.group()
        with self.assertRaises(AssetError):self.c.prompt('artifact_static_v1',{'mode':'dynamic'},set_id=g['set_id'])
        with self.assertRaises(AssetError):self.c.prompt('artifact_static_v1',{'appearance_direction':'整组覆盖'},set_id=g['set_id'])

    def test_unbound_prompt_requires_direction(self):
        with self.assertRaises(AssetError):self.c.prompt('artifact_static_v1',{'object':'剑'})
        text=self.c.prompt('artifact_static_v1',{'object':'剑','appearance_direction':LOOKS[0]})['text'];self.assertIn(LOOKS[0],text)

    def test_batch_image_import_and_runtime_128(self):
        g=self.group();p=self.prompt(g);spec=p['frozen_spec'];layout=spec['layout_spec'];cell=spec['source_cell_size']
        width=layout['columns']*cell[0]+(layout['columns']-1)*layout['horizontal_gap']
        height=layout['rows']*cell[1]+(layout['rows']-1)*layout['vertical_gap']
        out=io.BytesIO();im=Image.new('RGBA',(width,height),(0,0,0,0))
        # Synthetic validation fixture only, never an approved production artifact.
        for spot in spec['cell_mapping']:
            x=spot['column']*(cell[0]+layout['horizontal_gap'])+40;y=spot['row']*(cell[1]+layout['vertical_gap'])+40
            im.paste((50,100,80,255),(x,y,x+64,y+64))
        im.save(out,format='PNG');source=self.c.upload('test.png',out.getvalue(),'artifact_static_v1',g['set_id'],p['prompt_id'])
        imported=self.c.import_static_set(self.c.plan(source['source_id']),True)
        self.assertEqual(len(imported),5)
        aid=g['asset_ids'][0];self.c.review(aid,1,'needs_review');self.c.review(aid,1,'approved',{k:True for k in REVIEW});self.c.select(aid,1)
        result=self.c.build(aid,1,128,128);asset=self.c.get('asset',aid)
        self.assertEqual([asset['versions'][0]['runtime']['files'][0][k] for k in ('width','height')],[128,128])
        self.assertEqual(self.c.get('source',source['source_id'])['frozen_spec'],p['frozen_spec'])

    def test_http_create_edit_and_prompt_use_existing_authenticated_routes(self):
        app=create_app(self.root,'artifact-manager-test-token-20261018');app.testing=True;client=app.test_client();headers={'Authorization':'Bearer artifact-manager-test-token-20261018'}
        state=client.get('/api/state',headers=headers).json;self.assertTrue(any(t['template_id']=='artifact_static_v1' for t in state['templates']))
        result=client.post('/api/create-named',headers=headers,json={'template_id':'artifact_static_v1','name_zh':'法宝','generation_scope':'asset_set','asset_names':NAMES,'source_container':'sheet'})
        self.assertEqual(result.status_code,200);g=result.json;entries=self.entries(g)
        for row,look in zip(entries,LOOKS):row['appearance_direction']=look
        result=client.post('/api/edit-static-set',headers=headers,json={'set_id':g['set_id'],'asset_list':entries});self.assertEqual(result.status_code,200)
        result=client.post('/api/prompts',headers=headers,json={'template_id':'artifact_static_v1','set_id':g['set_id'],'options':{}})
        self.assertEqual(result.status_code,200);self.assertIn(LOOKS[0],result.json['text'])
        self.assertEqual(client.post('/api/edit-static-set',json={'set_id':g['set_id'],'asset_list':entries}).status_code,401)

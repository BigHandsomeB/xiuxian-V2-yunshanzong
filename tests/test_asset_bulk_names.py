"""Bulk name lists reuse independent Asset/Set/Prompt ownership; no approval on creation."""
import json,tempfile,unittest
from pathlib import Path
from tools.asset_manager.catalog import Catalog,PROJECT
from tools.asset_manager.model import AssetError,identifier
from tools.asset_manager.web import create_app

ORES='凡铁矿 赤铁矿 黑铁矿 青铁矿 精铁矿 赤铜矿 青铜矿 黄铜矿 紫铜矿 锡矿 铅矿 银矿 金矿 乌金矿 白石矿 青石矿 黑石矿 赤石矿 黄石矿 云母石 石英矿 白玉矿 青玉矿 墨玉矿 赤玉矿 玛瑙矿 硫磺矿 寒石矿 火纹石 磁石矿'.split()

class BulkAssetNamesTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=PROJECT/'tests');self.addCleanup(self.tmp.cleanup)
        self.c=Catalog(Path(self.tmp.name)/'assets')
    def group(self,names=ORES):
        return self.c.create_named('resource_icon_v1','凡品矿物','asset_set',names,source_container='image_set')
    def test_thirty_names_create_independent_records_without_approval(self):
        group=self.group();self.assertEqual(len(group['asset_ids']),30);self.assertEqual(len(set(group['asset_ids'])),30)
        for aid,name in zip(group['asset_ids'],ORES):
            self.assertTrue(aid.isascii());identifier(aid)
            asset=self.c.get('asset',aid)
            self.assertEqual(asset['name_zh'],name);self.assertEqual(asset['frame_count'],1)
            self.assertEqual(asset['versions'],[]);self.assertIsNone(asset['current_approved_version'])
        self.assertEqual(self.c.completeness(group['set_id'])['total'],30)
        self.assertEqual(json.loads(self.c.path('manifest.json').read_text())['assets'],{})
    def test_prompt_reads_saved_image_set_with_order_and_five_by_six_mapping(self):
        group=self.group();prompt=self.c.prompt(group['template_id'],{},set_id=group['set_id']);spec=prompt['frozen_spec']
        self.assertEqual(spec['asset_count'],30);self.assertEqual(spec['frame_counts'],{'icon':1})
        self.assertEqual(spec['asset_order'],group['asset_ids'])
        self.assertEqual([i['name_zh'] for i in spec['asset_list']],ORES)
        self.assertEqual((spec['grid_rows'],spec['grid_columns']),(5,6))
        self.assertEqual([(i['row'],i['column']) for i in spec['cell_mapping']],[(n//6,n%6) for n in range(30)])
        self.assertEqual([i['asset_id'] for i in spec['cell_mapping']],group['asset_ids'])
        positions=[prompt['text'].index(f'{i+1}. {name} (') for i,name in enumerate(ORES)]
        self.assertEqual(positions,sorted(positions));self.assertIn('30 different independent game assets',prompt['text'])
    def test_appending_names_keeps_existing_ids_and_previous_prompt_snapshot(self):
        group=self.group(ORES[:2]);old=self.c.prompt(group['template_id'],{},set_id=group['set_id'])
        items=[dict(asset_id=aid,name_zh=name) for aid,name in zip(group['asset_ids'],ORES[:2])]+[dict(name_zh=name) for name in ORES[2:]]
        expanded=self.c.edit_static_set(group['set_id'],items,'independent')
        self.assertEqual(expanded['asset_ids'][:2],group['asset_ids']);self.assertEqual(len(expanded['asset_ids']),30)
        self.assertEqual(self.c.get('prompt',old['prompt_id']),old)
        current=self.c.prompt(group['template_id'],{},set_id=group['set_id'])
        self.assertEqual([i['name_zh'] for i in current['frozen_spec']['asset_list']],ORES)
        self.assertEqual(current['frozen_spec']['asset_count'],30)
    def test_thirty_names_sheet_rejected_without_creating_assets(self):
        before=self.c.list('asset');before_sets=self.c.list('set')
        with self.assertRaises(AssetError):
            self.c.create_named('resource_icon_v1','凡品矿物','asset_set',ORES,source_container='sheet')
        self.assertEqual(self.c.list('asset'),before);self.assertEqual(self.c.list('set'),before_sets)

    def test_unfiltered_duplicates_are_rejected_atomically(self):
        before=self.c.list('asset');before_sets=self.c.list('set')
        with self.assertRaises(AssetError):self.group(ORES+['凡铁矿'])
        self.assertEqual(self.c.list('asset'),before);self.assertEqual(self.c.list('set'),before_sets)
    def test_same_names_in_another_group_do_not_overwrite_records(self):
        a=self.group();before=[self.c.get('asset',aid) for aid in a['asset_ids']];b=self.group()
        self.assertNotEqual(a['set_id'],b['set_id']);self.assertFalse(set(a['asset_ids'])&set(b['asset_ids']))
        self.assertEqual([self.c.get('asset',aid) for aid in a['asset_ids']],before)
    def test_readonly_http_preview_calculates_thirty_without_creating_assets(self):
        token='a-private-test-only-access-token';app=create_app(self.c.root,token)
        c=app.extensions['asset_catalog'];before=c.list('asset');before_sets=c.list('set')
        with app.test_client() as client:
            response=client.post('/api/create-preview',json=dict(template_id='resource_icon_v1',name_zh='凡品矿物',generation_scope='asset_set',source_container='image_set',asset_names=ORES),headers={'Authorization':'Bearer '+token})
        self.assertEqual(response.status_code,200);data=response.get_json()
        self.assertEqual(data['asset_count'],30);self.assertEqual((data['grid_rows'],data['grid_columns']),(5,6))
        self.assertEqual([i['name_zh'] for i in data['asset_list']],ORES)
        self.assertEqual(c.list('asset'),before);self.assertEqual(c.list('set'),before_sets)

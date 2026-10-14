"""Isolated visual projection tests; no live Save, Source or Pipeline writes."""
import copy
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from src.rendering.asset_catalog import metadata, MINERALS, PILLS
from src.rendering.game import manifest, present, bindings
from src.rendering.game_runtime import GameRuntimeAssets

class AssetVisualIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);(self.root/'registry').mkdir();(self.root/'runtime').mkdir()
        self.db=self.root/'registry/catalog.sqlite3'
        with sqlite3.connect(self.db) as db:db.execute('CREATE TABLE metadata(kind TEXT,id TEXT,body TEXT,PRIMARY KEY(kind,id))')
        self.pill=bindings()['icons']['pill'];self.snapshot={}
        self.set(PILLS[1],'修炼丹体系',[self.pill]);self.asset(self.pill,'凝气丹',PILLS[1]);self.assets=GameRuntimeAssets(self.root);self.publish()
    def put(self,kind,id,row):
        with sqlite3.connect(self.db) as db:db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?,?)',(kind,id,json.dumps(row,ensure_ascii=False)))
    def set(self,id,name,order):self.put('set',id,{'name_zh':name,'asset_ids':order})
    def asset(self,id,name,sid,**patch):
        row={'asset_id':id,'name_zh':name,'category':'pill','set_id':sid,'runtime_role':'item_icon','lifecycle_status':'active','current_approved_version':1,'versions':[{'version':1,'art_status':'approved'}]};row.update(patch);self.put('asset',id,row)
        path=self.root/'runtime'/f'{id}.png';path.write_bytes(b'isolated-test-runtime');self.snapshot[id]={'version':1,'files':[{'file':'runtime/'+path.name,'width':48,'height':48,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}]}
    def publish(self):(self.root/'manifest.json').write_text(json.dumps({'schema_version':1,'assets':self.snapshot}))
    def rows(self):return [r for g in manifest(self.assets)['catalog']['groups'] for r in g['items']]
    def test_approved_runtime_loading(self):
        rows=self.rows();self.assertEqual(len(rows),1);self.assertFalse(rows[0]['visual']['fallback']);self.assertTrue(rows[0]['visual']['asset']['url'].startswith('/game/runtime/'))
    def test_official_pill_binding_is_one_stable_item(self):
        self.assertEqual(self.pill,'icon.pill.a05aa9179e82c');self.assertEqual(self.rows()[0]['gameplay_item_id'],'pill');self.assertEqual(manifest(self.assets)['icons']['pill'],self.rows()[0]['visual'])
    def test_unapproved_not_listed(self):
        self.asset(self.pill,'凝气丹',PILLS[1],versions=[{'version':1,'art_status':'draft'}]);self.assertEqual(self.rows(),[])
    def test_unpublished_not_listed(self):
        self.snapshot={};self.publish();self.assertEqual(self.rows(),[])
    def test_approved_version_must_match_runtime(self):
        self.snapshot[self.pill]['version']=2;self.publish();self.assertEqual(self.rows(),[])
    def test_deprecated_not_listed(self):
        self.asset(self.pill,'凝气丹',PILLS[1],lifecycle_status='deprecated');self.assertEqual(self.rows(),[])
    def test_set_order_not_filename_or_chinese_name(self):
        self.asset('icon.pill.z','同名丹',PILLS[1]);self.asset('icon.pill.a','同名丹',PILLS[1]);self.set(PILLS[1],'修炼丹体系',['icon.pill.z',self.pill,'icon.pill.a']);self.publish();self.assertEqual([r['asset_id'] for r in self.rows()],['icon.pill.z',self.pill,'icon.pill.a'])
    def test_six_mineral_grades_keep_declared_order(self):
        for i,(sid,grade) in enumerate(reversed(MINERALS)):
            aid='icon.resource.m'+str(i);self.set(sid,grade,[aid]);self.asset(aid,grade,sid,category='resource')
        self.publish();groups=manifest(self.assets)['catalog']['groups'];self.assertEqual([g['grade'] for g in groups if g['category']=='mineral'],[grade for _,grade in MINERALS])
    def test_future_approved_asset_appears_on_reload_without_gameplay(self):
        self.assertEqual(len(self.rows()),1);self.asset('icon.pill.new','新丹',PILLS[1]);self.publish();rows=self.rows();self.assertEqual(len(rows),2);self.assertIsNone(rows[1]['gameplay_item_id']);self.assertEqual(rows[1]['gameplay_status'],'素材已登记，玩法尚未开放。')
    def test_missing_runtime_retains_catalog_fallback(self):
        (self.root/'runtime'/f'{self.pill}.png').unlink();self.assertTrue(self.rows()[0]['visual']['fallback'])
    def test_no_metadata_gameplay_icons_still_resolve(self):
        self.db.unlink();m=manifest(self.assets);self.assertFalse(m['catalog']['available']);self.assertFalse(m['icons']['pill']['fallback'])
    def test_corrupt_metadata_fails_safely(self):
        self.db.write_bytes(b'not-a-database');self.assertFalse(manifest(self.assets)['catalog']['available'])
    def test_registry_symlink_rejected(self):
        old=self.root/'registry/old.sqlite3';self.db.rename(old);self.db.symlink_to(old);self.assertFalse(manifest(self.assets)['catalog']['available'])
    def test_projection_does_not_mutate_inventory_or_view(self):
        view={'holdings':{'pill':{'quantity':6}},'inventory':{'pill':{'quantity':6}},'buildings':{}};before=copy.deepcopy(view);visual=present(view,self.assets);manifest(self.assets);self.assertEqual(view,before);self.assertFalse(visual['icons']['pill']['fallback']);self.assertNotIn('catalog',visual)
    def test_registry_read_is_nonmutating_and_no_private_metadata(self):
        before=self.db.read_bytes();m=manifest(self.assets);self.assertEqual(self.db.read_bytes(),before);public=json.dumps(m);self.assertNotIn('sqlite3',public);self.assertNotIn('source_id',public);self.assertNotIn('quantity',public);self.assertNotIn('effect',json.dumps(m['catalog']))
    def test_metadata_absence_never_creates_registry(self):
        self.db.unlink();manifest(self.assets);self.assertFalse(self.db.exists())

"""Read-only concept/presentation safeguards, isolated Registry/Runtime fixtures."""
import copy,hashlib,json,sqlite3,tempfile,unittest,re
from pathlib import Path
from src.rendering.concepts import concepts
from src.rendering.game import bindings,manifest,present
from src.rendering.game_runtime import GameRuntimeAssets

class ConceptContractTests(unittest.TestCase):
    def test_complete_explicit_list_is_81_after_user_confirmation(self):
        self.assertEqual(len(concepts()),81)
        self.assertEqual(len({r['concept_id'] for r in concepts()}),81)
    def test_blood_single_identity_two_categories_and_original_assets(self):
        rows=[r for r in concepts() if r['display_name_zh']=='灵兽精血'];self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['category'],['material','beast']);self.assertEqual(len(rows[0]['alternate_asset_ids']),1)
    def test_ore_and_spirit_ore_independent(self):
        r=next(r for r in concepts() if r['concept_id']=='concept.spirit_iron_ore')
        self.assertNotEqual(bindings()['icons']['ore'],r['asset_id']);self.assertEqual(r['gameplay_id'],'spirit_iron_ore')
        self.assertEqual(bindings()['icons']['ore'],'icon.resource.a8b24101ca3fd')
    def test_ingots_independent(self):
        r=next(r for r in concepts() if r['concept_id']=='concept.spirit_iron_ingot')
        self.assertNotEqual(bindings()['icons']['ingot'],r['asset_id']);self.assertEqual(r['gameplay_id'],'spirit_iron_ingot')
    def test_stone_uses_existing_basic_resource_asset_and_identity(self):
        from src.data.dungeons.definitions import load_dungeons
        from src.data.registry import DefinitionKey
        row=next(r for r in concepts() if r['concept_id']=='concept.stone')
        self.assertEqual(row['gameplay_id'],'stone')
        self.assertEqual(row['display_name_zh'],'石材')
        self.assertEqual(bindings()['icons']['stone'],row['asset_id'])
        self.assertEqual(load_dungeons(management=True).lookup(DefinitionKey('resources','stone')).display_name,'石材')
    def test_money_is_not_stone_or_grade_balance(self):
        r={r['concept_id']:r for r in concepts()};self.assertEqual(bindings()['icons']['coins'],r['concept.spirit_money']['asset_id'])
        for key in ['spirit_stone','spirit_stone_low','spirit_stone_mid','spirit_stone_high','spirit_stone_supreme']:
            self.assertEqual(r['concept.'+key]['gameplay_id'],{'spirit_stone':'spirit_stone_low','spirit_stone_low':'spirit_stone_mid','spirit_stone_mid':'spirit_stone_high','spirit_stone_high':'spirit_stone_supreme','spirit_stone_supreme':'spirit_stone_immortal'}[key]);self.assertNotEqual(r['concept.'+key]['asset_id'],bindings()['icons']['coins'])
    def test_approved_player_binding_is_presentation_only(self):
        self.assertEqual(bindings()['combat_bindings']['player.combat.hero'],'character.af8b2d2ce9282.idle')
    def test_existing_pill_identity_preserved(self):self.assertEqual(bindings()['icons']['pill'],'icon.pill.a05aa9179e82c')
    def test_herb_and_wood_keep_ids(self):
        r={r['gameplay_id']:r for r in concepts() if r['gameplay_id']};self.assertEqual(r['herb']['display_name_zh'],'灵草');self.assertEqual(r['wood']['display_name_zh'],'灵木')
    def test_seed_specificity_remains_pending(self):
        r=next(r for r in concepts() if r['concept_id']=='concept.seed');self.assertEqual(r['gameplay_status'],'NEEDS_CONFIRMATION');self.assertIsNone(r['gameplay_id'])
    def test_system_icons_include_16_core_concepts_without_gameplay_effects(self):
        core={'hp','mp','cultivation','attack','defense','power','disciples','production',
              'pause','automation','auto_combat','light','dark','capacity','locked','favorite'}
        icons=bindings()['system_icons']
        self.assertTrue(core<=icons.keys())
        self.assertEqual(len({icons[key] for key in core}),16)
        for r in concepts():self.assertFalse({'quantity','price','effect','recipe','drop_probability','stats'}&r.keys())
    def test_each_concept_has_required_fields(self):
        for r in concepts():self.assertTrue({'concept_id','display_name_zh','category','asset_id','template_id','gameplay_status','gameplay_id','possible_future_use'}<=r.keys())

class ConceptRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);(self.root/'registry').mkdir();(self.root/'runtime').mkdir()
        self.db=self.root/'registry/catalog.sqlite3';self.snapshot={};self.assets=GameRuntimeAssets(self.root)
        with sqlite3.connect(self.db) as db:db.execute('CREATE TABLE metadata(kind TEXT,id TEXT,body TEXT,PRIMARY KEY(kind,id))')
        self.herb=next(r for r in concepts() if r['concept_id']=='concept.herb');self.add(self.herb);self.publish()
    def put(self,kind,key,value):
        with sqlite3.connect(self.db) as db:db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?,?)',(kind,key,json.dumps(value,ensure_ascii=False)))
    def add(self,concept,status='approved',template=None):
        aid=concept['asset_id'];sid='asset_set.fixture.'+aid;template=template or concept['template_id']
        self.put('set',sid,{'name_zh':'隔离素材集','asset_ids':[aid]})
        self.put('asset',aid,{'asset_id':aid,'name_zh':concept['display_name_zh'],'category':'material','set_id':sid,'template_id':template,'runtime_role':'item_icon','current_approved_version':1,'versions':[{'version':1,'art_status':status,'frozen_spec':{'template_id':concept['template_id'],'template_version':4}}]})
        path=self.root/'runtime'/f'{aid}.png';path.write_bytes(b'isolated-runtime');digest=hashlib.sha256(path.read_bytes()).hexdigest()
        self.snapshot[aid]={'version':1,'export_origin':{'template_id':template,'template_version':4},'files':[{'file':'runtime/'+path.name,'width':48,'height':48,'sha256':digest}]}
    def publish(self):(self.root/'manifest.json').write_text(json.dumps({'schema_version':1,'assets':self.snapshot}))
    def rows(self):return [r for g in manifest(self.assets)['catalog']['groups'] for r in g['items']]
    def test_approved_concept_has_runtime_status(self):self.assertEqual(self.rows()[0]['runtime_status'],'RUNTIME_READY')
    def test_unapproved_concept_never_enters_catalog(self):self.add(self.herb,status='draft');self.assertEqual(self.rows(),[])
    def test_unpublished_concept_never_enters_catalog(self):self.snapshot={};self.publish();self.assertEqual(self.rows(),[])
    def test_template_mismatch_rejected_catalog_and_icon(self):
        self.add(self.herb,template='pill_icon_v1');self.publish();self.assertEqual(self.rows(),[]);self.assertTrue(manifest(self.assets)['icons']['herb']['fallback'])
    def test_runtime_version_mismatch_rejected(self):
        self.snapshot[self.herb['asset_id']]['export_origin']['template_version']=999;self.publish();self.assertEqual(self.rows(),[])
    def test_missing_image_fallback_not_gameplay_failure(self):
        (self.root/'runtime'/f"{self.herb['asset_id']}.png").unlink();self.assertTrue(self.rows()[0]['visual']['fallback'])
    def test_source_file_cannot_be_runtime(self):
        (self.root/'source.png').write_bytes(b'source');self.snapshot[self.herb['asset_id']]['files'][0]['file']='source.png';self.publish();self.assertTrue(manifest(self.assets)['icons']['herb']['fallback'])
    def test_checksum_failure_not_served(self):
        (self.root/'runtime'/f"{self.herb['asset_id']}.png").write_bytes(b'broken');self.assertIsNone(self.assets.file(self.herb['asset_id'],self.snapshot[self.herb['asset_id']]['files'][0]['sha256']))
    def test_reload_new_concept_without_creating_inventory(self):
        before=len(self.rows());r=next(r for r in concepts() if r['concept_id']=='concept.beast_egg');self.add(r);self.publish();self.assertEqual(len(self.rows()),before+1);self.assertIsNone(next(row for row in self.rows() if row['asset_id']==r['asset_id'])['gameplay_item_id'])
    def test_one_map_same_herb_in_view_and_manifest(self):
        v={'holdings':{'herb':{'quantity':7}},'buildings':{}};self.assertEqual(present(v,self.assets)['icons']['herb'],manifest(self.assets)['icons']['herb'])
    def test_read_does_not_change_registry_or_gameplay(self):
        v={'holdings':{'herb':{'quantity':7}},'buildings':{},'world':{'paused':True},'combat':None};before=copy.deepcopy(v);raw=self.db.read_bytes();present(v,self.assets);manifest(self.assets);self.assertEqual(v,before);self.assertEqual(self.db.read_bytes(),raw)
    def test_no_source_paths_or_rules_in_public_concepts(self):
        row=self.rows()[0];self.assertNotIn('source_id',row);self.assertNotIn('quantity',row);self.assertNotIn('price',row)

class ThemeDeliveryTests(unittest.TestCase):
    def test_pre_css_script_is_external_csp_safe(self):
        page=Path('src/ui/pages/game/index.html').read_text();self.assertLess(page.index('theme-bootstrap.js'),page.index('game.css'));self.assertNotIn('<script> ',page)
    def test_palette_is_shared_not_two_pages(self):
        css=Path('src/ui/pages/game/static/theme.css').read_text();self.assertIn(':root[data-theme=dark]',css)
        shared=css+Path('src/ui/pages/game/static/game.css').read_text()+Path('src/ui/pages/game/static/battle/battle.css').read_text()
        for word in ['building-entry','item-icon','world-bar','connection','secondary']:self.assertIn(word,shared)
        for token in ['--bg','--surface','--ink','--accent','--q-uncommon']:self.assertIn(token,css)
        self.assertIn("@import './theme.css'",shared)
    def test_theme_uses_no_authoritative_writes(self):
        source=Path('src/ui/pages/game/static/theme.js').read_text();self.assertNotIn('fetch(',source);self.assertNotIn('api(',source);self.assertIn('localStorage',source);self.assertIn('visibilitychange',source)

class MalformedRuntimeTests(unittest.TestCase):
    setUp=ConceptRuntimeTests.setUp
    put=ConceptRuntimeTests.put
    add=ConceptRuntimeTests.add
    publish=ConceptRuntimeTests.publish
    rows=ConceptRuntimeTests.rows
    # Test malformed presentation metadata against the same isolated setup, not live Manifest.
    def test_malformed_origin_falls_back_without_breaking_game_view(self):
        self.snapshot[self.herb['asset_id']]['export_origin']='bad';self.publish();self.assertTrue(manifest(self.assets)['icons']['herb']['fallback'])
    def test_current_profile_export_keeps_frozen_history_compatible(self):
        origin=self.snapshot[self.herb['asset_id']]['export_origin'];origin.update(policy='current_item_profile',template_version=999);self.publish()
        self.assertFalse(manifest(self.assets)['icons']['herb']['fallback']);self.assertEqual(len(self.rows()),1)

class ResourceOverviewTests(unittest.TestCase):
    def test_explicit_overview_is_read_only_and_does_not_include_loot(self):
        from src.rendering.game import resource_overview
        class Missing:
            def resolve(self,*args):return None
        rows=resource_overview(Missing(),{})
        self.assertEqual(len(rows),14)
        self.assertEqual([r['name'] for r in rows],['下品灵石','中品灵石','上品灵石','极品灵石','仙品灵石','灵钱','灵草','灵木','灵铁矿','灵铁锭','普通木材','石材','灵谷','灵泉水'])
        self.assertEqual(rows[5]['gameplay_id'],'coins');self.assertEqual(rows[13]['gameplay_id'],'spring_water');self.assertEqual(rows[10]['gameplay_id'],'ordinary_wood');self.assertFalse(any(r['gameplay_id']=='seed_grain' for r in rows));self.assertEqual(len(rows)+1,3*5)
        self.assertEqual(rows[0]['gameplay_id'],'spirit_stone_low');self.assertEqual(rows[8]['gameplay_id'],'spirit_iron_ore');self.assertEqual([r['visual']['asset_id'] for r in rows[:5]],['icon.resource.a2cd27cf0d526','icon.resource.a8e85ab24e156','icon.resource.aadc6def190e3','icon.resource.a56aff0caeced','icon.resource.a1170d4074d0a']);self.assertEqual([r['gameplay_id'] for r in rows[:5]],['spirit_stone_low','spirit_stone_mid','spirit_stone_high','spirit_stone_supreme','spirit_stone_immortal']);self.assertEqual([bindings()['icons'][r['gameplay_id']] for r in rows[:5]],[r['visual']['asset_id'] for r in rows[:5]])
        self.assertTrue(all('quantity' not in r for r in rows))
    def test_home_resource_grid_is_five_columns_with_responsive_icons(self):
        css=Path('src/ui/pages/game/static/game.css').read_text()
        rule=re.search(r'\.sect-resource-overview\{([^}]+)',css).group(1)
        self.assertIn('grid-template-columns:repeat(5,minmax(0,1fr))',rule)
        self.assertIn('.sect-resource-overview .item-icon{width:min(48px,100%)',css)
    def test_plain_resources_and_semantic_equipment_quality_frames(self):
        css=Path('src/ui/pages/game/static/game.css').read_text()
        rule=re.search(r'(?:^|})\s*\.item-icon\s*\{([^}]+)',css).group(1)
        self.assertIn('border:0',rule);self.assertIn('background:transparent',rule);self.assertIn('--q:transparent',rule)
        self.assertIn('.item-icon.quality-uncommon{--q:var(--q-uncommon)}',css)
        self.assertIn('inset 0 0 0 2px var(--q)',css)

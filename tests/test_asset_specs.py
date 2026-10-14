"""Pixel specification regression: real defaults and prompt/source/import/runtime continuity."""
import copy, io, json, tempfile, unittest
from pathlib import Path
from PIL import Image
from tools.asset_manager.catalog import Catalog, PROJECT
from tools.asset_manager.model import AssetError, REVIEW, templates
from tools.asset_manager.specs import freeze_spec, grid_regions, validate_profile
from tools.asset_manager.prompts import compile_prompt
from tools.asset_manager.web import create_app

def raster(size):
    out=io.BytesIO();Image.new("RGBA",size,(20,80,45,255)).save(out,format="PNG");return out.getvalue()

class PixelProfileTests(unittest.TestCase):
    def setUp(self):
        self.document=json.loads((PROJECT/"assets/templates/templates.json").read_text())
        self.templates=templates(self.document)

    def spec(self,key="character_compact_v1",**options):return freeze_spec(self.templates[key],options)

    def test_character_default_profile_and_canvas_separation(self):
        s=self.spec();self.assertEqual(s["subject_logic_size"],[48,64]);self.assertEqual(s["source_cell_size"],[128,128]);self.assertEqual(s["runtime_profile"]["frame_size"],[128,128]);self.assertEqual((s["spacing"],s["inner_safe_padding"]),(32,24));self.assertEqual(s["anchor"]["type"],"bottom_center")

    def test_monster_defaults(self):
        s=self.spec("monster_compact_v1");self.assertEqual(s["subject_logic_size"],[48,48]);self.assertEqual(s["frame_counts"],dict(idle=2,attack=3,hit=1,death=3))

    def test_boss_defaults(self):
        s=self.spec("boss_v1");self.assertEqual(s["source_cell_size"],[160,160]);self.assertEqual(s["spacing"],48);self.assertEqual(s["frame_counts"],dict(idle=2,attack=3,skill=4,hit=1,death=3))

    def test_icon_defaults(self):
        s=self.spec("resource_icon_v1");self.assertEqual(s["subject_logic_size"],[48,48]);self.assertEqual(s["source_cell_size"],[96,96]);self.assertEqual(s["runtime_profile"]["policy"],"crop_subject")

    def test_pill_choices_do_not_invent_gameplay_quality(self):
        a=self.spec("pill_icon_v1");b=self.spec("pill_icon_v1",subject_logic_size=[48,48]);self.assertEqual(a["runtime_profile"]["frame_size"],[48,48]);self.assertEqual(b["runtime_profile"]["frame_size"],[48,48]);self.assertNotIn("rarity",b)

    def test_interior_scene_is_six_states_not_sprite_frames(self):
        s=self.spec("building_interior_scene_v1");self.assertEqual(s["subject_logic_size"],[256,144]);self.assertEqual(s["output_mode"],"scene_set");self.assertEqual(list(s["frame_counts"].values()),[1]*6)

    def test_character_frames_optional_walk_and_special(self):
        s=self.spec();self.assertEqual(s["frame_counts"]["walk"],4);self.assertNotIn("special",s["frame_counts"])
        counts=dict(idle=2,walk=4,attack=4,cast=4,hit=2,death=4)
        s=self.spec(counts=counts);self.assertEqual(s["frame_counts"],counts);self.assertEqual((s["row_count"],s["column_count"]),(6,4))

    def test_fish_and_bird_do_not_inherit_combat_defaults(self):
        for family in ("fish","bird"):
            s=self.spec("spirit_beast_v1",family=family);self.assertEqual(s["frame_counts"],dict(idle=2,move=4));self.assertEqual(s["source_cell_size"],[128,128])

    def test_large_beast_has_explicit_larger_cell(self):
        s=self.spec("spirit_beast_v1",family="wide");self.assertEqual(s["subject_logic_size"],[128,96]);self.assertEqual(s["source_cell_size"],[192,160])

    def test_working_disciple_family_not_combat_set(self):
        s=self.spec(family="working_disciple");self.assertEqual(s["frame_counts"],dict(idle=2,work=4));self.assertNotIn("attack",s["action_spec"])

    def test_scene_tile_and_navigation_families(self):
        self.assertEqual(self.spec("environment_scene_v1")["runtime_profile"]["frame_size"],[320,180])
        self.assertEqual(self.spec("environment_scene_v1",family="terrain32")["runtime_profile"]["frame_size"],[32,32])
        self.assertEqual(self.spec("environment_scene_v1",family="navigation")["runtime_profile"]["frame_size"],[24,24])

    def test_profile_rejects_bool_and_unfitting_padding(self):
        p=copy.deepcopy(self.templates["character_compact_v1"]["pixel_size_profile"]);p["spacing"]=True
        with self.assertRaises(AssetError):validate_profile(p)
        p["spacing"]=32;p["inner_safe_padding"]=60
        with self.assertRaises(AssetError):validate_profile(p)

    def test_unknown_profile_reference_rejected(self):
        self.document["templates"][0]["pixel_size_profile"]="missing"
        with self.assertRaises(AssetError):templates(self.document)

    def test_advanced_override_does_not_mutate_template(self):
        before=copy.deepcopy(self.templates)
        s=self.spec(advanced_override=True,profile_override={"subject_logic_size":[64,64]})
        self.assertEqual(s["subject_logic_size"],[64,64]);self.assertEqual(before,self.templates)
        with self.assertRaises(AssetError):self.spec(profile_override={"subject_logic_size":[64,64]})

    def test_override_cannot_reduce_cut_safety(self):
        with self.assertRaises(AssetError):self.spec(advanced_override=True,profile_override={"spacing":0})
        with self.assertRaises(AssetError):self.spec(advanced_override=True,profile_override={"inner_safe_padding":0})

    def test_quality_does_not_change_pixel_profile(self):
        a=self.spec(quality="LEVEL 1");b=self.spec(quality="LEVEL 3");self.assertEqual(a["runtime_profile"],b["runtime_profile"])

    def test_stale_template_version_rejected(self):
        with self.assertRaises(AssetError):self.spec(expected_template_version=99)
        self.assertEqual(self.spec(expected_template_version=3)["template_version"],3)

    def test_arbitrary_runtime_size_rejected(self):
        with self.assertRaises(AssetError):self.spec(runtime_size="2048x2048")
        with self.assertRaises(AssetError):self.spec(runtime_size=True)

    def test_grid_uses_enabled_rows_and_keeps_blank_cells_unassigned(self):
        s=self.spec(counts={"idle":2,"walk":4},extra_columns=6);regions=grid_regions(s)
        self.assertEqual((s["row_count"],s["column_count"]),(2,6));self.assertEqual(len(regions),6)
        self.assertEqual(regions[2],dict(action="walk",frame=1,rect=[0,160,128,128]));self.assertNotIn([320,0,128,128],[r["rect"] for r in regions])

    def test_prompt_contains_logic_cell_safety_and_exact_actions(self):
        text=compile_prompt(self.templates["character_compact_v1"],{"counts":{"idle":2,"walk":4}})
        for value in ("48x64","128x128","32 px","24 px","bottom_center","Row 1: idle, 2 frame(s)","Row 2: walk, 4 frame(s)","unused cell remains transparent","1:4 to 1:4.5"):
            self.assertIn(value,text)

class FrozenSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=PROJECT/"tests")
        self.root=Path(self.temp.name)
        self.document=json.loads((PROJECT/"assets/templates/templates.json").read_text())
        self.template_path=self.root/"templates.json";self.template_path.write_text(json.dumps(self.document))
        self.cat=Catalog(self.root/"assets",template_file=self.template_path)
        self.cat.create_asset("character.test","测试剑修","character_compact_v1")
    def tearDown(self):self.temp.cleanup()

    def source(self,counts=None):
        p=self.cat.prompt("character_compact_v1",{"counts":counts or {"idle":2}},asset_id="character.test")
        return p,self.cat.upload("sheet.png",raster((288,128)),"character_compact_v1",prompt_id=p["prompt_id"])

    def approve(self,asset,version=1):
        self.cat.review(asset,version,"needs_review");self.cat.review(asset,version,"approved",{k:True for k in REVIEW});self.cat.select(asset,version)

    def test_prompt_freezes_version_profile_and_grid(self):
        p,source=self.source();s=p["frozen_spec"]
        self.assertEqual(s["template_version"],3);self.assertEqual(s["frame_counts"],{"idle":2});self.assertEqual(s["grid_spec"]["horizontal_gap"],32);self.assertEqual(source["frozen_spec"],s)

    def test_importer_uses_prompt_snapshot_defaults(self):
        p,source=self.source();plan=self.cat.plan(source["source_id"])
        self.assertEqual([r["rect"] for r in plan["regions"]],[[0,0,128,128],[160,0,128,128]])
        v=self.cat.import_version("character.test",plan,True);self.assertEqual(v["frozen_spec"],p["frozen_spec"])

    def test_template_upgrade_does_not_change_old_source(self):
        p,source=self.source()
        self.document["templates"][0]["template_version"]=3;self.document["templates"][0]["structure"]["idle"]=[3,3]
        self.template_path.write_text(json.dumps(self.document));other=Catalog(self.root/"assets",template_file=self.template_path)
        plan=other.plan(source["source_id"]);v=other.import_version("character.test",plan,True)
        self.assertEqual(len(v["files"]),2);self.assertEqual(v["frozen_spec"]["template_version"],3)
        self.assertEqual(self.cat.get("prompt",p["prompt_id"]),p)

    def test_mutation_of_returned_snapshot_cannot_modify_catalog(self):
        p,source=self.source();source["frozen_spec"]["spacing"]=0
        self.assertEqual(self.cat.get("source",source["source_id"])["frozen_spec"]["spacing"],32)

    def test_no_prompt_upload_creates_explicit_import_snapshot(self):
        source=self.cat.upload("sheet.png",raster((288,128)),"character_compact_v1",spec_options={"counts":{"idle":2}})
        self.assertIsNone(source["prompt_id"]);self.assertEqual(source["specification_origin"],"import_snapshot");self.assertEqual(len(self.cat.plan(source["source_id"])["regions"]),2)

    def test_reject_unselected_action_and_changed_frame_count(self):
        p,source=self.source()
        with self.assertRaises(AssetError):self.cat.plan(source["source_id"],{"attack":4},"manual",regions=[dict(action="attack",frame=i,rect=[0,0,128,128]) for i in range(1,5)])
        with self.assertRaises(AssetError):self.cat.plan(source["source_id"],{"idle":1},"independent")

    def test_manual_geometry_correction_keeps_frozen_semantics(self):
        p,source=self.source();regions=[dict(action="idle",frame=1,rect=[0,0,128,128]),dict(action="idle",frame=2,rect=[156,0,128,128])]
        plan=self.cat.plan(source["source_id"],{"idle":2},"manual",regions=regions)
        v=self.cat.import_version("character.test",plan,True)
        self.assertEqual([{k:value for k,value in r.items() if k!="asset_id"} for r in v["plan"]["regions"]],regions);self.assertEqual(v["frozen_spec"]["spacing"],32)

    def test_runtime_preserves_sprite_canvas_and_anchor(self):
        p,source=self.source();v=self.cat.import_version("character.test",self.cat.plan(source["source_id"]),True);self.approve("character.test")
        built=self.cat.build("character.test",1);self.assertEqual(built["files"][0]["width"],128);self.assertEqual(built["anchor"]["type"],"bottom_center")
        with self.assertRaises(AssetError):self.cat.build("character.test",1,48,64)
        manifest=self.cat.publish();self.assertEqual(manifest["assets"]["character.test"]["runtime_profile"]["frame_size"],[128,128])

    def test_runtime_scene_is_independent_from_source_native_size(self):
        self.cat.create_asset("scene.test","测试环境","environment_scene_v1",state="scene")
        p=self.cat.prompt("environment_scene_v1",{},asset_id="scene.test")
        source=self.cat.upload("scene.png",raster((1280,720)),"environment_scene_v1",prompt_id=p["prompt_id"])
        v=self.cat.import_version("scene.test",self.cat.plan(source["source_id"],mode="independent"),True);self.approve("scene.test")
        b=self.cat.build("scene.test",1);self.assertEqual(v["source_native_size"],[1280,720]);self.assertEqual((b["files"][0]["width"],b["files"][0]["height"]),(320,180))

    def test_icon_subject_crop_does_not_shrink_padding_into_body(self):
        self.cat.create_asset("icon.test","测试丹药","pill_icon_v1",state="icon")
        image=Image.new("RGBA",(96,96),(0,0,0,0));image.paste((255,0,0,255),(24,24,72,72));out=io.BytesIO();image.save(out,format="PNG")
        source=self.cat.upload("pill.png",out.getvalue(),"pill_icon_v1")
        self.cat.import_version("icon.test",self.cat.plan(source["source_id"],mode="independent"),True);self.approve("icon.test")
        built=self.cat.build("icon.test",1)
        with Image.open(self.cat.path(built["files"][0]["file"])) as result:
            self.assertEqual(result.size,(48,48));self.assertEqual(result.getpixel((0,0)),(255,0,0,255))

    def test_snapshot_survives_fresh_catalog(self):
        p,source=self.source();fresh=Catalog(self.root/"assets",template_file=self.template_path)
        self.assertEqual(fresh.get("source",source["source_id"])["frozen_spec"],p["frozen_spec"])

    def test_asset_detail_api_exposes_size_provenance_without_mutation(self):
        # The default web adapter shares the same production authority file.
        p,source=self.source();self.cat.import_version("character.test",self.cat.plan(source["source_id"]),True)
        app=create_app(self.root/"assets","a"*32);client=app.test_client();before=self.cat.export_registry()
        data=client.get("/api/state",headers={"Authorization":"Bearer "+"a"*32}).get_json()
        asset=next(a for a in data["assets"] if a["asset_id"]=="character.test")
        self.assertEqual(asset["size_provenance"]["source_native_size"],[288,128]);self.assertEqual(asset["size_provenance"]["prompt_id"],p["prompt_id"])
        self.assertEqual(before,self.cat.export_registry())

    def test_work_family_asset_and_set_use_own_actions(self):
        self.cat.create_set("set.work","工作弟子","character_compact_v1",["work"],"worker.test",family="working_disciple")
        asset=self.cat.get("asset","worker.test.work")
        self.assertEqual(asset["family"],"working_disciple")
        prompt=self.cat.prompt("character_compact_v1",{"family":"working_disciple","counts":{"work":4}},asset_id=asset["asset_id"])
        self.assertEqual(prompt["frozen_spec"]["frame_counts"],{"work":4})
        with self.assertRaises(AssetError):self.cat.prompt("character_compact_v1",{},asset_id=asset["asset_id"])

    def test_preprofile_prompt_keeps_historical_frame_rule(self):
        old=copy.deepcopy(self.cat.templates["character_compact_v1"])
        old["structure"]["idle"]=[3,3]
        old.pop("pixel_size_profile");old.pop("available_profiles")
        with self.cat.transaction() as conn:
            self.cat.put("prompt","legacy",dict(prompt_id="legacy",template_id="character_compact_v1",set_id=None,template_snapshot=old,options={"counts":{"idle":3}},text="Old exact prompt"),conn,True)
        source=self.cat.upload("old.png",raster((384,128)),"character_compact_v1",prompt_id="legacy")
        plan=self.cat.plan(source["source_id"],{"idle":3},"grid",dict(rows=1,columns=3,frame_width=128,frame_height=128))
        version=self.cat.import_version("character.test",plan,True)
        self.assertTrue(version["frozen_spec"]["legacy"]);self.assertEqual(len(version["files"]),3)

    def test_unbound_legacy_source_requires_explicit_binding(self):
        source=self.cat.upload("raw.png",raster((128,128)),"character_compact_v1")
        with self.cat.transaction() as conn:
            source.pop("frozen_spec");self.cat.put("source",source["source_id"],source,conn)
        with self.assertRaises(AssetError):self.cat.plan(source["source_id"])
        bound=self.cat.bind_source_spec(source["source_id"],{"counts":{"idle":2}})
        self.assertEqual(bound["specification_origin"],"explicit_legacy_import_snapshot")
        with self.assertRaises(AssetError):self.cat.bind_source_spec(source["source_id"])

    def test_profile_api_fills_character_and_scene_without_free_text(self):
        app=create_app(self.root/"assets","a"*32);client=app.test_client();h={"Authorization":"Bearer "+"a"*32}
        for key,logic in (("character_compact_v1",[48,64]),("pill_icon_v1",[48,48]),("building_interior_scene_v1",[256,144])):
            data=client.post("/api/spec",json={"template_id":key},headers=h).get_json();self.assertEqual(data["subject_logic_size"],logic)

if __name__=="__main__":unittest.main()

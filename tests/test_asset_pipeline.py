"""Asset infrastructure tests: temporary V2 workspaces, no gameplay/V1 saves or real art."""
import copy, hashlib, io, json, os, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from tools.asset_manager.catalog import Catalog, PROJECT
from tools.asset_manager.images import decode, png, runtime, MAX_BYTES
from tools.asset_manager.model import AssetError, templates, grid, rectangle, mapping, REVIEW, INTERIOR_REVIEW
from tools.asset_manager.prompts import compile_prompt
from tools.asset_manager.web import create_app

TEMPLATE = "resource_icon_v1"

def image_bytes(size=(8,8), format_name="PNG"):
    # Synthetic deterministic test raster, never registered in the project assets.
    image=Image.new("RGBA",size,(40,90,60,255)); image.putpixel((0,0),(255,0,0,0))
    out=io.BytesIO();image.save(out,format=format_name);return out.getvalue()

class ModelTests(unittest.TestCase):
    def setUp(self):
        self.document=json.loads((PROJECT/"assets/templates/templates.json").read_text())
        self.templates=templates(self.document)

    def test_initial_and_item_templates(self):
        self.assertEqual(len(self.templates),19)
        self.assertIn("battle_background_v1",self.templates)
        self.assertIn("building_interior_scene_v1",self.templates)

    def test_duplicate_template_rejected(self):
        self.document["templates"].append(self.document["templates"][0])
        with self.assertRaises(AssetError):templates(self.document)

    def test_invalid_frame_range(self):
        self.document["templates"][0]["structure"]["idle"]=[12,12]
        with self.assertRaises(AssetError):templates(self.document)

    def test_schema_rejected(self):
        self.document["schema_version"]=999
        with self.assertRaises(AssetError):templates(self.document)

    def test_grid_gap_and_margins(self):
        value=grid(30,20,dict(rows=2,columns=2,frame_width=8,frame_height=6,horizontal_gap=3,vertical_gap=2,margin_left=4,margin_right=3,margin_top=2,margin_bottom=4))
        self.assertEqual(value,[[4,2,8,6],[15,2,8,6],[4,10,8,6],[15,10,8,6]])

    def test_grid_exceeds_bounds(self):
        with self.assertRaises(AssetError):grid(10,10,dict(rows=2,columns=2,frame_width=8,frame_height=8))

    def test_grid_rejects_bool_and_negative(self):
        for bad in [True,-1,1.5]:
            with self.subTest(bad=bad),self.assertRaises(AssetError):grid(10,10,dict(rows=bad,columns=1,frame_width=1,frame_height=1))

    def test_manual_bounds(self):
        self.assertEqual(rectangle([1,2,3,4],8,8),[1,2,3,4])
        for rect in [[1,2,0,4],[7,7,2,2],[-1,0,1,1],[0,0,True,1]]:
            with self.subTest(rect=rect),self.assertRaises(AssetError):rectangle(rect,8,8)

    def test_sprite_mapping_exact_selected_frames(self):
        t=self.templates["character_compact_v1"]
        values=[dict(action="idle",frame=1),dict(action="idle",frame=2)]
        self.assertEqual(mapping(t,values,{"idle":2}),values)
        with self.assertRaises(AssetError):mapping(t,values+values,{"idle":2})

    def test_prompt_uses_template_counts(self):
        self.assertIn("48x48",compile_prompt(self.templates[TEMPLATE],{}))
        p=compile_prompt(self.templates["character_compact_v1"],{"counts":{"walk":4},"object":"剑修"})
        self.assertIn("Row 1: walk, 4 frame(s)",p)
        self.assertNotIn("Row 2",p)
        self.assertIn("AI must not add actions",p)
        self.assertIn("[Logical Pixels and Runtime Target]",p)

    def test_generated_instructions_are_english_with_rule_provenance(self):
        from tools.asset_manager.prompts import project_rules
        template=self.templates["building_interior_scene_v1"]
        context, fingerprints=project_rules(template)
        text=compile_prompt(template,{"state":"master"},context)
        self.assertFalse(any("\u4e00" <= c <= "\u9fff" for c in text))
        self.assertIn("[This Asset]",text)
        self.assertIn("[Final Output Goal]",text)
        self.assertIn("WORLD FIRST / SCENE FIRST / MOBILE FIRST",text)
        self.assertEqual(len(fingerprints),6)

    def test_prompt_rejects_extra_frames(self):
        with self.assertRaises(AssetError):compile_prompt(self.templates["character_compact_v1"],{"counts":{"idle":12}})

    def test_interior_prompt_requires_master(self):
        with self.assertRaises(AssetError):compile_prompt(self.templates["building_interior_scene_v1"],{"counts":{"stable":1}})
        text=compile_prompt(self.templates["building_interior_scene_v1"],{"counts":{"stable":1},"master_reference":"scene.master"})
        self.assertIn("same camera",text)

    def test_png_webp_lossless_pixels(self):
        image=decode(image_bytes(),"test.png")
        for fmt in ["png","webp"]:
            with Image.open(io.BytesIO(runtime(image,16,16,fmt))) as built:
                self.assertEqual(built.convert("RGBA").getpixel((0,0)),image.getpixel((0,0)))
                self.assertEqual(built.size,(16,16))

    def test_resize_does_not_stretch(self):
        with self.assertRaises(AssetError):runtime(Image.new("RGBA",(8,8)),8,16,"png")

    def test_upload_invalid_types_and_names(self):
        for name in ["../../a.png","/a.png","a\\b.png",".hidden.png","file.py","x.svg"]:
            with self.subTest(name=name),self.assertRaises(AssetError):decode(image_bytes(),name)
        with self.assertRaises(AssetError):decode(b"not an image","a.png")
        with self.assertRaises(AssetError):decode(image_bytes(),"a.jpg")

    def test_upload_display_filename_punctuation_and_unicode_spaces(self):
        for name in ["丹鼎阁【旺火】.png", "ChatGPT Image Oct 6, 2026 at 04:12:38 PM.png",
                     "ChatGPT Image Oct 6, 2026, 04_12_38\u202fPM.png", "丹鼎阁🔥（最终）.PNG"]:
            with self.subTest(name=name):
                self.assertEqual(decode(image_bytes(), name).size, (8, 8))

    def test_upload_filename_controls_and_paths_remain_rejected(self):
        for name in ["../../a.png", "/a.png", "a\\b.png", "C:escape.png", ".hidden.png",
                     "a\x00.png", "a\n.png", "a\t.png", "a\u202e.png", "a\u2028.png",
                     "a\ud800.png", "a" * 161 + ".png"]:
            with self.subTest(name=repr(name)), self.assertRaises(AssetError):
                decode(image_bytes(), name)

    def test_upload_size_limit(self):
        with self.assertRaises(AssetError):decode(b"x"*(MAX_BYTES+1),"a.png")

    def test_mapping_boolean_frame_rejected(self):
        with self.assertRaises(AssetError):mapping(self.templates[TEMPLATE],[dict(action="icon",frame=True)],{"icon":1})

    def test_non_integer_scale_requires_acknowledgement(self):
        image=Image.new("RGBA",(8,8))
        with self.assertRaises(AssetError):runtime(image,6,6,"png")
        self.assertTrue(runtime(image,6,6,"png",True))

    def test_upload_dimension_limit(self):
        with self.assertRaises(AssetError):decode(image_bytes((8193,1)),"too-wide.png")

    def test_animated_upload_rejected(self):
        out=io.BytesIO();a=Image.new("RGBA",(2,2),"red");b=Image.new("RGBA",(2,2),"blue")
        a.save(out,format="PNG",save_all=True,append_images=[b],duration=100)
        with self.assertRaises(AssetError):decode(out.getvalue(),"animated.png")

    def test_monster_optional_actions_not_default(self):
        text=compile_prompt(self.templates["monster_compact_v1"],{})
        self.assertNotIn("move, 4 frame(s)",text)
        self.assertIn("Row 4: death",text)

    def test_master_prompt_is_one_complete_scene(self):
        text=compile_prompt(self.templates["building_interior_scene_v1"],{"state":"master"})
        self.assertIn("one complete image",text)
        self.assertNotIn("Row 1:",text)

class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=PROJECT/"tests")
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/"assets"
        self.cat=Catalog(self.root)
        self.cat.create_asset("icon.resource.ore","测试矿石",TEMPLATE,state="icon",tags=["ore"])

    def upload(self,template=TEMPLATE,set_id=None,prompt_id=None,size=(8,8),spec_options=None):
        return self.cat.upload("source.png",image_bytes(size),template,set_id,prompt_id,spec_options=spec_options)

    def version(self,asset="icon.resource.ore",template=TEMPLATE,action="icon",master=False,set_id=None):
        source=self.upload(template,set_id,size=(16,9) if template=="building_interior_scene_v1" else (8,8))
        plan=self.cat.master_plan(source["source_id"]) if master else self.cat.plan(source["source_id"],{action:1},"independent")
        return self.cat.import_version(asset,plan,True,master)

    def approve(self,asset="icon.resource.ore",version=1):
        self.cat.review(asset,version,"needs_review")
        self.cat.review(asset,version,"approved",{k:True for k in REVIEW+INTERIOR_REVIEW})
        self.cat.select(asset,version)

    def built(self):
        self.version();self.approve();self.cat.build("icon.resource.ore",1);return self.cat.publish()

    def test_danding_slots_missing_and_no_fake_files(self):
        c=self.cat.completeness("scene_set.danding.interior.v1")
        self.assertEqual((c["total"],c["complete"],c["approved"],c["runtime"]),(6,0,0,0))
        self.assertEqual(len(c["slots"]),7)
        self.assertTrue(all(s["status"]=="missing_source" for s in c["slots"].values()))
        self.assertFalse((self.root/"source").exists())

    def test_duplicate_asset_and_set_rejected(self):
        with self.assertRaises(AssetError):self.cat.create_asset("icon.resource.ore","new",TEMPLATE)
        with self.assertRaises(AssetError):self.cat.create_set("scene_set.danding.interior.v1","new","building_interior_scene_v1",["stable"],"other")

    def test_set_creation_is_atomic_on_collision(self):
        self.cat.create_asset("collision.master","collision",TEMPLATE)
        with self.assertRaises(AssetError):self.cat.create_set("test.set","Test",TEMPLATE,["icon"],"collision")
        self.assertIsNone(self.cat.get("set","test.set",missing=True))

    def test_rename_keeps_identity(self):
        value=self.cat.rename("icon.resource.ore","改名",["metal"])
        self.assertEqual(value["asset_id"],"icon.resource.ore")
        self.assertEqual(value["name_zh"],"改名")

    def test_versions_preserved_and_selection_explicit(self):
        self.version();self.approve();self.version()
        a=self.cat.get("asset","icon.resource.ore")
        self.assertEqual(len(a["versions"]),2)
        self.assertEqual(a["current_approved_version"],1)
        with self.assertRaises(AssetError):self.cat.select(a["asset_id"],2)

    def test_source_is_original_and_distinct_from_component(self):
        v=self.version();s=self.cat.get("source",v["source_id"])
        self.assertEqual(self.cat.path(s["file"]).read_bytes(),image_bytes())
        self.assertTrue(v["files"][0]["file"].startswith("components/"))
        self.assertEqual(self.cat.publish()["assets"],{})

    def test_upload_display_name_is_metadata_not_destination(self):
        name = "丹鼎阁【旺火】 04:12\u202fPM.png"
        first = self.cat.upload(name, image_bytes(), "building_interior_scene_v1")
        second = self.cat.upload(name, image_bytes(), "building_interior_scene_v1")
        self.assertEqual(first["original_name"], name)
        self.assertEqual(first["file"], "source/files/" + first["source_id"] + ".png")
        self.assertNotEqual(first["file"], second["file"])
        self.assertEqual(self.cat.source_image(first).size, (8, 8))
        self.assertEqual(self.cat.get("source", first["source_id"])["original_name"], name)

    def test_upload_duplicate_filename_does_not_overwrite(self):
        a,b=self.upload(),self.upload()
        self.assertNotEqual(a["file"],b["file"])
        self.assertTrue(self.cat.path(a["file"]).is_file())

    def test_path_escape_absolute_traversal_and_symlink(self):
        for p in ["../bad","/tmp/bad"]:
            with self.assertRaises(AssetError):self.cat.path(p)
        (self.root/"escape").symlink_to("/tmp",target_is_directory=True)
        with self.assertRaises(AssetError):self.cat.path("escape/bad")
        with self.assertRaises(AssetError):Catalog(Path("/tmp/outside-assets"))

    def test_unknown_template_source_rejected(self):
        with self.assertRaises(AssetError):self.upload("unknown")
        self.assertEqual(self.cat.list("source"),[])

    def test_prompt_history_append_and_source_association(self):
        p=self.cat.prompt(TEMPLATE,{"object":"矿石"},asset_id="icon.resource.ore")
        edited=self.cat.prompt(TEMPLATE,p["options"],asset_id="icon.resource.ore",edited_text="当前编辑")
        s=self.upload(prompt_id=p["prompt_id"])
        self.assertNotEqual(p["prompt_id"],edited["prompt_id"])
        self.assertEqual(self.cat.get("source",s["source_id"])["prompt_id"],p["prompt_id"])
        self.assertEqual(self.cat.get("prompt",p["prompt_id"])["text"],p["text"])

    def test_source_prompt_template_mismatch(self):
        p=self.cat.prompt("pill_icon_v1",{})
        with self.assertRaises(AssetError):self.upload(prompt_id=p["prompt_id"])

    def test_grid_sprite_import_action_order(self):
        s=self.upload("character_compact_v1",size=(16,16),spec_options={"counts":{"idle":2,"hit":2}})
        p=self.cat.plan(s["source_id"],{"idle":2,"hit":2},"grid",dict(rows=2,columns=2,frame_width=8,frame_height=8))
        self.cat.create_asset("character.test","角色","character_compact_v1")
        v=self.cat.import_version("character.test",p,True)
        self.assertEqual([(f["action"],f["frame"]) for f in v["files"]],[("idle",1),("idle",2),("hit",1),("hit",2)])

    def test_scene_sheet_grid_custom_mapping(self):
        s=self.upload("building_interior_scene_v1",size=(24,16))
        states=["prepare","measure","add_herbs","stable","high_fire","finish"]
        cells=grid(24,16,dict(rows=2,columns=3,frame_width=8,frame_height=8))
        values=[dict(action=a,frame=1,rect=r) for a,r in zip(states,cells)]
        p=self.cat.plan(s["source_id"],{a:1 for a in states},"grid",dict(rows=2,columns=3,frame_width=8,frame_height=8),values)
        self.assertEqual(len(p["regions"]),6)

    def test_manual_sprite_mapping_and_crop_pixels(self):
        s=self.upload("character_compact_v1",size=(16,8))
        p=self.cat.plan(s["source_id"],{"idle":2},"manual",regions=[dict(action="idle",frame=1,rect=[0,0,8,8]),dict(action="idle",frame=2,rect=[8,0,8,8])])
        self.cat.create_asset("character.test","角色","character_compact_v1")
        v=self.cat.import_version("character.test",p,True)
        self.assertEqual(v["files"][0]["width"],8)

    def test_import_needs_confirm_and_stale_source_rejected(self):
        s=self.upload();p=self.cat.plan(s["source_id"],{"icon":1},"independent")
        with self.assertRaises(AssetError):self.cat.import_version("icon.resource.ore",p)
        p["source_sha256"]="changed"
        with self.assertRaises(AssetError):self.cat.import_version("icon.resource.ore",p,True)
        self.assertFalse(self.cat.get("asset","icon.resource.ore")["versions"])

    def test_independent_interior_import_with_master(self):
        group="scene_set.danding.interior.v1";prefix="scene.danding.interior"
        self.version(prefix+".master","building_interior_scene_v1",master=True,set_id=group);self.approve(prefix+".master")
        self.version(prefix+".stable","building_interior_scene_v1","stable",set_id=group);self.approve(prefix+".stable")
        c=self.cat.completeness(group)
        self.assertEqual((c["complete"],c["approved"]),(1,1))
        self.assertEqual(self.cat.get("asset",prefix+".stable")["versions"][0]["master_version"],1)
        with self.assertRaises(AssetError):self.cat.build(prefix+".master",1,8,8)

    def test_interior_approval_requires_master(self):
        asset="scene.danding.interior.stable"
        self.version(asset,"building_interior_scene_v1","stable")
        self.cat.review(asset,1,"needs_review")
        with self.assertRaises(AssetError):self.cat.review(asset,1,"approved",{k:True for k in REVIEW+INTERIOR_REVIEW})

    def test_manual_checklist_and_transitions(self):
        self.version()
        with self.assertRaises(AssetError):self.cat.review("icon.resource.ore",1,"approved",{k:True for k in REVIEW})
        self.cat.review("icon.resource.ore",1,"needs_review")
        with self.assertRaises(AssetError):self.cat.review("icon.resource.ore",1,"approved",{"style":True})
        self.assertEqual(self.cat.get("asset","icon.resource.ore")["versions"][0]["art_status"],"needs_review")

    def test_build_requires_approval(self):
        self.version()
        with self.assertRaises(AssetError):self.cat.build("icon.resource.ore",1)

    def test_manifest_gates_draft_review_missing_build(self):
        self.version();self.assertEqual(self.cat.publish()["assets"],{})
        self.cat.review("icon.resource.ore",1,"needs_review");self.assertEqual(self.cat.publish()["assets"],{})
        self.cat.review("icon.resource.ore",1,"approved",{k:True for k in REVIEW});self.cat.select("icon.resource.ore",1)
        self.assertEqual(self.cat.publish()["assets"],{})

    def test_runtime_output_and_offline_manifest(self):
        m=self.built();item=m["assets"]["icon.resource.ore"]
        self.assertTrue(item["files"][0]["file"].startswith("runtime/"))
        # No service/catalog connection necessary to resolve the published file.
        loaded=json.loads((self.root/"manifest.json").read_text())
        with Image.open(self.root/loaded["assets"]["icon.resource.ore"]["files"][0]["file"]) as image:self.assertEqual(image.size,(48,48))

    def test_manifest_missing_file_excluded(self):
        m=self.built();self.cat.path(m["assets"]["icon.resource.ore"]["files"][0]["file"]).unlink()
        self.assertEqual(self.cat.publish()["assets"],{})

    def test_deprecate_removes_published_version_even_after_selection_changes(self):
        self.built();self.version();self.approve(version=2)
        self.cat.review("icon.resource.ore",1,"deprecated")
        self.assertEqual(json.loads(self.cat.path("manifest.json").read_text())["assets"],{})
        self.assertEqual(self.cat.get("asset","icon.resource.ore")["current_approved_version"],2)

    def test_logical_asset_deprecation_retains_files_and_unpublishes(self):
        manifest=self.built();file=manifest["assets"]["icon.resource.ore"]["files"][0]["file"]
        asset=self.cat.deprecate_asset("icon.resource.ore")
        self.assertIsNone(asset["current_approved_version"])
        self.assertTrue(all(v["art_status"] == "deprecated" for v in asset["versions"]))
        self.assertTrue(self.cat.path(file).is_file())
        self.assertEqual(self.cat.publish()["assets"],{})

    def test_approved_files_not_deleted(self):
        self.built();v=self.cat.get("asset","icon.resource.ore")["versions"][0]
        with self.assertRaises(AssetError):self.cat.delete_source(v["source_id"])
        with self.assertRaises(AssetError):self.cat.delete_build("icon.resource.ore",1)

    def test_unused_source_delete_and_deprecated_build_delete(self):
        s=self.upload();self.cat.delete_source(s["source_id"])
        self.assertFalse(self.cat.path(s["file"]).exists())
        self.built();self.cat.review("icon.resource.ore",1,"deprecated");self.cat.delete_build("icon.resource.ore",1)
        self.assertIsNone(self.cat.get("asset","icon.resource.ore")["versions"][0]["runtime"])

    def test_build_failure_metadata_and_manifest_unchanged(self):
        self.version();self.approve();before=self.cat.export_registry();manifest=self.cat.path("manifest.json").read_bytes()
        with patch.object(self.cat,"atomic",side_effect=OSError("injected")),self.assertRaises(OSError):self.cat.build("icon.resource.ore",1)
        self.assertEqual(before,self.cat.export_registry());self.assertEqual(manifest,self.cat.path("manifest.json").read_bytes())

    def test_import_failure_metadata_rollback(self):
        s=self.upload();p=self.cat.plan(s["source_id"],{"icon":1},"independent")
        with patch.object(self.cat,"put",side_effect=OSError("injected")),self.assertRaises(OSError):self.cat.import_version("icon.resource.ore",p,True)
        self.assertEqual(self.cat.get("asset","icon.resource.ore")["versions"],[])

    def test_publish_failure_keeps_previous_manifest(self):
        self.built();before=self.cat.path("manifest.json").read_bytes()
        with patch.object(self.cat,"atomic",side_effect=OSError("injected")),self.assertRaises(OSError):self.cat.publish()
        self.assertEqual(before,self.cat.path("manifest.json").read_bytes())

    def test_search_and_filters(self):
        self.version()
        self.assertEqual(len(self.cat.search("矿石")),1)
        self.assertEqual(len(self.cat.search(tag="ore",version=1,template_id=TEMPLATE,art_status="draft")),1)
        self.assertEqual(len(self.cat.search(tag="missing")),0)

    def test_registry_round_trip_query_purity(self):
        self.version();self.approve();before=self.cat.export_registry()
        other=Catalog(self.root);self.assertEqual(before,other.export_registry())
        self.cat.search("ore");self.cat.completeness("scene_set.danding.interior.v1")
        self.assertEqual(before,self.cat.export_registry())

    def test_source_component_corruption_detected(self):
        self.version();self.approve()
        v=self.cat.get("asset","icon.resource.ore")["versions"][0]
        path=self.cat.path(v["files"][0]["file"]);path.write_bytes(b"bad")
        with self.assertRaises(AssetError):self.cat.build("icon.resource.ore",1)

    def test_full_danding_set_independent_import_review_and_runtime(self):
        group="scene_set.danding.interior.v1";prefix="scene.danding.interior";template="building_interior_scene_v1"
        self.version(prefix+".master",template,master=True,set_id=group);self.approve(prefix+".master")
        for action in self.cat.get("set",group)["states"]:
            self.version(prefix+"."+action,template,action,set_id=group)
            self.approve(prefix+"."+action)
            self.cat.build(prefix+"."+action,1,format_name="webp")
        c=self.cat.completeness(group)
        self.assertEqual((c["complete"],c["approved"],c["runtime"]),(6,6,6))
        manifest=self.cat.publish();self.assertEqual(len(manifest["assets"]),6)
        self.assertNotIn(prefix+".master",manifest["assets"])
        fresh=Catalog(self.root);self.assertEqual(fresh.completeness(group)["runtime"],6)

    def test_prompt_records_current_rule_fingerprints(self):
        p=self.cat.prompt(TEMPLATE,{})
        self.assertEqual(len(p["rule_fingerprints"]),6)
        self.assertIn("docs/standards/visual-north-star.md",p["rule_fingerprints"])
        self.assertIn("Project rules in priority order",p["text"])

    def test_duplicate_across_catalog_connections(self):
        from concurrent.futures import ThreadPoolExecutor
        other=Catalog(self.root)
        def create(c):
            try:c.create_asset("icon.resource.concurrent","矿石",TEMPLATE);return True
            except AssetError:return False
        with ThreadPoolExecutor(max_workers=2) as executor:
            values=list(executor.map(create,[self.cat,other]))
        self.assertEqual(sorted(values),[False,True])

    def test_source_checksum_revalidated_on_confirm(self):
        s=self.upload();p=self.cat.plan(s["source_id"],{"icon":1},"independent")
        self.cat.path(s["file"]).write_bytes(image_bytes((4,4)))
        with self.assertRaises(AssetError):self.cat.import_version("icon.resource.ore",p,True)

    def test_manual_master_crop(self):
        s=self.upload("building_interior_scene_v1")
        p=self.cat.master_plan(s["source_id"],[0,0,4,4])
        v=self.cat.import_version("scene.danding.interior.master",p,True,True)
        self.assertEqual((v["files"][0]["width"],v["files"][0]["height"]),(4,4))

    def test_approve_missing_component_rejected(self):
        self.version();self.cat.review("icon.resource.ore",1,"needs_review")
        v=self.cat.get("asset","icon.resource.ore")["versions"][0]
        self.cat.path(v["files"][0]["file"]).unlink()
        with self.assertRaises(AssetError):self.cat.review("icon.resource.ore",1,"approved",{k:True for k in REVIEW})

    def test_immutable_write_does_not_replace_existing_source(self):
        s=self.upload();before=self.cat.path(s["file"]).read_bytes()
        with self.assertRaises(AssetError):self.cat.atomic(s["file"],b"replace")
        self.assertEqual(before,self.cat.path(s["file"]).read_bytes())

    def test_manifest_tampered_runtime_excluded(self):
        m=self.built();f=m["assets"]["icon.resource.ore"]["files"][0]
        self.cat.path(f["file"]).write_bytes(b"bad")
        self.assertEqual(self.cat.publish()["assets"],{})

    def test_frame_replacement_new_version_retains_old_approved_files(self):
        source=self.upload("character_compact_v1",size=(16,8),spec_options={"counts":{"idle":2}})
        self.cat.create_asset("character.test","角色","character_compact_v1")
        plan=self.cat.plan(source["source_id"],{"idle":2},"grid",dict(rows=1,columns=2,frame_width=8,frame_height=8))
        old=self.cat.import_version("character.test",plan,True)
        self.approve("character.test")
        replacement=self.upload("character_compact_v1")
        new=self.cat.replace_frame("character.test",1,0,replacement["source_id"],[0,0,8,8],True)
        self.assertEqual(new["version"],2);self.assertEqual(new["art_status"],"draft")
        self.assertEqual(new["files"][1],old["files"][1])
        self.assertNotEqual(new["files"][0]["file"],old["files"][0]["file"])
        self.assertEqual(self.cat.get("asset","character.test")["current_approved_version"],1)
        with self.assertRaises(AssetError):self.cat.replace_frame("character.test",1,0,replacement["source_id"],[0,0,4,4],True)
        self.assertEqual(len(self.cat.get("asset","character.test")["versions"]),2)

class WebTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=PROJECT/"tests");self.addCleanup(self.temp.cleanup)
        self.token="test-only-asset-access-token-32chars"
        self.app=create_app(Path(self.temp.name)/"assets",self.token)
        self.client=self.app.test_client();self.cat=self.app.extensions["asset_catalog"]

    def login(self):
        self.assertEqual(self.client.post("/login",data={"token":self.token}).status_code,302)
        return self.client.get("/api/state").get_json()["csrf"]

    def test_no_anonymous_read_or_write(self):
        self.assertEqual(self.client.get("/api/state").status_code,401)
        self.assertEqual(self.client.post("/api/publish",json={}).status_code,401)
        self.assertEqual(self.client.get("/file/source/unknown/0/0").status_code,401)

    def test_token_required_at_start(self):
        with self.assertRaises(AssetError):create_app(Path(self.temp.name)/"other","")

    def test_login_and_csrf_required(self):
        csrf=self.login();self.assertEqual(self.client.post("/api/publish",json={}).status_code,403)
        self.assertEqual(self.client.post("/api/publish",json={},headers={"X-CSRF-Token":csrf}).status_code,200)

    def test_cross_origin_rejected(self):
        csrf=self.login()
        self.assertEqual(self.client.post("/api/publish",json={},headers={"X-CSRF-Token":csrf,"Origin":"https://evil.example"}).status_code,403)
        self.assertEqual(self.client.post("/login",data={"token":self.token},headers={"Origin":"https://evil.example"}).status_code,403)

    def test_bearer_and_security_headers(self):
        r=self.client.get("/api/state",headers={"Authorization":"Bearer "+self.token})
        self.assertEqual(r.status_code,200);self.assertIn("frame-ancestors 'none'",r.headers["Content-Security-Policy"])
        self.assertEqual(r.headers["X-Content-Type-Options"],"nosniff")

    def test_untrusted_host_rejected(self):
        self.assertEqual(self.client.get("/",headers={"Host":"evil.example"}).status_code,400)

    def test_mobile_markup_and_css(self):
        self.login();r=self.client.get("/")
        self.assertIn(b"viewport-fit=cover",r.data)
        self.assertIn(b'type="module"',r.data)
        with self.client.get("/static/style.css") as response:
            css=response.data
        for rule in [b"safe-area",b"min-height:44px",b"image-rendering:pixelated",b":focus-visible"]:self.assertIn(rule,css)

    def test_upload_prompt_and_independent_import_via_http(self):
        csrf=self.login();headers={"X-CSRF-Token":csrf}
        a="icon.resource.test"
        self.assertEqual(self.client.post("/api/assets",json=dict(asset_id=a,name_zh="矿石",template_id=TEMPLATE,state="icon"),headers=headers).status_code,200)
        p=self.client.post("/api/prompts",json=dict(template_id=TEMPLATE,options={"object":"矿石"},asset_id=a),headers=headers).get_json()
        s=self.client.post("/api/source",data=dict(file=(io.BytesIO(image_bytes()),"a.png"),template_id=TEMPLATE,prompt_id=p["prompt_id"]),headers=headers).get_json()
        plan=self.client.post("/api/plan",json=dict(source_id=s["source_id"],counts={"icon":1},mode="independent"),headers=headers).get_json()
        r=self.client.post("/api/import",json=dict(asset_id=a,plan=plan,confirmed=True),headers=headers)
        self.assertEqual(r.status_code,200)
        with self.client.get(f"/file/component/{a}/1/0") as response:
            self.assertEqual(response.status_code,200)

    def test_browser_upload_unicode_display_filename(self):
        csrf = self.login()
        name = "丹鼎阁【旺火】 04:12\u202fPM.png"
        response = self.client.post("/api/source", data={
            "file": (io.BytesIO(image_bytes()), name),
            "template_id": "building_interior_scene_v1",
        }, headers={"X-CSRF-Token": csrf})
        self.assertEqual(response.status_code, 200, response.get_json())
        source = response.get_json()
        self.assertEqual(source["original_name"], name)
        with self.client.get(f"/file/source/{source['source_id']}/0/0") as preview:
            self.assertEqual(preview.status_code, 200)
            self.assertEqual(Image.open(io.BytesIO(preview.data)).size, (8, 8))

    def test_http_invalid_fields_and_file_role(self):
        csrf=self.login();h={"X-CSRF-Token":csrf}
        self.assertEqual(self.client.post("/api/assets",json={},headers=h).status_code,400)
        self.assertEqual(self.client.get("/file/unsafe/x/1/0").status_code,400)

    def test_read_does_not_mutate_registry(self):
        self.login();before=self.cat.export_registry();self.client.get("/api/state");self.client.get("/api/search?q=danding");self.client.get("/")
        self.assertEqual(before,self.cat.export_registry())

    def test_proxy_prefix_login_and_static_links(self):
        from werkzeug.middleware.dispatcher import DispatcherMiddleware
        from werkzeug.middleware.proxy_fix import ProxyFix
        from werkzeug.wrappers import Response
        from werkzeug.test import Client
        mounted=ProxyFix(DispatcherMiddleware(Response("Not found",status=404),{"/tools/assets":self.app}),x_proto=1)
        client=Client(mounted,Response)
        response=client.post("/tools/assets/login",data={"token":self.token},headers={"X-Forwarded-Proto":"https","Host":"localhost:8443","Origin":"https://localhost:8443"})
        self.assertEqual(response.status_code,302)
        self.assertEqual(response.headers["Location"],"/tools/assets/")
        response=client.get("/tools/assets/")
        self.assertIn(b'/tools/assets/static/app.js',response.data)
        self.assertIn(b'content="/tools/assets"',response.data)
        self.assertEqual(client.get("/tools/assets/api/state").status_code,200)
        with client.get("/tools/assets/static/app.js") as response:
            self.assertEqual(response.status_code,200)
        self.assertEqual(client.get("/api/state").status_code,404)

    def test_browser_paths_include_configured_prefix(self):
        script=(PROJECT/"tools/asset_manager/static/app.js").read_text()
        self.assertNotIn('src="/file/',script)
        self.assertNotIn('href="/api/',script)
        self.assertIn("fetch(BASE+'/api/'",script)

    def test_no_gameplay_dependencies_or_api_paths(self):
        for p in (PROJECT/"tools/asset_manager").glob("*.py"):
            self.assertNotIn("from src.",p.read_text());self.assertNotIn("import src.",p.read_text())
        routes={r.rule for r in self.app.url_map.iter_rules()}
        self.assertFalse(any("inventory" in r or "settlement" in r or "alchemy" in r for r in routes))

if __name__ == "__main__":unittest.main()

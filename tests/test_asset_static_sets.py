"""Independent static assets, frozen cell identity and unchanged animation contracts."""
import copy,io,json,tempfile,unittest
from unittest.mock import patch
from pathlib import Path
from PIL import Image
from tools.asset_manager.catalog import Catalog,PROJECT
from tools.asset_manager.model import AssetError,REVIEW,identifier
from tools.asset_manager.sets import creation_spec,suggested_id,grid_shape,static_regions
from tools.asset_manager.web import create_app

ORES=["玄铁矿","赤铜矿","寒铁矿","灵晶矿","赤炎矿","星陨矿"]
class StaticSetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=PROJECT/"tests");self.addCleanup(self.temp.cleanup)
        self.catalog=Catalog(Path(self.temp.name)/"assets")
    def group(self,mode="sheet",items=None):return self.catalog.create_named("resource_icon_v1","宗门矿石","set",items or ORES,mode)
    def prompt(self,group):return self.catalog.prompt(group["template_id"],{"object":group["name_zh"],"family":group["family"]},set_id=group["set_id"])
    def sheet(self,prompt):
        spec=prompt["frozen_spec"];g=spec["grid_spec"];width=g["columns"]*g["frame_width"]+(g["columns"]-1)*g["horizontal_gap"];height=g["rows"]*g["frame_height"]+(g["rows"]-1)*g["vertical_gap"]
        output=io.BytesIO();Image.new("RGBA",(width,height),(0,0,0,0)).save(output,format="PNG")
        return self.catalog.upload("test.png",output.getvalue(),prompt["template_id"],prompt["set_id"],prompt["prompt_id"])
    def test_six_assets_not_six_frames(self):
        g=self.group();self.assertEqual(len(g["asset_ids"]),6)
        for aid in g["asset_ids"]:
            a=self.catalog.get("asset",aid);self.assertEqual(a["frame_count"],1);self.assertEqual(a["state"],"icon")
        self.assertEqual(self.catalog.completeness(g["set_id"])["total"],6)
    def test_count_derives_from_list(self):
        for n in (1,4,6):self.assertEqual(len(self.group(items=ORES[:n])["asset_ids"]),n)
    def test_names_reject_empty_duplicates_and_overlarge(self):
        for items in ([],[""],["甲","甲"],[str(i) for i in range(129)]):
            with self.assertRaises(AssetError):self.catalog.create_named("resource_icon_v1","组","set",items,"sheet")
    def test_ascii_ids_are_deterministic_without_translation(self):
        p=self.catalog.creation_preview("resource_icon_v1","玄铁矿");q=self.catalog.creation_preview("resource_icon_v1","玄铁矿")
        self.assertEqual(p["machine_id"],q["machine_id"]);self.assertTrue(p["machine_id"].isascii());identifier(p["machine_id"])
    def test_collision_is_resolved_and_manual_collision_rejected(self):
        a=self.catalog.create_named("pill_icon_v1","回春丹");b=self.catalog.create_named("pill_icon_v1","回春丹")
        self.assertNotEqual(a["asset_id"],b["asset_id"])
        with self.assertRaises(AssetError):self.catalog.create_named("pill_icon_v1","另一名",machine_id=a["asset_id"])
    def test_non_ascii_manual_id_rejected(self):
        with self.assertRaises(AssetError):self.catalog.create_named("resource_icon_v1","矿石",machine_id="玄铁矿")
    def test_advanced_ids_match_each_independent_asset(self):
        g=self.catalog.create_named("resource_icon_v1","矿石","set",ORES[:2],"sheet",asset_ids=["icon.resource.first","icon.resource.second"])
        self.assertEqual(g["asset_ids"],["icon.resource.first","icon.resource.second"])
    def test_template_supplies_family_namespace_role(self):
        p=self.catalog.creation_preview("resource_icon_v1","矿石")
        self.assertEqual(p["family"],"default");self.assertEqual(p["runtime_role"],"item_icon");self.assertTrue(p["machine_id"].startswith("icon.resource."))
    def test_creation_preview_queries_ids_without_loading_histories(self):
        self.group()
        with patch.object(self.catalog,'list',side_effect=AssertionError('Full history loaded')):
            preview=self.catalog.creation_preview('resource_icon_v1','宗门矿石','set',ORES,'sheet')
            created=self.group()
            self.assertEqual(preview['machine_id'],created['set_id'])
            self.assertEqual([i['asset_id'] for i in preview['asset_list']],created['asset_ids'])
    def test_grid_shapes(self):
        for count,shape in [(4,(2,2)),(6,(2,3)),(8,(2,4)),(9,(3,3))]:self.assertEqual(grid_shape(count),shape)
        self.assertEqual(grid_shape(14),(3,5))
        self.assertEqual(grid_shape(25),(5,5))
        for count in range(1,26):
            rows,columns=grid_shape(count)
            self.assertLessEqual(rows,5);self.assertLessEqual(columns,5)
            self.assertGreaterEqual(rows*columns,count)
        with self.assertRaisesRegex(AssetError,'25个素材'):grid_shape(26)
    def test_fourteen_asset_sheet_freezes_three_by_five(self):
        items=['图标'+str(i) for i in range(14)]
        preview=self.catalog.creation_preview('resource_icon_v1','十四图标','set',items,'sheet')
        self.assertEqual((preview['grid_rows'],preview['grid_columns']),(3,5))
        p=self.prompt(self.group(items=items));s=p['frozen_spec']
        self.assertEqual((s['grid_rows'],s['grid_columns']),(3,5))
        self.assertEqual(len(s['cell_mapping']),14)
        self.assertEqual((s['cell_mapping'][-1]['row'],s['cell_mapping'][-1]['column']),(2,3))
        self.assertIn('3 rows x 5 columns',p['text'])
        self.assertEqual(self.sheet(p)['frozen_spec'],s)
    def test_oversized_sheet_rejected_but_independent_images_allowed(self):
        items=['图标'+str(i) for i in range(26)]
        with self.assertRaisesRegex(AssetError,'25个素材'):self.group(items=items)
        self.assertEqual(len(self.group(mode='independent',items=items)['asset_ids']),26)
    def test_snapshot_freezes_order_grid_and_mapping(self):
        g=self.group();p=self.prompt(g);s=p["frozen_spec"]
        self.assertEqual(s["asset_count"],6);self.assertEqual(s["frame_counts"],{"icon":1});self.assertEqual(s["asset_order"],g["asset_ids"]);self.assertEqual((s["grid_rows"],s["grid_columns"]),(2,3));self.assertEqual([(c["row"],c["column"]) for c in s["cell_mapping"]],[(0,0),(0,1),(0,2),(1,0),(1,1),(1,2)])
    def test_prompt_says_assets_not_animation(self):
        p=self.prompt(self.group());self.assertIn("6 different independent game assets",p["text"]);self.assertIn("2 rows x 3 columns",p["text"]);self.assertIn("NOT animation frames",p["text"])
        for name in ORES:self.assertIn(name,p["text"])
    def test_submitted_counts_do_not_create_six_frames(self):
        g=self.group()
        with self.assertRaises(AssetError):self.catalog.prompt(g["template_id"],{"counts":{"icon":6}},set_id=g["set_id"])
    def test_list_order_is_preserved(self):
        g=self.group(items=list(reversed(ORES)));s=self.prompt(g)["frozen_spec"]
        self.assertEqual([a["name_zh"] for a in s["asset_list"]],list(reversed(ORES)))
    def test_source_has_same_snapshot(self):
        p=self.prompt(self.group());source=self.sheet(p);self.assertEqual(source["frozen_spec"],p["frozen_spec"])
    def test_grid_import_maps_six_independent_versions(self):
        g=self.group();p=self.prompt(g);source=self.sheet(p);plan=self.catalog.plan(source["source_id"]);result=self.catalog.import_static_set(plan,True)
        self.assertEqual(len(result),6)
        for a in result:self.assertEqual(len(a["version"]["files"]),1)
        self.assertEqual(self.catalog.completeness(g["set_id"])["complete"],6)
    def test_blank_cell_unassigned(self):
        p=self.prompt(self.group(items=ORES[:5]));source=self.sheet(p);plan=self.catalog.plan(source["source_id"])
        self.assertEqual(len(plan["regions"]),5);self.assertEqual(len(p["frozen_spec"]["cell_mapping"]),5)
    def test_wrong_asset_mapping_rejected(self):
        p=self.prompt(self.group());source=self.sheet(p);plan=self.catalog.plan(source["source_id"]);bad=copy.deepcopy(plan);bad["regions"][0]["asset_id"]="icon.unknown"
        with self.assertRaises(AssetError):self.catalog.import_static_set(bad,True)
    def test_duplicate_mapping_rejected(self):
        p=self.prompt(self.group());source=self.sheet(p);plan=self.catalog.plan(source["source_id"]);bad=copy.deepcopy(plan);bad["regions"][1]["asset_id"]=bad["regions"][0]["asset_id"]
        with self.assertRaises(AssetError):self.catalog.import_static_set(bad,True)
    def test_batch_metadata_rolls_back_on_failure(self):
        g=self.group();source=self.sheet(self.prompt(g));plan=self.catalog.plan(source["source_id"]);original=self.catalog._import_version;calls=0
        def fail(*args):
            nonlocal calls
            calls+=1
            if calls==2:raise OSError("disk failure")
            return original(*args)
        with patch.object(self.catalog,"_import_version",side_effect=fail):
            with self.assertRaises(OSError):self.catalog.import_static_set(plan,True)
        for aid in g["asset_ids"]:self.assertEqual(self.catalog.get("asset",aid)["versions"],[])
    def test_manual_correction_maps_by_ids_without_vision(self):
        p=self.prompt(self.group(items=ORES[:2]));source=self.sheet(p);regions=static_regions(p["frozen_spec"]);plan=self.catalog.plan(source["source_id"],mode="manual",regions=regions)
        self.assertEqual([r["asset_id"] for r in plan["regions"]],p["frozen_spec"]["asset_ids"])
    def test_independent_assets_keep_set_identity(self):
        g=self.group("independent");p=self.catalog.prompt(g["template_id"],{},asset_id=g["asset_ids"][0]);self.assertEqual(p["frozen_spec"]["asset_count"],1);self.assertEqual(p["frozen_spec"]["asset_set_id"],g["set_id"])
        source=self.sheet(p);plan=self.catalog.plan(source["source_id"],mode="independent");self.catalog.import_static_set(plan,True)
    def test_approved_rename_keeps_id_and_six_runtime_outputs(self):
        g=self.group();source=self.sheet(self.prompt(g));self.catalog.import_static_set(self.catalog.plan(source["source_id"]),True)
        for aid in g["asset_ids"]:
            self.catalog.review(aid,1,"needs_review");self.catalog.review(aid,1,"approved",dict.fromkeys(REVIEW,True));self.catalog.select(aid,1);self.catalog.build(aid,1)
        renamed=self.catalog.rename(g["asset_ids"][0],"玄铁矿石");self.assertEqual(renamed["asset_id"],g["asset_ids"][0]);manifest=self.catalog.publish();self.assertEqual(set(manifest["assets"]),set(g["asset_ids"]))
        for runtime in manifest["assets"].values():self.assertEqual(len(runtime["files"]),1)
    def test_renaming_does_not_rewrite_frozen_prompt(self):
        g=self.group();p=self.prompt(g);self.catalog.rename(g["asset_ids"][0],"玄铁矿石");self.assertEqual(self.catalog.get("prompt",p["prompt_id"]),p)
    def test_dynamic_profiles_unchanged(self):
        from tools.asset_manager.specs import freeze_spec
        s=freeze_spec(self.catalog.templates["character_compact_v1"],{"counts":dict(idle=2,walk=4,attack=4,cast=4,hit=2,death=4)})
        self.assertEqual(s["frame_counts"],dict(idle=2,walk=4,attack=4,cast=4,hit=2,death=4));self.assertNotIn("asset_list",s)
    def test_scene_set_unchanged(self):
        g=self.catalog.completeness("scene_set.danding.interior.v1");self.assertEqual(g["total"],6);self.assertIn("master",g["slots"])
    def test_restart_preserves_static_set_authority(self):
        g=self.group();other=Catalog(self.catalog.root);self.assertEqual(other.get("set",g["set_id"]),g)
    def test_web_creation_and_prompt_share_authority(self):
        app=create_app(self.catalog.root,"x"*32);client=app.test_client();headers={"Authorization":"Bearer "+"x"*32}
        response=client.post("/api/create-named",json=dict(template_id="resource_icon_v1",name_zh="宗门矿石",generation_scope="set",asset_names=ORES,generation_mode="sheet"),headers=headers)
        self.assertEqual(response.status_code,200);g=response.json
        p=client.post("/api/prompts",json=dict(template_id=g["template_id"],options={},set_id=g["set_id"]),headers=headers)
        self.assertEqual(p.status_code,200);self.assertEqual(p.json["frozen_spec"]["asset_count"],6)

    def test_edit_list_add_delete_reorder_and_stable_rename(self):
        g=self.group(items=ORES[:3]);first=g["asset_ids"][0];last=g["asset_ids"][2]
        updated=self.catalog.edit_static_set(g["set_id"],[dict(asset_id=last,name_zh=ORES[2]),dict(asset_id=first,name_zh="玄铁矿石"),dict(name_zh="星陨矿")])
        self.assertEqual(updated["asset_ids"][:2],[last,first]);self.assertEqual(len(updated["asset_ids"]),3);self.assertEqual(self.catalog.get("asset",first)["name_zh"],"玄铁矿石")
        self.assertIsNone(self.catalog.get("asset",g["asset_ids"][1])["set_id"])
    def test_edit_detaches_without_deleting_frozen_prompt_reference(self):
        g=self.group();p=self.prompt(g)
        self.catalog.edit_static_set(g["set_id"],[dict(asset_id=aid,name_zh=self.catalog.get("asset",aid)["name_zh"]) for aid in g["asset_ids"][1:]])
        self.assertIsNone(self.catalog.get("asset",g["asset_ids"][0])["set_id"])
        self.assertEqual(self.catalog.get("prompt",p["prompt_id"]),p)
    def test_no_prompt_sheet_import_freezes_set_identity(self):
        g=self.group();prompt=self.prompt(g);source=self.sheet(prompt)
        data=self.catalog.path(source["file"]).read_bytes();plain=self.catalog.upload("plain.png",data,g["template_id"],g["set_id"])
        self.assertEqual(plain["frozen_spec"]["asset_ids"],g["asset_ids"]);self.assertEqual(len(self.catalog.plan(plain["source_id"])["regions"]),6)
    def test_reorder_does_not_change_historical_mapping(self):
        g=self.group();old=self.prompt(g)
        items=[dict(asset_id=aid,name_zh=self.catalog.get("asset",aid)["name_zh"]) for aid in reversed(g["asset_ids"])];self.catalog.edit_static_set(g["set_id"],items)
        new=self.prompt(self.catalog.get("set",g["set_id"]));self.assertEqual(new["frozen_spec"]["asset_ids"],list(reversed(g["asset_ids"])));self.assertEqual(self.catalog.get("prompt",old["prompt_id"]),old)

    def test_static_reference_uses_approved_icon_without_interior_master_drift(self):
        g=self.group(items=ORES[:1]);p=self.prompt(g);source=self.sheet(p);self.catalog.import_static_set(self.catalog.plan(source["source_id"]),True);aid=g["asset_ids"][0]
        self.catalog.review(aid,1,"needs_review");self.catalog.review(aid,1,"approved",dict.fromkeys(REVIEW,True));self.catalog.select(aid,1)
        other=self.group(items=ORES[1:3]);ref=self.catalog.prompt(other["template_id"],{"master_reference":aid},set_id=other["set_id"])
        self.assertEqual(ref["master_version"],1)
        with self.assertRaises(AssetError):self.catalog.prompt("building_interior_scene_v1",{"master_reference":aid,"state":"prepare","counts":{"prepare":1}})
    def test_preview_matches_actual_collision_safe_ids(self):
        self.group();preview=self.catalog.creation_preview("resource_icon_v1","宗门矿石","set",ORES,"sheet");created=self.group()
        self.assertEqual(preview["machine_id"],created["set_id"]);self.assertEqual([a["asset_id"] for a in preview["asset_list"]],created["asset_ids"])

    def test_independent_scope_is_single_with_set_reference(self):
        g=self.group("independent");p=self.catalog.prompt(g["template_id"],{},asset_id=g["asset_ids"][0]);s=p["frozen_spec"]
        self.assertEqual(s["generation_scope"],"single_asset");self.assertEqual(s["asset_set_id"],g["set_id"])
    def test_unmapped_independent_group_upload_rejected(self):
        g=self.group("independent");p=self.prompt(g)
        with self.assertRaises(AssetError):self.sheet(p)
    def test_specification_preview_equals_saved_mapping_and_is_pure(self):
        g=self.group();before=self.catalog.list("prompt");spec=self.catalog.specification(g["template_id"],{},set_id=g["set_id"])
        self.assertEqual(self.catalog.list("prompt"),before);p=self.catalog.prompt(g["template_id"],{},set_id=g["set_id"])
        self.assertEqual(spec,p["frozen_spec"])

    def test_named_dynamic_set_uses_namespace_and_resolved_family_actions(self):
        g=self.catalog.create_named("character_compact_v1","宗门工作弟子","set",family="working_disciple")
        self.assertTrue(g["asset_prefix"].startswith("character."));self.assertEqual(g["states"],["idle","work"])
        self.assertEqual(self.catalog.get("asset",g["asset_prefix"]+".work")["name_zh"],"工作")

"""Read approved Runtime through guarded metadata; never change pipeline or gameplay IDs."""
import unittest
from pathlib import Path
from src.rendering.game_runtime import GameRuntimeAssets
from src.rendering.game import _battle,bindings
from src.data.dungeons.definitions import load_dungeons
from src.systems.dungeons import progress
from src.systems.combat import battle

class DungeonRenderingTests(unittest.TestCase):
 def test_all_16_enemy_poses_ground_anchor_and_all_hero_actions(self):
  assets=GameRuntimeAssets(Path(__file__).resolve().parents[1]/'assets');snapshot=assets.snapshot();registry=load_dungeons();seen=set()
  for eid in progress.definition(registry).encounters:
   encounter=battle.encounter(registry,eid);enemy=battle.monster(registry,encounter.monster_id)
   if enemy.asset_id in seen:continue
   seen.add(enemy.asset_id)
   combat={'player':{'asset_id':'player.combat.hero'},'enemy':{'asset_id':enemy.asset_id},'encounter':{'background_asset_id':encounter.background_asset_id}}
   result=_battle(assets,snapshot,combat,bindings());self.assertIsNotNone(result['background']);self.assertFalse(result['player']['fallback']);self.assertFalse(result['enemy']['fallback'])
   hero=result['sprites'][result['player']['asset_id']];self.assertEqual(hero['actions']['attack']['frameCount'],4);self.assertEqual(hero['actions']['death']['frameCount'],4);self.assertTrue({'idle','attack','cast','hit','death'}<=hero['actions'].keys())
   monster=result['sprites'][result['enemy']['asset_id']];self.assertTrue(monster['static']);self.assertEqual(set(monster['actions']),{'idle','attack','hit','death'});self.assertGreater(monster['anchor']['y'],0)
   self.assertEqual(len(result['effects']),8)
   for row in result['effects'].values():
    effect=result['sprites'][row['asset_id']];self.assertEqual(effect['anchor'],{'x':64,'y':64});self.assertTrue(all(not a['loop'] for a in effect['actions'].values()))
  self.assertEqual(len(seen),16)
 def test_missing_runtime_remains_honest_fallback(self):
  import tempfile
  with tempfile.TemporaryDirectory() as path:
   assets=GameRuntimeAssets(path);c={'player':{'asset_id':'player.combat.hero'},'enemy':{'asset_id':'monster.dungeon.thorn_rat'},'encounter':{'background_asset_id':'scene.combat.thorn_path'}}
   result=_battle(assets,{},c,bindings());self.assertTrue(result['enemy']['fallback']);self.assertEqual(result['sprites'],{});self.assertEqual(result['effects'],{})

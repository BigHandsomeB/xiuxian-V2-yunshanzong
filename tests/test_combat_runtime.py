"""Game-side compatibility for published high-frame action metadata and stable bindings."""
import hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from src.rendering.game_runtime import GameRuntimeAssets
from src.rendering import game
from src.data.combat.definitions import load_combat
from src.application.game import GameApplication
from src.application.danding import initial_slice
from src.core.state.envelope import thaw_json
from src.systems.combat import battle

class CombatRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);(self.root/'runtime').mkdir();self.assets=GameRuntimeAssets(self.root);self.files=[]
    def tearDown(self):self.temp.cleanup()
    def publish(self,actions,animation=None):
        files=[]
        for name,count in actions.items():
            for i in range(1,count+1):
                relative=f'runtime/{name}-{i}.png';p=self.root/relative;p.write_bytes(relative.encode());files.append({'file':relative,'width':128,'height':128,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'action':name,'frame':i})
        row={'version':1,'anchor':{'type':'bottom_center','baseline_from_bottom':24},'files':files}
        if animation is not None:row['animation']=animation
        (self.root/'manifest.json').write_text(json.dumps({'schema_version':1,'assets':{'character.formal_player':row}}));return row
    def test_player_all_high_frame_actions_supported_and_role_timing(self):
        self.publish({'idle':4,'run':6,'attack_combo':10,'heavy_attack':6,'skill':8,'ultimate':12,'dodge':4,'hit':3,'death':6})
        s=self.assets.sprite('character.formal_player',role='player');self.assertEqual(s['actions']['attack_combo']['frameCount'],10);self.assertEqual(s['actions']['attack_combo']['duration'],85);self.assertEqual(s['actions']['idle']['duration'],240);self.assertEqual(s['actions']['run']['duration'],130)
    def test_runtime_metadata_duration_loop_triggers_override_defaults(self):
        self.publish({'attack':8},{'attack':{'duration_ms':[60,70,80,90,90,80,70,60],'loop':False,'triggers':[{'frame':3,'effect':'slash','x':4,'y':0}]}})
        a=self.assets.sprite('character.formal_player',role='player')['actions']['attack'];self.assertEqual(a['duration'],[60,70,80,90,90,80,70,60]);self.assertEqual(a['triggers'][0]['frame'],3);self.assertFalse(a['loop'])
    def test_monster_compact_count_and_slow_default_preserved(self):
        self.publish({'idle':2,'attack':3,'hit':1,'death':3});s=self.assets.sprite('character.formal_player',role='enemy');self.assertEqual(sum(a['frameCount'] for a in s['actions'].values()),9);self.assertEqual(s['actions']['idle']['duration'],700);self.assertEqual(s['actions']['attack']['duration'],220)
    def test_bad_timing_metadata_falls_back(self):
        for metadata in [{'attack':{'duration_ms':0}},{'attack':{'duration_ms':[80]}},{'attack':{'loop':'yes'}},{'attack':{'triggers':[{'frame':9,'effect':'slash'}]}}]:
            self.publish({'attack':8},metadata);self.assertIsNone(self.assets.sprite('character.formal_player',role='player'))
    def test_formal_sprite_binding_replaces_fallback_without_combat_change(self):
        self.publish({'idle':4,'attack':8,'hit':3,'death':6});r=load_combat();state=initial_slice(r,last_settled_at_ms=1000)
        # Existing Application projection can consume this before an Encounter starts.
        view={'holdings':{},'buildings':{},'combat':{'player':{'asset_id':'player.combat.hero'},'enemy':{'asset_id':'monster.combat.thorn_rat'},'encounter':{'background_asset_id':'scene.battle.thorn'}}}
        before=thaw_json(battle.player(r,state.save_id));self.assertTrue(game.present(view,self.assets)['battle']['assets']['player']['fallback'])
        config={**game.BINDINGS,'combat_bindings':{**game.BINDINGS['combat_bindings'],'player.combat.hero':'character.formal_player'}}
        with patch.object(game,'bindings',return_value=config):
            p=game.present(view,self.assets)['battle']['assets'];self.assertEqual(p['player']['asset_id'],'character.formal_player');self.assertFalse(p['player']['fallback']);self.assertEqual(p['sprites']['character.formal_player']['actions']['attack']['frameCount'],8)
        self.assertEqual(thaw_json(battle.player(r,state.save_id)),before)

    def test_binding_update_reloads_without_service_restart(self):
        path=self.root/'game-bindings.json';config={**game.BINDINGS,'combat_bindings':dict(game.BINDINGS['combat_bindings'])};path.write_text(json.dumps(config))
        with patch.object(game,'BINDING_PATH',path):
            self.assertEqual(game.manifest(self.assets)['combat_bindings']['player.combat.hero']['asset_id'],config['combat_bindings']['player.combat.hero']);config['combat_bindings']['player.combat.hero']='character.formal_player';path.write_text(json.dumps(config));self.assertEqual(game.manifest(self.assets)['combat_bindings']['player.combat.hero']['asset_id'],'character.formal_player')
            for malformed in ['malformed','{"schema_version":1}',json.dumps({**config,'battle':{}})]:
                path.write_text(malformed);self.assertEqual(game.bindings(),game.BINDINGS)

if __name__=='__main__':unittest.main()

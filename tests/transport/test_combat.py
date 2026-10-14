"""Authenticated actual HTTP Commands over the same isolated Combat/Inventory Application."""
import unittest,json
from unittest.mock import patch
from pathlib import Path
from src.transport.danding import create_app
from src.transport.combat import register
from src.rendering.game import bindings,present
from src.rendering.game_runtime import GameRuntimeAssets
from src.core.state.envelope import thaw_json
from tests.systems import test_combat as fixtures
from tests.transport.test_danding import TOKEN

class CombatHTTPTests(unittest.TestCase):
    setUp_fixture=fixtures.CombatTests.setUp
    tearDown=fixtures.CombatTests.tearDown
    application=fixtures.CombatTests.application
    state_now=fixtures.CombatTests.state_now
    command=fixtures.CombatTests.command
    execute=fixtures.CombatTests.execute
    def setUp(self):
        self.setUp_fixture();self.assets=GameRuntimeAssets(self.root/'assets');self.web=create_app(self.application,self.save,lambda v:present(v,self.assets),self.assets.file,TOKEN,secure=False,ui_root=Path('src/ui/pages/game').resolve(),cookie_path='/game/')
        self.web.config['SESSION_COOKIE_PATH']='/';register(self.web,self.application,self.save);self.client=self.web.test_client();self.client.post('/login',data={'token':TOKEN});self.csrf=self.client.get('/api/view').json['csrf']
    def body(self,name,payload,**overrides):
        q=self.command(name,payload,**overrides);return {'protocol_version':1,'save_id':q.save_id,'request_id':q.request_id,'generation':q.generation,'expected_revision':q.expected_revision,'command':{'name':q.name,'version':q.version,'payload':thaw_json(q.payload)}}
    def post(self,body):return self.client.post('/api/command',json=body,headers={'X-CSRF-Token':self.csrf})
    def start(self):
        r=self.post(self.body('combat_start',{'encounter_id':'thorn_first'}));self.assertEqual(r.status_code,200,r.json);return r.json['receipt']['result']['combat']['battle_id']
    def win(self):
        bid=self.start()
        for _ in range(4):self.assertEqual(self.post(self.body('combat_attack',{'battle_id':bid})).status_code,200)
        return bid
    def test_battle_view_endpoint_ready_pure(self):
        before=self.state_now();r=self.client.get('/api/combat');self.assertEqual(r.status_code,200);self.assertEqual(r.json['combat']['status'],'READY');self.assertEqual(self.state_now(),before)
    def test_start_command_and_available_actions(self):
        bid=self.start();v=self.client.get('/api/combat').json['combat'];self.assertEqual(v['battle_id'],bid);self.assertEqual(v['available_commands'],['combat_attack','combat_abandon']);self.assertEqual(v['player']['hp'],80);self.assertEqual(v['enemy']['hp'],35)
    def test_attack_response_committed_events_hp(self):
        bid=self.start();r=self.post(self.body('combat_attack',{'battle_id':bid}));self.assertEqual(r.status_code,200);v=r.json['receipt']['result']['combat'];self.assertEqual((v['enemy']['hp'],v['player']['hp']),(25,74.5));self.assertEqual(v['latest_events'][1]['damage'],10);self.assertEqual(self.client.get('/api/combat').json['combat'],v)
    def test_abandon_command(self):
        bid=self.start();r=self.post(self.body('combat_abandon',{'battle_id':bid}));self.assertEqual(r.status_code,200);self.assertEqual(r.json['receipt']['result']['combat']['status'],'ABANDONED');self.assertNotIn('coins',self.state_now().domains['inventory']['holdings'])
    def test_invalid_battle_id_safe_chinese_error(self):
        self.start();before=self.state_now();r=self.post(self.body('combat_attack',{'battle_id':'missing'}));self.assertEqual(r.status_code,422);self.assertIn('战斗',r.json['message']);self.assertNotIn('unknown',r.json['message']);self.assertEqual(self.state_now(),before)
    def test_stale_revision_conflict(self):
        bid=self.start();a=self.body('combat_attack',{'battle_id':bid});b=self.body('combat_attack',{'battle_id':bid});self.assertEqual(self.post(a).status_code,200);r=self.post(b);self.assertEqual(r.status_code,409);self.assertEqual(r.json['code'],'STALE')
    def test_duplicate_command_id_returns_same_receipt(self):
        bid=self.start();q=self.body('combat_attack',{'battle_id':bid});first=self.post(q);second=self.post(q);self.assertEqual(first.json,second.json);self.assertEqual(self.state_now().domains['combat']['battle']['step'],1)
    def test_completed_battle_command_rejected(self):
        bid=self.win();before=self.state_now();r=self.post(self.body('combat_attack',{'battle_id':bid}));self.assertEqual(r.status_code,422);self.assertEqual(self.state_now(),before)
    def test_reward_state_and_actual_inventory(self):
        bid=self.win();v=self.client.get('/api/view').json;self.assertEqual(v['view']['combat']['reward_state'],'READY');self.assertNotIn('dewleaf',v['view']['holdings']);q=self.body('combat_reward',{'battle_id':bid});self.assertEqual(self.post(q).status_code,200);self.assertEqual(self.post(q).status_code,200);self.assertEqual(self.post(self.body('combat_reward',{'battle_id':bid})).status_code,200);v=self.client.get('/api/view').json['view'];self.assertEqual(v['holdings']['dewleaf']['quantity'],1);self.assertEqual(v['holdings']['coins']['quantity'],3);self.assertEqual(v['combat']['reward_state'],'SETTLED')
    def test_refresh_web_app_recovers_active_hp(self):
        bid=self.start();self.post(self.body('combat_attack',{'battle_id':bid}));before=self.client.get('/api/combat').json['combat'];other=self.web.test_client();other.post('/login',data={'token':TOKEN});self.assertEqual(other.get('/api/combat').json['combat'],before)
    def test_malformed_payload_and_client_damage_rejected(self):
        before=self.state_now()
        for payload in [{'encounter_id':'thorn_first','attack':999},{'encounter_id':None},{}]:self.assertEqual(self.post(self.body('combat_start',payload)).status_code,422)
        bad=self.body('combat_start',{'encounter_id':'thorn_first'});bad['command']['payload']=[];self.assertEqual(self.post(bad).status_code,400);self.assertEqual(self.state_now(),before)
    def test_security_uses_existing_auth_csrf_origin(self):
        private=self.web.test_client();self.assertEqual(private.get('/api/combat').status_code,401);q=self.body('combat_start',{'encounter_id':'thorn_first'});self.assertEqual(self.client.post('/api/command',json=q).status_code,403);self.assertEqual(self.client.post('/api/command',json=q,headers={'X-CSRF-Token':self.csrf,'Origin':'https://evil.invalid'}).status_code,403);self.assertNotIn('combat',self.state_now().domains)
    def test_true_battle_presentation_fallback_and_domain_identity(self):
        self.start();r=self.client.get('/api/view').json;self.assertTrue(r['presentation']['battle']['implemented']);self.assertFalse(r['presentation']['battle']['read_only']);assets=r['presentation']['battle']['assets'];self.assertEqual(assets['player']['asset_id'],bindings()['combat_bindings'].get(r['view']['combat']['player']['asset_id']) or r['view']['combat']['player']['asset_id']);self.assertEqual(assets['enemy']['asset_id'],bindings()['combat_bindings'].get(r['view']['combat']['enemy']['asset_id']) or r['view']['combat']['enemy']['asset_id']);self.assertTrue(assets['player']['fallback']);self.assertTrue(assets['enemy']['fallback']);self.assertIsNone(assets['background']);self.assertTrue(assets['slash']['fallback']);self.assertNotIn('Source',json.dumps(assets))

if __name__=='__main__':unittest.main()

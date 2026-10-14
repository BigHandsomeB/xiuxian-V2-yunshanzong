"""Shipping factory and readonly HTTP over isolated retirement fixtures."""
import unittest
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
from io import StringIO
from contextlib import redirect_stdout
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.test import Client
from werkzeug.wrappers import Response
from tests.systems.test_economy import EconomyFixture
from tools.playable.game import game_factory
from src.application.item_retirement import RetiredEconomyApplication
from tools.playable.retire_items import run
from src.transport.danding import create_app
from src.rendering.game import present,manifest
from src.rendering.game_runtime import GameRuntimeAssets
from src.core.validation import ConflictError
class RetirementHTTPTests(EconomyFixture,unittest.TestCase):
 def setUp(self):
  super().setUp();assets=GameRuntimeAssets(self.root/'assets');factory=game_factory(self.path,self.root,self.clock,registry=self.registry,application_class=RetiredEconomyApplication)
  http=create_app(factory,self.save,lambda v:present(v,assets),assets.file,'retirement-isolated-token-123',secure=False,ui_root=Path('src/ui/pages/game').resolve(),cookie_path='/game/',asset_view=lambda:manifest(assets));http.testing=True
  self.client=Client(DispatcherMiddleware(lambda e,s:(s('404 Not Found',[]),[])[1],{'/game':http}),Response);self.client.post('/game/login',data={'token':'retirement-isolated-token-123'})
 def post(self,name,payload):
  v=self.client.get('/game/api/view').json
  return self.client.post('/game/api/command',json={'protocol_version':1,'save_id':self.save,'generation':v['generation'],'expected_revision':v['revision'],'request_id':str(uuid4()),'command':{'name':name,'version':1,'payload':payload}},headers={'X-CSRF-Token':v['csrf']})
 def test_factory_rejects_retired_recipe(self):
  before=self.state();r=self.post('production_start',{'building_id':self.building('forge'),'recipe_id':'forge_sword'});self.assertEqual(r.status_code,422);self.assertIn('移除',r.json['error']);self.assertEqual(self.state(),before)
 def test_factory_view_has_no_forge_items_and_get_is_pure(self):
  s=self.state();r=self.client.get('/game/api/view');self.assertEqual(r.status_code,200);self.assertFalse(any(x['recipe_id'].startswith('forge') for x in r.json['view']['economy']['recipes']));self.assertEqual(self.state(),s)
 def test_no_public_retirement_endpoint(self):
  s=self.state();r=self.post('retire_three_items',{});self.assertIn(r.status_code,(400,422));self.assertEqual(self.state(),s)
 def test_cli_fails_closed_if_scope_changed(self):
  (self.root/'save-id').write_text(self.save);self.path.rename(self.root/'danding.sqlite3');self.path=self.root/'danding.sqlite3'
  with self.assertRaises(ConflictError):run(self.root)
 def test_cli_application_commit_matches_authorized_scope(self):
  bid=self.command('combat_start',{'encounter_id':'thorn_first'}).result['combat']['battle_id']
  for _ in range(4):self.command('combat_attack',{'battle_id':bid})
  self.command('combat_reward',{'battle_id':bid});(self.root/'save-id').write_text(self.save)
  # CLI uses the existing private filename, not a second Save; fixture only.
  self.path.rename(self.root/'danding.sqlite3');self.path=self.root/'danding.sqlite3';before=self.state()
  with redirect_stdout(StringIO()):run(self.root,expected_revision=before.revision,expected_dewleaf=1)
  after=self.state();self.assertNotIn('dewleaf',after.domains['inventory']['holdings']);self.assertFalse(after.domains['equipment']['instances']);self.assertEqual(before.time,after.time)

"""Real slice HTTP over isolated Foundation SQLite; no V1/production access."""
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from uuid import uuid4
import copy, hashlib, json, tempfile, unittest
from unittest.mock import patch
from src.application.danding import DandingApplication, initial_slice, target, worker
from src.application.memory import Command
from src.application.settlement import SettlementRequest
from src.application.recovery import RecoveryApplication
from src.core.save.recovery import RecoveryRequest
from src.core.save.sqlite import SQLiteSave,V2_ROOT
from src.core.state.envelope import thaw_json
from src.core.time.config import OFFLINE_CAP_MS
from src.core.time.model import Continuation
from src.data.recipes.alchemy import load_alchemy
from src.rendering.assets import RuntimeAssets
from src.rendering.scenes.sect.danding import present,scene_state
from src.transport.danding import create_app
from tests.fixtures.time import ManualClock

TOKEN='test-private-play-token-long-enough'


class DandingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=V2_ROOT/'tests');self.root=Path(self.temp.name)
        self.registry=load_alchemy();self.clock=ManualClock(1000);self.path=self.root/'slice.sqlite3'
        self.state=initial_slice(self.registry,last_settled_at_ms=1000);self.save=self.state.save_id
        with SQLiteSave.initialize(self.path,allowed_root=self.root) as store:
            DandingApplication(store,self.registry,self.clock).create(self.state)
        self.assets=RuntimeAssets(self.root/'assets');(self.root/'assets/runtime').mkdir(parents=True)
        self.web=self.make_web();self.client=self.web.test_client();self.login()
    def tearDown(self):self.temp.cleanup()
    @contextmanager
    def application(self):
        with SQLiteSave(self.path,allowed_root=self.root) as store:yield DandingApplication(store,self.registry,self.clock)
    def make_web(self):
        app=create_app(self.application,self.save,lambda v:present(v,self.assets),self.assets.file,TOKEN,secure=False)
        app.config['SESSION_COOKIE_PATH']='/'  # Direct adapter tests; mount is covered separately.
        return app
    def login(self,client=None):return (client or self.client).post('/login',data={'token':TOKEN})
    def view(self):
        r=self.client.get('/api/view');self.assertEqual(r.status_code,200,r.json);return r.json
    def body(self,action=None):
        v=self.view()['view'];body={'protocol_version':1,'save_id':v['save_id'],'request_id':str(uuid4()),'generation':v['generation'],'expected_revision':v['revision']}
        body.update({'command':{'name':{'start':'alchemy_start','assign':'work_assign','unassign':'work_unassign'}.get(action,action),'version':1,'payload':{}}} if action else {'continuation':v['time']['continuation']});return body
    def post(self,path,body):return self.client.post(path,json=body,headers={'X-CSRF-Token':self.view()['csrf']})
    def start(self):return self.post('/api/command',self.body('start'))
    def settle(self,ms):self.clock.advance(ms);return self.post('/api/settle',self.body())
    def quantity(self,key):return self.view()['view']['inventory'][key]['quantity']
    def stock(self,amounts):
        with self.application() as game:
            s=game.query(self.save);return game.execute(Command(self.save,s.generation,s.revision,str(uuid4()),'inventory_grant',{'amounts':amounts}))
    def publish(self,asset_id='scene.building.a219f807916ef.prepare',file='runtime/test.png'):
        path=self.root/'assets'/file;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'test-runtime')
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        manifest={'schema_version':1,'assets':{asset_id:{'version':1,'files':[{'file':file,'sha256':digest,'width':256,'height':144}]}}}
        (self.root/'assets/manifest.json').write_text(json.dumps(manifest));return manifest,digest

    def test_initial_scenario_uses_real_domains(self):
        v=self.view()['view'];self.assertEqual(v['inventory']['herb']['quantity'],30)
        self.assertEqual(v['inventory']['pill']['quantity'],0);self.assertEqual(v['work']['assigned_count'],1)
        with self.application() as game:self.assertNotIn('alchemy',game.query(self.save).domains)
    def test_view_building_and_recipe_requirements(self):
        v=self.view()['view'];self.assertEqual(v['building']['name'],'丹鼎阁');r=v['alchemy']['recipes'][0]
        self.assertEqual((r['recipe_id'],r['duration_ms'],r['batch_inputs'],r['batch_outputs']),('pill',30000,{'herb':5},{'pill':1}))
        self.assertTrue(r['can_start']);self.assertEqual(v['time']['day_length_ms'],120000)
    def test_single_snapshot_view(self):
        with self.application() as game,patch.object(game,'query',wraps=game.query) as query:
            game.view(self.save);self.assertEqual(query.call_count,1)
    def test_get_does_not_claim_clock_settle_or_change_revision(self):
        self.start();before=self.view();self.clock.advance(60000)
        with patch.object(self.clock,'now_ms',side_effect=AssertionError('GET must not read clock')):
            after=self.view()
        self.assertEqual(before,after);self.assertEqual(self.quantity('pill'),0)
    def test_http_start_consumes_real_inputs_once(self):
        request=self.body('start');r=self.post('/api/command',request);self.assertEqual(r.status_code,200,r.json)
        self.assertEqual(self.quantity('herb'),25);v=self.view()['view']
        self.assertEqual(v['alchemy']['current']['status'],'WORKING');self.assertTrue(v['building']['busy'])
        self.assertEqual(v['work']['working_count'],1);revision=v['revision']
        replay=self.post('/api/command',request);self.assertEqual(replay.json,r.json)
        self.assertEqual(self.quantity('herb'),25);self.assertEqual(self.view()['view']['revision'],revision)
    def test_two_different_start_clicks_do_not_create_two_jobs(self):
        body=self.body('start');self.assertEqual(self.post('/api/command',body).status_code,200)
        body['request_id']=str(uuid4());self.assertEqual(self.post('/api/command',body).status_code,409)
        body=self.body('start');self.assertEqual(self.post('/api/command',body).status_code,409)
        self.assertEqual(self.quantity('herb'),25)
    def test_explicit_settlement_completes_once_and_releases(self):
        self.start();self.clock.advance(30000);body=self.body();r=self.post('/api/settle',body)
        self.assertEqual(r.status_code,200,r.json);v=self.view()['view']
        self.assertEqual(v['alchemy']['current']['status'],'COMPLETE');self.assertEqual(v['inventory']['pill']['quantity'],1)
        self.assertFalse(v['building']['busy']);self.assertEqual(v['work']['working_count'],0)
        self.assertEqual(self.post('/api/settle',body).json,r.json);self.settle(0);self.assertEqual(self.quantity('pill'),1)
    def test_complete_can_start_again(self):
        self.start();self.settle(30000);self.assertEqual(self.start().status_code,200)
        self.settle(30000);self.assertEqual(self.quantity('pill'),2);self.assertEqual(self.quantity('herb'),20)
    def test_blocking_materials_no_partial_creation(self):
        with self.application() as game:
            s=game.query(self.save);game.execute(Command(self.save,s.generation,s.revision,str(uuid4()),'inventory_consume',{'amounts':{'herb':30}}))
        before=self.view()['view'];self.assertIn('INSUFFICIENT_INPUTS',before['alchemy']['recipes'][0]['blocking_reasons'])
        self.assertEqual(self.start().status_code,422);self.assertEqual(self.view()['view'],before)
    def test_legal_assignment_and_unassignment_via_application(self):
        r=self.post('/api/command',self.body('unassign'));self.assertEqual(r.status_code,200)
        self.assertIn('NO_ASSIGNED_WORKERS',self.view()['view']['alchemy']['recipes'][0]['blocking_reasons'])
        self.assertEqual(self.start().status_code,422)
        self.assertEqual(self.post('/api/command',self.body('assign')).status_code,200);self.assertEqual(self.start().status_code,200)
    def test_midjob_unassignment_keeps_current_commitment(self):
        self.start();self.post('/api/command',self.body('unassign'));v=self.view()['view']
        self.assertEqual((v['work']['assigned_count'],v['work']['working_count']),(0,1))
        self.settle(30000);self.assertEqual(self.quantity('pill'),1);self.assertEqual(self.view()['view']['work']['working_count'],0)
    def test_output_ready_keeps_all_output_and_can_retry(self):
        # Exercise finite-capacity output with an explicit fixture; real pills use the unlimited bag.
        from src.data.items.resources import ResourceDefinition
        with patch.object(ResourceDefinition,'warehouse_counted',property(lambda row:row.capacity_counted)):
            self.start();self.stock({'wood':6975});self.settle(30000);v=self.view()['view']
            self.assertEqual(v['alchemy']['current']['status'],'OUTPUT_READY');self.assertEqual(self.quantity('pill'),0)
            self.assertEqual(v['work']['working_count'],0);self.assertTrue(v['building']['busy'])
            self.assertEqual(self.view()['presentation']['scene']['state'],'finish');self.settle(0);self.assertEqual(self.quantity('pill'),0)
            with self.application() as game:
                s=game.query(self.save);game.execute(Command(self.save,s.generation,s.revision,str(uuid4()),'inventory_consume',{'amounts':{'wood':1}}))
            self.settle(0);self.assertEqual(self.quantity('pill'),1);self.assertFalse(self.view()['view']['building']['busy'])
    def test_offline_return_uses_existing_cap(self):
        self.start();r=self.settle(OFFLINE_CAP_MS+999)
        self.assertEqual(r.json['receipt']['result']['accepted_ms'],OFFLINE_CAP_MS)
        self.assertEqual(r.json['receipt']['result']['discarded_ms'],999);self.assertEqual(self.quantity('pill'),1)
    def test_http_refresh_and_service_recreation_keep_job(self):
        self.start();self.settle(10000);before=self.view()['view'];self.web=self.make_web();self.client=self.web.test_client();self.login()
        self.assertEqual(self.view()['view'],before);self.settle(20000);self.assertEqual(self.quantity('pill'),1)
    def test_restart_replay_idempotency(self):
        body=self.body('start');receipt=self.post('/api/command',body).json
        self.web=self.make_web();self.client=self.web.test_client();self.login()
        replay=self.post('/api/command',body).json
        self.assertEqual(replay['receipt'],receipt['receipt'])
        self.assertEqual(replay['view'],receipt['view'])
        self.assertEqual(replay['presentation'],receipt['presentation'])
        self.assertEqual(replay['csrf'],self.view()['csrf'])  # New login, same committed intent.
        self.assertEqual(self.quantity('herb'),25)
    def test_command_snapshot_matches_authoritative_get(self):
        body=self.body('unassign');response=self.post('/api/command',body)
        self.assertEqual(response.status_code,200,response.json)
        reply=response.json;current=self.view()
        for key in ('view','presentation','csrf','save_id','generation','revision'):
            self.assertEqual(reply[key],current[key],key)
        self.assertEqual(reply['receipt']['request_id'],body['request_id'])
        self.assertEqual(reply['receipt']['committed_revision'],reply['revision'])

    def test_chunked_settlement_same_gameplay_outcome(self):
        self.start();self.settle(10000);self.settle(10000);self.settle(10000)
        v=self.view()['view'];self.assertEqual((v['inventory']['herb']['quantity'],v['inventory']['pill']['quantity'],v['work']['working_count']),(25,1,0))
    def test_pending_resume_projection(self):
        # Two existing Domain events, not a new timer or recipe; force budget boundary.
        with self.application() as game:
            s=game.query(self.save);garden=next(k for k,row in s.domains['sect']['buildings'].items() if row['definition_id']=='field')
            gather=next(k for k,row in s.domains['disciples']['groups'].items() if row['definition_id']=='ordinary_farm')
            for name,payload in [('work_assign',{'worker_id':gather,'building_id':garden,'count':1}),('production_start',{'building_id':garden,'recipe_id':'grain','unlock_floor':0,'unlock_realm':0})]:
                s=game.query(self.save);game.execute(Command(self.save,s.generation,s.revision,str(uuid4()),name,payload))
        self.start();self.clock.advance(100000)
        with self.application() as game:
            s=game.query(self.save);receipt=game.settle(SettlementRequest(self.save,s.generation,s.revision,str(uuid4()),1))
        if receipt.result.status=='PENDING':
            v=self.view()['view'];self.assertTrue(v['time']['pending']);self.assertIsNotNone(v['time']['continuation'])
            self.assertEqual(self.post('/api/settle',self.body()).status_code,200);self.assertFalse(self.view()['view']['time']['pending'])
        else:self.fail('fixture did not produce pending')
    def test_scene_mapping_uses_only_committed_progress(self):
        self.assertEqual(self.view()['presentation']['scene']['state'],'prepare');self.start()
        self.assertEqual(self.view()['presentation']['scene']['state'],'measure')
        for ms,expected in [(4000,'add_herbs'),(5000,'stable'),(12000,'high_fire'),(9000,'finish')]:
            self.settle(ms);self.assertEqual(self.view()['presentation']['scene']['state'],expected)
    def test_presentation_never_produces_rewards(self):
        self.start();view=self.view()['view'];before=copy.deepcopy(view);view['alchemy']['current']['status']='COMPLETE'
        for _ in range(5):self.assertEqual(present(view,self.assets)['scene']['state'],'finish')
        self.assertEqual(self.quantity('pill'),0);self.assertEqual(self.view()['view'],before)
    def test_missing_asset_and_manifest_safe_fallback(self):
        self.assertIsNone(self.view()['presentation']['scene']['asset']);self.assertTrue(self.view()['presentation']['scene']['fallback'])
        (self.root/'assets/manifest.json').write_text('broken');self.assertEqual(self.client.get('/api/view').status_code,200)
    def test_scene_resolves_through_manifest_and_runtime_route(self):
        _,digest=self.publish();view=self.view()['presentation']['scene'];self.assertEqual(view['asset']['asset_id'],'scene.building.a219f807916ef.prepare')
        self.assertEqual(view['asset']['width'],256);self.assertNotIn('path',view['asset'])
        response=self.client.get('/runtime/scene.building.a219f807916ef.prepare/'+digest)
        self.assertEqual(response.status_code,200);response.close()
    def test_static_room_keeps_committed_stage_without_swapping_background(self):
        self.publish();self.start();v=self.view()['presentation']['scene']
        self.assertEqual(v['state'],'measure');self.assertEqual(v['asset']['asset_id'],'scene.building.a219f807916ef.prepare');self.assertFalse(v['fallback']);self.assertEqual(v['mode'],'static')
        first=v['asset']['asset_id'];self.settle(30000);done=self.view()['presentation']['scene']
        self.assertEqual(done['state'],'finish');self.assertEqual(done['asset']['asset_id'],first);self.assertEqual(self.quantity('pill'),1)
    def test_runtime_path_escape_and_source_rejected(self):
        for file in ('../escape.png','source/raw.png'):
            manifest,_=self.publish(file='runtime/test.png');manifest['assets']['scene.building.a219f807916ef.prepare']['files'][0]['file']=file
            (self.root/'assets/manifest.json').write_text(json.dumps(manifest));self.assertIsNone(self.assets.resolve('scene.building.a219f807916ef.prepare'))
    def test_runtime_symlink_and_corrupt_digest_rejected(self):
        _,digest=self.publish();path=self.root/'assets/runtime/test.png';path.write_bytes(b'altered')
        self.assertEqual(self.client.get('/runtime/scene.building.a219f807916ef.prepare/'+digest).status_code,404)
        path.unlink();path.symlink_to(self.root/'assets/manifest.json');self.assertIsNone(self.assets.resolve('scene.building.a219f807916ef.prepare'))
    def test_anonymous_access_is_protected(self):
        client=self.web.test_client();self.assertEqual(client.get('/api/view').status_code,401)
        self.assertEqual(client.post('/api/command',json={}).status_code,401);self.assertEqual(client.get('/').status_code,302)
    def test_wrong_origin_and_csrf_rejected(self):
        self.assertEqual(self.client.post('/api/command',json=self.body('start')).status_code,403)
        self.assertEqual(self.client.post('/api/command',json=self.body('start'),headers={'Origin':'https://other.example','X-CSRF-Token':self.view()['csrf']}).status_code,403)
        self.assertEqual(self.client.post('/login',data={'token':TOKEN},headers={'Origin':'https://other.example'}).status_code,403)
    def test_public_origin_with_port_is_valid(self):
        web=create_app(self.application,self.save,lambda v:present(v,self.assets),self.assets.file,TOKEN,allowed_hosts=['example.test'],secure=True)
        client=web.test_client();r=client.post('/login',data={'token':TOKEN},base_url='https://example.test:8443',headers={'Origin':'https://example.test:8443'})
        self.assertEqual(r.status_code,302);self.assertIn('Secure',r.headers['Set-Cookie'])
    def test_no_arbitrary_grant_or_save_id_override(self):
        body=self.body('inventory_grant');self.assertEqual(self.post('/api/command',body).status_code,422)
        body=self.body('start');body['save_id']=str(uuid4());self.assertEqual(self.post('/api/command',body).status_code,400)
        self.assertEqual(self.quantity('herb'),30)
    def test_stale_revision_and_generation_handled(self):
        body=self.body('start');body['generation']+=1;self.assertEqual(self.post('/api/command',body).status_code,409)
        body=self.body('start');self.settle(1000);self.assertEqual(self.post('/api/command',body).status_code,409)
    def test_same_request_different_action_conflicts(self):
        body=self.body('start');self.post('/api/command',body);body['command']['name']='work_unassign'
        self.assertEqual(self.post('/api/command',body).status_code,409);self.assertEqual(self.view()['view']['work']['assigned_count'],1)
    def test_persistence_failure_does_not_leak_partial_state(self):
        before=self.view()['view']
        with patch.object(SQLiteSave,'commit',side_effect=__import__('src.core.save.codec',fromlist=['PersistenceError']).PersistenceError('forced')):
            self.assertEqual(self.start().status_code,503)
        self.assertEqual(self.view()['view'],before)
    def test_application_is_only_http_gameplay_entry(self):
        with self.application() as game:
            self.assertEqual(set(game.query(self.save).domains),{'inventory','sect','production','disciples'})
        source=(V2_ROOT/'src/transport/danding.py').read_text()
        self.assertNotIn('sqlite',source.lower());self.assertNotIn('src.systems',source)
    def test_mobile_document_uses_scene_manifest_controls_and_safe_area(self):
        r=self.client.get('/');self.assertEqual(r.status_code,200)
        html=r.data.decode();self.assertIn('viewport-fit=cover',html);self.assertIn('id="scene"',html);self.assertIn('dialog',html)
        script=(V2_ROOT/'src/ui/pages/danding/static/danding.js').read_text()
        self.assertNotIn('setInterval',script);self.assertIn('visibilitychange',script)
        self.assertNotIn('30秒',script);self.assertNotIn('5灵草',script)
    def test_login_survives_wsgi_recreation(self):
        # Stable, scope-separated cookie key; a restart does not reset the save or login.
        other=self.make_web();cookie=self.client.get_cookie('xianxia_play')
        client=other.test_client();client.set_cookie('xianxia_play',cookie.value)
        self.assertEqual(client.get('/api/view').status_code,200)
    def test_error_messages_do_not_expose_trace_or_enum(self):
        r=self.post('/api/command',{'invalid':True});self.assertEqual(r.status_code,400)
        self.assertNotIn('Traceback',r.data.decode());self.assertIn('请求版本或格式不正确',r.json['error'])

    def test_recovery_projection_and_old_request_rejection(self):
        self.start();self.settle(10000)
        with self.application() as game:game.checkpoint(self.save)
        old=self.body('start');self.settle(20000);self.assertEqual(self.quantity('pill'),1)
        with self.application() as game:
            recovery=RecoveryApplication(game.foundation,self.clock);observation=recovery.inspect(self.save)
            result=recovery.recover(RecoveryRequest(self.save,observation.current_generation,observation.current_fingerprint,observation.source_fingerprint,str(uuid4()),'slice test'))
            self.assertEqual(result.status,'SUCCESS')
        view=self.view()['view'];self.assertEqual(view['generation'],2);self.assertEqual(view['alchemy']['current']['status'],'WORKING')
        self.assertEqual(view['inventory']['pill']['quantity'],0);self.assertEqual(self.post('/api/command',old).status_code,409)
        self.settle(20000);self.assertEqual(self.quantity('pill'),1)

    def test_real_mount_cookie_and_routes(self):
        from werkzeug.middleware.dispatcher import DispatcherMiddleware
        from werkzeug.test import Client
        from werkzeug.wrappers import Response
        web=create_app(self.application,self.save,lambda v:present(v,self.assets),self.assets.file,TOKEN,secure=False)
        def absent(environ,start_response):start_response('404 Not Found',[]);return [b'Not Found']
        client=Client(DispatcherMiddleware(absent,{'/play':web}),Response)
        response=client.post('/play/login',data={'token':TOKEN})
        self.assertEqual(response.status_code,302);self.assertTrue(response.location.endswith('/play/'))
        self.assertIn('Path=/play/',response.headers['Set-Cookie'])
        self.assertEqual(client.get('/play/api/view').status_code,200)
        page=client.get('/play/');self.assertIn('/play/static/danding.js',page.text)
        response=client.get('/play/static/session.js');self.assertEqual(response.status_code,200);response.close()

    def test_foundation_versioned_http_envelope(self):
        response=self.view();self.assertEqual(response['protocol_version'],1)
        self.assertEqual((response['save_schema_version'],response['data_schema_version']),(1,1))
        self.assertEqual(response['revision'],response['view']['revision'])
        self.assertEqual(response['time'],response['view']['time'])
        for key,value in [('protocol_version',2),('protocol_version',True)]:
            body=self.body('start');body[key]=value;self.assertEqual(self.post('/api/command',body).status_code,400)
        body=self.body('start');body['command']['version']=2
        result=self.post('/api/command',body);self.assertEqual(result.status_code,400)
        self.assertTrue({'code','category','message','request_id','retryable'}<=result.json.keys())
        self.assertEqual(self.quantity('herb'),30)

    def test_invalid_json_and_oversized_request_are_safe(self):
        headers={'X-CSRF-Token':self.view()['csrf'],'Content-Type':'application/json'}
        for body,status in [('{broken',400),('x'*5000,413)]:
            response=self.client.post('/api/command',data=body,headers=headers)
            self.assertEqual(response.status_code,status);self.assertEqual(response.json['category'],'VALIDATION')
        self.assertEqual(self.quantity('herb'),30)

    def test_stale_settlement_and_command_return_current_revision(self):
        first=self.body();self.clock.advance(1)
        self.assertEqual(self.post('/api/settle',first).status_code,200)
        current=self.view()['view']
        stale={**first,'request_id':str(uuid4())}
        response=self.post('/api/settle',stale)
        self.assertEqual(response.status_code,409)
        self.assertEqual(response.json['current_revision'],current['revision'])
        self.assertEqual(response.json['current_generation'],current['generation'])
        self.assertEqual(self.view()['view'],current)
        command=self.body('start');command['expected_revision']=first['expected_revision']
        response=self.post('/api/command',command)
        self.assertEqual(response.status_code,409)
        self.assertEqual(response.json['current_revision'],current['revision'])
        self.assertEqual(self.view()['view'],current)


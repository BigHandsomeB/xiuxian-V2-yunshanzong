"""Reports are observations: temporary saves only; original gameplay stays identical."""
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
from src.application import offline_reports as reports, equipment as equip
from src.application.economy_settlement import EconomySettlement
from src.application.sect_management import ManagementApplication
from src.application.memory import Command
from src.application.settlement import SettlementRequest
from src.core.save.sqlite import SQLiteSave, V2_ROOT
from src.core.state.envelope import thaw_json
from src.core.time.config import OFFLINE_CAP_MS
from src.core.time.model import Continuation
from src.core.validation import ConflictError, ValidationError
from tests.systems import test_settlement_batch as fixtures
from tests.fixtures.settlement_legacy import legacy_advance


class OfflineReportTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.SettlementBatchTests(); f.setUp(); self.addCleanup(f.doCleanups)
        self.f=f; self.registry=f.registry; self.clock=f.clock; self.state=f.state
        self.temp=tempfile.TemporaryDirectory(dir=V2_ROOT/'tests'); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.path=self.root/'reports.sqlite3'

    def drain(self, state, target, batch=2):
        events=[]; receipts=[]
        for _ in range(20000):
            state,result=self.f.app.engine.advance(state,max_events=batch,
                now_ms=None if state.time['pending'] else target,
                continuation=Continuation.for_state(state) if state.time['pending'] else None)
            events.extend(result.processed_events); receipts.append(result)
            if not state.time['pending']: return state,events,receipts
        self.fail('fixture did not finish')

    def idle(self):
        d=thaw_json(self.state.domains['dungeon']); d['auto'].update(enabled=False,wake=None,tick_ready=False)
        return replace(self.state,domains={**self.state.domains,'dungeon':d})

    def seed(self, state=None):
        with SQLiteSave.initialize(self.path,allowed_root=self.root) as store:
            app=ManagementApplication(store,self.registry,self.clock); app.create(state or self.state)

    def request(self, state, batch=2):
        return SettlementRequest(state.save_id,state.generation,state.revision,str(uuid4()),batch,
            Continuation.for_state(state) if state.time['pending'] else None)

    def test_server_simulation_window_threshold_not_page_visibility(self):
        for elapsed in (0,59000,60000,60001,8*3600000):
            with self.subTest(elapsed=elapsed):
                end,_,rounds=self.drain(self.idle(),1000+elapsed)
                queue=end.domains.get(reports.DOMAIN,{}).get('unread',[])
                self.assertEqual(len(queue),int(elapsed>60000))
                if queue:
                    self.assertEqual(queue[0]['duration']['settled_ms'],elapsed)
                    self.assertEqual(rounds[-1].offline_report['report_id'],queue[0]['report_id'])
                    self.assertIs(type(rounds[-1].offline_report),dict)
        # No browser state or client clock is passed to the server at all.
        end,_,_=self.drain(self.idle(),500)
        self.assertNotIn(reports.DOMAIN,end.domains)

    def test_multiround_accumulates_and_new_wall_time_does_not_extend_target(self):
        full,events,_=self.drain(self.state,121000,batch=4096)
        chunked,chunk_events,rounds=self.drain(self.state,121000,batch=1)
        self.f.assert_same(full,chunked); self.assertEqual(events,chunk_events)
        self.assertTrue(all(r.offline_report is None for r in rounds[:-1]))
        a=thaw_json(full.domains[reports.DOMAIN]['unread'][0]); b=thaw_json(chunked.domains[reports.DOMAIN]['unread'][0])
        a.pop('completed_revision'); b.pop('completed_revision'); self.assertEqual(a,b)
        self.assertEqual(b['combat']['wins'],chunked.domains['dungeon']['auto']['wins']-self.state.domains['dungeon']['auto']['wins'])
        self.assertGreater(b['combat']['wins'],0)
        partial,result=self.f.app.engine.advance(self.state,max_events=1,now_ms=121000)
        self.assertEqual(partial.time['pending']['report_id'],reports.active(partial)['report_id'])
        self.clock.advance(10**9)
        end,_,last=self.drain(partial,10**9,batch=2)
        self.assertEqual(last[-1].target_sim_ms,120000)
        self.assertEqual(end.domains[reports.DOMAIN]['unread'][0]['duration']['settled_ms'],120000)

    def test_old_pending_has_no_report_first_new_complete_window_does(self):
        with patch.object(EconomySettlement,'advance',legacy_advance):
            old,result=self.f.app.engine.advance(self.state,max_events=1,now_ms=121000)
        self.assertIsNotNone(old.time['pending']); self.assertNotIn(reports.DOMAIN,old.domains)
        end,_,last=self.drain(old,10**9)
        self.assertNotIn(reports.DOMAIN,end.domains); self.assertIsNone(last[-1].offline_report)
        new,_,_=self.drain(end,end.time['last_settled_at_ms']+60001)
        self.assertEqual(len(new.domains[reports.DOMAIN]['unread']),1)

    def test_cap_is_existing_server_cap_and_actual_duration_preserved(self):
        end,_,rounds=self.drain(self.idle(),1000+80*3600000)
        r=end.domains[reports.DOMAIN]['unread'][0]
        self.assertEqual(r['duration'],{'actual_ms':80*3600000,'settled_ms':OFFLINE_CAP_MS,'discarded_ms':80*3600000-OFFLINE_CAP_MS,'capped':True})
        self.assertEqual(rounds[-1].accepted_ms,OFFLINE_CAP_MS)
        exact,_,_=self.drain(self.idle(),1000+OFFLINE_CAP_MS)
        self.assertFalse(exact.domains[reports.DOMAIN]['unread'][0]['duration']['capped'])

    def test_persist_restart_and_replay_each_chunk_and_completion(self):
        self.seed(); self.clock.advance(120000); request=None; last=None
        for _ in range(1000):
            with SQLiteSave(self.path,allowed_root=self.root) as store:
                app=ManagementApplication(store,self.registry,self.clock); state=app.query(self.state.save_id)
                request=self.request(state); receipt=app.settle(request); after=app.query(state.save_id)
                self.assertEqual(app.settle(request),receipt); self.assertEqual(app.query(state.save_id),after)
                if last is not None:
                    self.assertEqual(app.settle(last[0]),last[1]); self.assertEqual(app.query(state.save_id),after)
                last=(request,receipt)
                if not after.time['pending']: break
        else: self.fail('fixture did not finish')
        with SQLiteSave(self.path,allowed_root=self.root) as store:
            app=ManagementApplication(store,self.registry,self.clock)
            r=app.view(self.state.save_id)['offline_reports'][0]
            self.assertEqual(r['report_id'],receipt.result.offline_report['report_id'])
            self.assertEqual(app.settle(request),receipt)
            self.assertEqual(len(app.view(self.state.save_id)['offline_reports']),1)

    def test_ack_replay_refresh_and_paused_world(self):
        end,_,_=self.drain(self.idle(),121000); self.seed(end)
        with SQLiteSave(self.path,allowed_root=self.root) as store:
            app=ManagementApplication(store,self.registry,self.clock); state=app.query(end.save_id)
            app.execute(Command(state.save_id,state.generation,state.revision,str(uuid4()),'world_pause',{}))
            state=app.query(end.save_id); report=state.domains[reports.DOMAIN]['unread'][0]
            q=Command(state.save_id,state.generation,state.revision,str(uuid4()),'offline_report_ack',{'report_id':report['report_id']})
            receipt=app.execute(q); after=app.query(end.save_id)
            self.assertEqual(app.execute(q),receipt); self.assertEqual(after,app.query(end.save_id))
            self.assertTrue(after.time['world_paused']); self.assertEqual(after.time,state.time)
        with SQLiteSave(self.path,allowed_root=self.root) as store:
            app=ManagementApplication(store,self.registry,self.clock); self.assertEqual(app.view(end.save_id)['offline_reports'],())
            state=app.query(end.save_id)
            replay=replace(q,request_id=str(uuid4()),expected_revision=state.revision)
            app.execute(replay); self.assertEqual(app.query(end.save_id),state)

    def test_pause_and_stop_auto_preceding_settlement_report(self):
        self.seed(self.idle()); self.clock.advance(120000)
        with SQLiteSave(self.path,allowed_root=self.root) as store:
            app=ManagementApplication(store,self.registry,self.clock); state=app.query(self.state.save_id)
            r=app.execute(Command(state.save_id,state.generation,state.revision,str(uuid4()),'world_pause',{}))
            self.assertIsNotNone(r.result['settlement']['offline_report'])
            self.assertEqual(len(app.view(state.save_id)['offline_reports']),1)
        end,_,_=self.drain(self.state,121000); self.assertEqual(len(end.domains[reports.DOMAIN]['unread']),1)
        # Stop command does not erase the preceding report (same flow as the client).
        with tempfile.TemporaryDirectory(dir=self.root) as directory:
            root=Path(directory)
            with SQLiteSave.initialize(root/'stop.sqlite3',allowed_root=root) as store:
                app=ManagementApplication(store,self.registry,self.clock); app.create(end); state=app.query(end.save_id)
                app.execute(Command(state.save_id,state.generation,state.revision,str(uuid4()),'dungeon_auto',{'enabled':False,'mode':'farm','floor':2,'floor_count':3}))
                self.assertEqual(len(app.view(end.save_id)['offline_reports']),1)

    def test_queue_limit_merges_without_losing_counts_outputs_equipment_or_progress(self):
        state=self.idle(); originals=[]
        # Distinct windows, all counters populated before finalization.
        for n in range(12):
            state=reports.begin(state,state.time['last_settled_at_ms']+61000)
            state=reports.observe_combat(state,'wins'); state=reports.observe_recruitment(state)
            state=reports.observe_production(state,{'recipe_id':'grain'},{'grain':n+1},0)
            identity=f'{state.save_id}:{state.generation}:i:{n+1000}'
            state=reports.observe_equipment(state,identity,'green','GAIN')
            state=reports.observe_equipment(state,identity,'green','SELL')
            inventory=thaw_json(state.domains['inventory']); inventory['holdings']['grain']=inventory['holdings'].get('grain',0)+n+1
            state=replace(state,domains={**state.domains,'inventory':inventory})
            candidate,result=self.f.app.engine.core.advance(state,max_events=1,now_ms=state.time['last_settled_at_ms']+61000)
            self.assertEqual(result.status,'COMPLETE')
            state,r=reports.finish(candidate,result,self.registry); originals.append(r); reports.validate(state)
            self.assertLessEqual(len(state.domains[reports.DOMAIN]['unread']),5)
        queue=state.domains[reports.DOMAIN]['unread']; self.assertEqual(len(queue),5)
        summary=queue[0]; self.assertEqual(summary['summary_count'],8)
        self.assertEqual(sum(r['summary_count'] for r in queue),12)
        self.assertEqual(sum(r['items'].get('grain',0) for r in queue),sum(range(1,13)))
        self.assertEqual(sum(r['combat']['wins'] for r in queue),12)
        self.assertEqual(sum(r['equipment']['quality_counts']['green']['gained'] for r in queue),12)
        self.assertEqual(sum(r['equipment']['quality_counts']['green']['sold'] for r in queue),12)
        self.assertEqual(sum(r['production']['grain']['outputs']['grain'] for r in queue),78)
        self.assertEqual(sum(len(r['equipment']['added_ids']) for r in queue),12)
        self.assertEqual(sum(r['duration']['settled_ms'] for r in queue),12*61000)
        self.assertEqual(summary['first_revision'],originals[0]['first_revision'])
        self.assertEqual(summary['sequence'],originals[7]['sequence'])

    def test_hundreds_of_auto_sold_salvaged_instances_quality_survives_deletion(self):
        from src.systems.equipment import items
        for mode in ('SELL','SALVAGE'):
            with self.subTest(mode=mode):
                state=self.idle(); automation=thaw_json(state.domains['automation']); automation['equipment']['mode']=mode
                state=replace(state,domains={**state.domains,'automation':automation}); state=reports.begin(state,121000)
                expected={}; ids=[]
                for n in range(360):
                    definition=('basic_left','thorn_king_blade','red_copper_mine_equipment_11')[n%3]
                    # The policy result is fixed by the fixture, real processing/Inventory still run.
                    state,identity=equip.acquire(state,self.registry,definition,'offline-fixture'); ids.append(identity)
                    quality=items.definition(self.registry,definition).quality; expected[quality]=expected.get(quality,0)+1
                with patch.object(items,'evaluate',new=lambda *args:mode),patch.object(equip.sect,'capacity_source',new=lambda *args:{'effective':10**9}):
                    for _ in range(23): state=equip.automate(state,self.registry)
                self.assertFalse(set(ids)&set(state.domains['equipment']['instances']))
                counts=reports.active(state)['equipment']['quality_counts']
                for quality,n in expected.items():
                    self.assertEqual(counts[quality]['gained'],n); self.assertEqual(counts[quality]['removed'],n)
                    self.assertEqual(counts[quality]['sold' if mode=='SELL' else 'salvaged'],n)
                candidate,result=self.f.app.engine.core.advance(state,max_events=1,now_ms=121000)
                end,r=reports.finish(candidate,result,self.registry); reports.validate(end)
                self.assertEqual(r['equipment']['quality_counts'],thaw_json(counts))
                self.assertEqual(len(r['equipment']['removed_ids']),360)
                self.assertLess(len(json.dumps(end.to_dict()['domains'][reports.DOMAIN])),120000)
                self.assertNotIn('stats',json.dumps(r))

    def test_failed_commit_rolls_back_report_and_original_world(self):
        self.seed(); self.clock.advance(120000)
        with SQLiteSave(self.path,allowed_root=self.root) as store:
            app=ManagementApplication(store,self.registry,self.clock); state=app.query(self.state.save_id); q=self.request(state,4096)
            with patch.object(store,'_insert_receipt',side_effect=RuntimeError('fixture failure')):
                with self.assertRaises(RuntimeError): app.settle(q)
            self.assertEqual(app.query(state.save_id),state); self.assertIsNone(store.receipt(q.save_id,q.generation,q.request_id))
            receipt=app.settle(q); self.assertEqual(app.settle(q),receipt)

    def test_legacy_final_state_all_original_fields_and_event_order_identical(self):
        for target in (1000,61000,121000):
            legacy,old_events,_=self.f.drain(self.state,target,legacy=True)
            actual,new_events,_=self.drain(self.state,target)
            self.f.assert_same(legacy,actual); self.assertEqual(old_events,new_events)

    def test_production_recurring_counts_not_overwritten(self):
        from src.systems.economy import policy
        state=self.idle()
        building=next(k for k,row in state.domains['sect']['buildings'].items() if row['definition_id']=='garden')
        state=self.f.app.start_candidate(state,building,'grain')
        automation=policy.set_production(state.domains['automation'],self.registry,building,{'enabled':True,'recipe_id':'grain','target':100,'reserves':{},'max_consumption':100})
        state=self.f.app.engine.wake(replace(state,domains={**state.domains,'automation':automation}))
        end,_,_=self.drain(state,181000,batch=1)
        r=end.domains[reports.DOMAIN]['unread'][0]; row=r['production']['grain']
        self.assertGreater(row['completed_count'],1)
        self.assertEqual(row['outputs']['grain'],end.domains['inventory']['holdings'].get('grain',0)-state.domains['inventory']['holdings'].get('grain',0))

    def test_forged_ack_and_pending_fingerprint_rejected(self):
        partial,result=self.f.app.engine.advance(self.state,max_events=1,now_ms=121000)
        data=thaw_json(partial.domains[reports.DOMAIN]); data['active']['combat']['wins']+=1
        forged=replace(partial,domains={**partial.domains,reports.DOMAIN:data})
        with self.assertRaises(ConflictError): self.f.app.engine.advance(forged,max_events=2,continuation=result.continuation)
        end,_,_=self.drain(self.idle(),121000)
        with self.assertRaises(ValidationError): reports.acknowledge(end,f'{end.save_id}:2:r:0')
        with self.assertRaises(ConflictError): reports.acknowledge(end,f'{end.save_id}:1:r:999999')

    def test_real_recruitment_and_due_commerce_results_do_not_auto_claim(self):
        from src.systems.sect import management
        state=self.idle(); self.seed(state)
        with SQLiteSave(self.path,allowed_root=self.root) as store:
            app=ManagementApplication(store,self.registry,self.clock); state=app.query(state.save_id)
            inventory=thaw_json(state.domains['inventory']); inventory['holdings'].update(coins=100000,grain=1000)
            part=thaw_json(state.domains['sect_management'])
            from src.systems.sect import commerce
            part.setdefault('commerce',commerce.initial())
            # Only a fixture ledger; real settlement/projection must leave escrow intact.
            part['commerce']['bids']['0:thorn_king_core']={'resource_id':'thorn_king_core','cycle':0,'bid':100,'npc_bid':90,'end_ms':70000}
            part['commerce']['consignments']['consign:1']={'resource_id':'thorn_king_core','reserve':100,'npc_bid':90,'end_ms':70000}
            part['commerce']['sequence']=1
            state=replace(state,domains={**state.domains,'inventory':inventory,'sect_management':part})
            gid=next(iter(state.domains['disciples']['groups']))
            # Recruitment is scheduled by the real command in another isolated seed.
            with tempfile.TemporaryDirectory(dir=self.root) as directory:
                root=Path(directory)
                with SQLiteSave.initialize(root/'recruit.sqlite3',allowed_root=root) as second:
                    game=ManagementApplication(second,self.registry,self.clock);game.create(state);state=game.query(state.save_id)
                    game.execute(Command(state.save_id,state.generation,state.revision,str(uuid4()),'sect_recruit',{'group_id':gid,'count':1}))
                    started=game.query(state.save_id); end,_,_=self.drain(started,1000+max(120000,management.config(self.registry)['recruit_duration_ms']))
            r=end.domains[reports.DOMAIN]['unread'][0]
            self.assertEqual(r['recruitment']['completed_count'],1);self.assertEqual(r['recruitment']['after']-r['recruitment']['before'],1)
            self.assertEqual(len(r['commerce']),2);self.assertTrue(all(row['status']=='pending_claim' for row in r['commerce']))
            self.assertEqual(end.domains['sect_management']['commerce'],started.domains['sect_management']['commerce'])
            self.assertEqual(r['commerce'][0]['coins'],0)

    def test_corrupt_report_counts_and_baseline_rejected(self):
        end,_,_=self.drain(self.idle(),121000);data=thaw_json(end.domains[reports.DOMAIN]);data['unread'][0]['equipment']['quality_counts']={'green':{'gained':1,'removed':0,'sold':0,'salvaged':0}}
        with self.assertRaises(ValidationError):reports.validate(replace(end,domains={**end.domains,reports.DOMAIN:data}))
        partial,result=self.f.app.engine.advance(self.state,max_events=1,now_ms=121000)
        data=thaw_json(partial.domains[reports.DOMAIN]);del data['active']['baseline']['inventory']
        with self.assertRaises(ValidationError):reports.validate(replace(partial,domains={**partial.domains,reports.DOMAIN:data}))

    def test_existing_receipt_without_report_field_still_replays(self):
        from dataclasses import asdict
        from src.core.save.codec import StoredReceipt
        end,_,rounds=self.drain(self.idle(),61000);result=asdict(rounds[-1]);result.pop('offline_report')
        self.seed(end)
        with SQLiteSave(self.path,allowed_root=self.root) as store:
            game=ManagementApplication(store,self.registry,self.clock)
            record=StoredReceipt(end.save_id,end.generation,str(uuid4()),'0'*64,end.revision,'settlement',result)
            receipt=game.foundation._decode_receipt(record)
            self.assertIsNone(receipt.result.offline_report);self.assertEqual(receipt.result.status,'COMPLETE')

    def test_explicit_recovery_preserves_unread_reports_and_new_sequence(self):
        from src.application.recovery import RecoveryApplication
        from src.core.save.recovery import RecoveryRequest
        end,_,_=self.drain(self.idle(),121000);self.seed(end)
        with SQLiteSave(self.path,allowed_root=self.root) as store:
            game=ManagementApplication(store,self.registry,self.clock);game.foundation.checkpoint(end.save_id)
            recovery=RecoveryApplication(game.foundation,self.clock);o=recovery.inspect(end.save_id)
            q=RecoveryRequest(end.save_id,o.current_generation,o.current_fingerprint,o.source_fingerprint,str(uuid4()),'report recovery fixture')
            result=recovery.recover(q);self.assertEqual(result.status,'SUCCESS')
            state=game.query(end.save_id);self.assertEqual(state.generation,2)
            old=state.domains[reports.DOMAIN]['unread'][0];self.assertEqual(old,end.domains[reports.DOMAIN]['unread'][0])
            next_state,_,_=self.drain(state,state.time['last_settled_at_ms']+60001)
            self.assertEqual(len(next_state.domains[reports.DOMAIN]['unread']),2)
            self.assertGreater(next_state.domains[reports.DOMAIN]['unread'][1]['sequence'],old['sequence'])

    def test_combat_defeat_counted_once_and_preexisting_defeat_not_recounted(self):
        from src.systems.dungeons import progress
        dungeon=thaw_json(self.state.domains['dungeon']);dungeon['cleared_floor']=99
        dungeon=progress.set_auto(dungeon,self.registry,True,'farm',99,1)
        state=self.f.app.engine.wake(replace(self.state,domains={**self.state.domains,'dungeon':dungeon}))
        end,_,_=self.drain(state,121000,batch=1)
        report=end.domains[reports.DOMAIN]['unread'][0]
        self.assertEqual(report['combat']['losses'],1)
        self.assertEqual(end.domains['dungeon']['auto']['reason'],'DEFEATED')
        next_state,_,_=self.drain(end,182000,batch=1)
        self.assertEqual(next_state.domains[reports.DOMAIN]['unread'][-1]['combat']['losses'],0)

    def test_summary_adds_negative_items_losses_and_keeps_first_last_growth(self):
        end,_,_=self.drain(self.idle(),121000);a=thaw_json(end.domains[reports.DOMAIN]['unread'][0]);b=thaw_json(a)
        a['items']={'grain':10,'wood':-4};b['items']={'grain':-3,'wood':4}
        a['combat']['wins']=2;a['combat']['losses']=1;b['combat']['wins']=4;b['combat']['losses']=3
        a['cultivation'].update(before=1,after=20);b['cultivation'].update(before=20,after=30)
        a['combat']['floors']['thorn_path']={'before':1,'after':4};b['combat']['floors']['thorn_path']={'before':4,'after':7}
        b['duration'].update(actual_ms=80*3600000,settled_ms=72*3600000,discarded_ms=8*3600000,capped=True)
        merged=reports.merge(a,b)
        self.assertEqual(merged['items'],{'grain':7});self.assertEqual((merged['combat']['wins'],merged['combat']['losses']),(6,4))
        self.assertEqual((merged['cultivation']['before'],merged['cultivation']['after']),(1,30))
        self.assertEqual(merged['combat']['floors']['thorn_path'],{'before':1,'after':7});self.assertTrue(merged['duration']['capped'])

    def test_recovered_partial_report_is_not_completed_or_recounted(self):
        from src.application.recovery import RecoveryApplication
        from src.core.save.recovery import RecoveryRequest
        partial,_=self.f.app.engine.advance(self.state,max_events=1,now_ms=121000);self.seed(partial)
        with SQLiteSave(self.path,allowed_root=self.root) as store:
            game=ManagementApplication(store,self.registry,self.clock);game.foundation.checkpoint(partial.save_id)
            recovery=RecoveryApplication(game.foundation,self.clock);o=recovery.inspect(partial.save_id)
            q=RecoveryRequest(partial.save_id,o.current_generation,o.current_fingerprint,o.source_fingerprint,str(uuid4()),'report partial fixture')
            self.assertEqual(recovery.recover(q).status,'SUCCESS');state=game.query(partial.save_id)
            short,_,_=self.drain(state,state.time['last_settled_at_ms']+1000)
            self.assertEqual(len(short.domains[reports.DOMAIN]['unread']),0)
            full,_,_=self.drain(short,short.time['last_settled_at_ms']+60001)
            self.assertEqual(len(full.domains[reports.DOMAIN]['unread']),1)
            self.assertIsNone(full.domains[reports.DOMAIN]['active'])

    def test_reports_roundtrip_in_existing_backup_without_gameplay_write(self):
        from src.core.save.backup import BackupStore,validate_save,MAX_SAVE_BYTES
        self.seed();self.clock.advance(120000)
        with SQLiteSave(self.path,allowed_root=self.root) as store:
            game=ManagementApplication(store,self.registry,self.clock);state=game.query(self.state.save_id)
            game.settle(self.request(state,1));partial=game.query(state.save_id)
            cloud=BackupStore(self.root/'backup.sqlite3',self.root);ancestors=[]
            for index,state in enumerate((partial,self.drain(partial,121000)[0]),1):
                body={'formatVersion':1,'saveId':state.save_id,'version':index,'updatedAt':1000,'commitId':str(uuid4()),'ancestors':list(ancestors),'source':'server','state':state.to_dict()}
                validated=validate_save(body,state.save_id);game.foundation.validate_state(validated)
                self.assertEqual(validated,state);self.assertLess(len(json.dumps(body).encode()),MAX_SAVE_BYTES)
                cloud.put(state.save_id,body,index-1);ancestors.insert(0,body['commitId']);self.assertEqual(cloud.read(state.save_id)['state']['domains'][reports.DOMAIN],state.to_dict()['domains'][reports.DOMAIN])
            self.assertEqual(game.query(partial.save_id),partial)

    def test_same_settle_chunks_match_every_original_field_including_revision(self):
        for target in (1000,60000,61001,121000):
            with self.subTest(target=target):
                legacy,old_events,old_rounds=self.f.drain(self.state,target,legacy=True,batch=1)
                actual,new_events,new_rounds=self.drain(self.state,target,batch=1)
                left=legacy.to_dict();right=actual.to_dict()
                left['domains'].pop(reports.DOMAIN,None);right['domains'].pop(reports.DOMAIN,None)
                self.assertEqual(left,right)  # Only report fields excluded; revision is compared.
                self.assertEqual(old_events,new_events);self.assertEqual(old_rounds,len(new_rounds))

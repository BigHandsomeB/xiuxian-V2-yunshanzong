"""Global Pause/Resume plus readonly framework projections on the existing Save."""
from dataclasses import replace,asdict
from src.application.cultivation import CultivationApplication
from src.application.danding import envelope,SliceRequestError
from src.application.memory import Command,Receipt
from src.core.save.codec import StoredReceipt
from src.core.state.envelope import freeze_json,thaw_json
from src.core.time import world
from src.core.validation import ValidationError,ConflictError
from src.systems.sect import rules,buildings
from src.data.registry import DefinitionKey
WorldPaused=world.WorldPaused
WORLD_COMMANDS=('world_pause','world_resume')
class WorldApplication(CultivationApplication):
    def view(self,save_id):
        return self.project_world(self.query(save_id))
    def project_world(self,state):
        v=thaw_json(freeze_json({**self.project_view(state),'combat':self.project_combat(state),'cultivation':self.project_cultivation(state)}))
        is_paused=world.paused(state.time)
        v['world']={'paused':is_paused,'status':'PAUSED' if is_paused else 'RUNNING','can_pause':not is_paused and state.time['pending'] is None,'can_resume':is_paused,'message':'世界已暂停：战斗与生产不推进；买卖、升级、打造等操作可用' if is_paused else '世界运行中'}
        for key,row in v['buildings'].items():
            row['upgrade_available']=False
            try:
                q=thaw_json(rules.quote_upgrade(state.domains['sect'],self.registry,key))
                row['upgrade_requirements']=[{'resource_id':r,'name':self.registry.lookup(DefinitionKey('resources',r)).display_name,'quantity':n,'current':state.domains['inventory']['holdings'].get(r,0)} for r,n in q['cost'].items()]
                row['next_level']=q['target_level'];row['construction_seconds']=q['construction_work_seconds']
                from src.data.economy.sect_rules import settings
                cfg=settings(self.registry);opened=bool(cfg and row['definition_id'] in cfg['building_upgrade']['materials'])
                row['upgrade_opened']=opened;row['upgrade_instant']=opened
                row['upgrade_available']=opened and state.time['pending'] is None and all(state.domains['inventory']['holdings'].get(r,0)>=n for r,n in q['cost'].items())
            except ValidationError:row['upgrade_requirements']=[]
        if is_paused:
            v['combat']['available_commands']=[]
            from src.data.economy.sect_rules import settings
            if not settings(self.registry):
                for r in v['alchemy']['recipes']:r['can_start']=False;r['blocking_reasons']=['WORLD_PAUSED',*r['blocking_reasons']]
                v['work']['can_assign']=v['work']['can_unassign']=False
        return freeze_json(v)
    def combat_view(self,save_id):return self.view(save_id)['combat']
    def act(self,save_id,body):
        envelope(save_id,body,'command');c=body['command']
        if type(c) is not dict or set(c)!={'name','version','payload'} or type(c['version']) is not int or type(c['payload']) is not dict:raise SliceRequestError('invalid command')
        if c['name'] not in WORLD_COMMANDS:return super().act(save_id,body)
        return self.execute(Command(save_id,body['generation'],body['expected_revision'],body['request_id'],c['name'],c['payload'],c['version']))
    def execute(self,q):
        if not isinstance(q,Command):raise ValidationError('Command required')
        if q.name not in WORLD_COMMANDS:return super().execute(q)
        with self.store.transaction():
            state=self.query(q.save_id)
            if q.generation!=state.generation:raise ConflictError('generation mismatch')
            r=self.store.receipt(state.save_id,state.generation,q.request_id)
            if r:
                if r.kind!='command' or r.intent!=q.digest() or r.committed_revision>state.revision:raise ConflictError('world intent conflict')
                return self.foundation._decode_receipt(r)
            if q.expected_revision!=state.revision or state.time['pending'] is not None:raise ConflictError('请先更新状态并完成宗门进度续算')
            if q.version!=1 or q.payload:raise ValidationError('exact pause/resume intent required')
            candidate=state;settled=None
            if q.name=='world_pause' and not world.paused(state.time):
                candidate,result=self.engine.advance(state,max_events=32,now_ms=self.clock.now_ms())
                if result.status!='COMPLETE':raise ConflictError('请先完成宗门进度续算，再暂停世界')
                candidate=replace(candidate,time=world.pause(candidate.time),revision=state.revision+1)
                from src.application import offline_reports as reports
                candidate=reports.observe_pause(candidate);settled=asdict(result)
            elif q.name=='world_resume' and world.paused(state.time):
                candidate=replace(state,time=world.resume(state.time,self.clock.now_ms()),revision=state.revision+1)
            self.foundation.validate_state(candidate)
            receipt=Receipt(q.request_id,candidate.revision,{'operation':q.name,'world_paused':world.paused(candidate.time),'settlement':settled})
            self.store.commit(state,candidate,StoredReceipt(state.save_id,state.generation,q.request_id,q.digest(),candidate.revision,'command',thaw_json(receipt.result)))
        return receipt

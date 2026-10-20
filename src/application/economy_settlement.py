"""Bounded Application dispatch on the unchanged Core event/cursor/continuation contract."""
from dataclasses import replace,asdict
from time import monotonic
from src.core.time.engine import SettlementEngine
from src.core.time.model import Continuation, plan_window
from src.core.time.config import SETTLEMENT_BUDGET_MS, CATCHUP_BUDGET_MS, OFFLINE_COMBAT_RECENT_MS
from src.core.state.envelope import thaw_json,StateEnvelope
from src.core.state.draft import batch_scope
from src.core.time.world import require_running
from src.core.validation import ValidationError,ConflictError,integer
from src.application.work import WorkSettlement
from src.application import sect
from src.systems.resources import jobs
from src.systems.disciples import work
from src.systems.inventory import operations,holdings
from src.systems.economy import policy
from src.application import recipe_staffing
from src.application import equipment as equip
from src.application import offline_reports as reports

class EconomySettlement:
    def __init__(self,app):
        self.app=app;self.registry=app.registry;self.work=WorkSettlement(self.registry);self.budget_ms=SETTLEMENT_BUDGET_MS;self.catchup_budget_ms=CATCHUP_BUDGET_MS
        self.core=SettlementEngine({'production':jobs.simulation(self.registry),'automation':policy.simulation(self.registry)})
    def validate_state(self,state):
        self.work.validate_state(state);self.core.validate_state(state);reports.validate(state)
        policies=list(state.domains['automation']['production'].items())
        policies.extend((b,row) for b,q in state.domains['automation'].get('recipe_production',{}).items() for row in q['recipes'].values())
        for b,row in policies:
            building=state.domains['sect']['buildings'].get(b)
            if building is None or jobs.definition(self.registry,row['recipe_id']).building_kind!=building['definition_id']:raise ValidationError('automation target/recipe mismatch')
        return state
    def wake(self,s):
        policies=[*s.domains['automation']['production'].values(),*(row for q in s.domains['automation'].get('recipe_production',{}).values() for row in q['recipes'].values())]
        if not any(r['enabled'] for r in policies):due=None
        else:due=min((j['due_ms']+1 for j in s.domains['production']['jobs'].values() if j['status']=='WORKING'),default=None)
        old=s.domains['automation']['wake']
        if (due is None and old is None) or (old and old['due_ms']==due):return s
        p=thaw_json(s.domains['automation']);counter=s.identity['event_counter']
        if due is None:p['wake']=None
        else:
            counter+=1;p['wake']={'event_id':f'{s.save_id}:{s.generation}:e:{counter}','due_ms':due}
        return replace(s,identity={**s.identity,'event_counter':counter},domains={**s.domains,'automation':p})
    def deliver(self,s):
        rows=s.domains['production']['jobs'];active={j['job_id'] for j in rows.values() if j['status']=='WORKING'}
        if not any(j['status']=='OUTPUT_READY' for j in rows.values()) and set(s.domains['disciples']['commitments'])<=active:return s
        p=thaw_json(s.domains['production']);stock=s.domains['inventory'];capacity=sect.capacity_source(s,self.registry)['effective']
        for job in sorted(p['jobs'].values(),key=lambda j:(j['due_ms'],j['event_id'])):
            if job['status']!='OUTPUT_READY':continue
            amounts=jobs.outputs(job,self.registry);needed=sum(n for k,n in amounts.items() if holdings.definition(self.registry,k).warehouse_counted)
            d=jobs.definition(self.registry,job['recipe_id']);quantity=max(1,job['yield_milli']//1000) if d.equipment_output_id else 0
            if needed and holdings.stock_size(stock,self.registry)+needed>capacity:continue
            if quantity:
                for _ in range(quantity):s,_=equip.acquire(s,self.registry,d.equipment_output_id,job['job_id'])
            stock,result=operations.grant(stock,self.registry,amounts,capacity=capacity)
            if any(result['discarded'].values()):raise ValidationError('cannot discard production')
            job['status']='COMPLETE'
            s=reports.observe_production(s,job,amounts,quantity)
        active={j['job_id'] for j in p['jobs'].values() if j['status']=='WORKING'}
        return replace(s,domains={**s.domains,'production':p,'inventory':stock,'disciples':work.release_finished(s.domains['disciples'],self.registry,active)})
    def dispatch(self,s):
        for b,row in sorted(s.domains['automation']['production'].items()):
            if not row['enabled'] or b in s.domains['automation'].get('recipe_production',{}):continue
            j=s.domains['production']['jobs'].get(b)
            if j and j['status']!='COMPLETE':continue
            d=jobs.definition(self.registry,row['recipe_id']);count=self.app.output_stock(s,d)
            if count>=row['target']:continue
            try:
                s=self.app.start_candidate(s,b,d.machine_id,policy_row=row)
                j=s.domains['production']['jobs'][b]
                p=policy.record(s.domains['automation'],'START',j['job_id'],d.display_name+'已自动开始')
                s=replace(s,domains={**s.domains,'automation':p})
            except (ValidationError,ConflictError):continue
        return self.wake(recipe_staffing.dispatch(self.app,s))
    def compress(self,state,now_ms):
        return state
    def advance(self,state,*,max_events,now_ms=None,continuation=None):
        integer(max_events,'max_events',1)
        started=monotonic()
        accepted=state.time["pending"]["accepted_ms"] if state.time["pending"] else plan_window(state.time,now_ms).accepted_ms
        budget_ms=self.catchup_budget_ms if accepted>OFFLINE_COMBAT_RECENT_MS else self.budget_ms
        require_running(state.time);self.validate_state(state)
        # Validate caller continuation BEFORE adding new Domain work.
        if state.time['pending']:
            self.core._pending(state,continuation)
        elif continuation is not None:raise ValidationError('unexpected continuation')
        # One detached full snapshot. Branches preserve pure-handler rollback semantics.
        detached={name:getattr(state,name) for name in StateEnvelope.__dataclass_fields__}
        with batch_scope():
            working=reports.begin(StateEnvelope.from_dict(detached),now_ms,self.registry) if not state.time['pending'] else StateEnvelope.from_dict(detached)
            prepared=self.app.prepare_economy_state(working) if not working.time['pending'] else working
            last_equipment=None
            def automate(candidate):
                nonlocal last_equipment
                part=candidate.domains.get('equipment')
                if part is last_equipment:return candidate
                updated=equip.automate(candidate,self.registry)
                # Cache only a no-op scan; batches of >16 pending instances still drain.
                last_equipment=part if updated.domains.get('equipment') is part else None
                return updated
            s=self.wake(self.dispatch(automate(self.deliver(prepared))));processed=[];result=None
            for _ in range(max_events):
                s=self.compress(s,now_ms)
                candidate,result=self.core._batch_step(s,now_ms=None if s.time['pending'] else now_ms)
                processed.extend(result.processed_events)
                s=self.wake(self.dispatch(automate(self.deliver(candidate))))
                if result.status=='COMPLETE' or len(processed)>=max_events or monotonic()-started>=budget_ms/1000:break
            s=replace(s,revision=state.revision+1 if s!=state else state.revision)
            if s.time['pending']:
                t=thaw_json(s.time);t['pending']['revision']=s.revision;s=replace(s,time=t)
            s,report=reports.finish(s,result,self.registry)
        # Draft snapshots cannot escape to persistence; freeze the final full envelope once.
        s=replace(s)
        report=thaw_json(report) if report is not None else None
        self.validate_state(s)
        from src.application.cultivation import partition
        from src.systems.cultivation import leveling
        c=leveling.config(self.registry)
        gains={'xp_gained':max(0,leveling.xp(partition(s),c)-leveling.xp(partition(state),c)),'levels_gained':leveling.level(partition(s),c)-leveling.level(partition(state),c)} if c else {}
        result=replace(result,from_sim_ms=state.time['sim_time_ms'],processed_events=tuple(processed),continuation=Continuation.for_state(s) if s.time['pending'] else None,offline_report=report)
        if gains:
            from src.application.settlement import GrowthSettlementResult
            result=GrowthSettlementResult(**{**asdict(result),'continuation':result.continuation},**gains)
        return s,result

"""Bounded offline/online automatic battle over the existing event settlement authority."""
from dataclasses import replace
from src.application.item_retirement import RetiredSettlement
from src.core.time.engine import SettlementEngine
from src.core.state.envelope import thaw_json
from src.core.validation import ValidationError
from src.core.time.config import OFFLINE_COMBAT_RECENT_MS
from src.core.time.model import plan_window
from src.systems.resources import jobs
from src.systems.economy import policy
from src.systems.dungeons import progress
from src.systems.cultivation import growth
from src.systems.combat import battle
from src.application import offline_reports as reports
from src.systems.combat.equipment_effects import interval

class DungeonSettlement(RetiredSettlement):
    def __init__(self,app):
        super().__init__(app)
        self.recent_ms=OFFLINE_COMBAT_RECENT_MS;self.result_path=True;self._compressed=None
        self.core=SettlementEngine({'production':jobs.simulation(self.registry),'automation':policy.simulation(self.registry),'dungeon':progress.simulation(self.registry)})
    def compress(self,s,now_ms):
        self._compressed=None
        if not self.result_path:return s
        target=s.time['pending']['target_sim_ms'] if s.time['pending'] else plan_window(s.time,now_ms).target_sim_ms
        a=s.domains['dungeon']['auto'];w=a['wake']
        if not a['enabled'] or not w or 'interval_ms' not in w or w['due_ms']>target-self.recent_ms:return s
        events=self.core._events(s,{k:s.domains[k] for k in self.core._domains})
        if not events or events[0].domain!='dungeon':return s
        part=s.domains.get('combat',battle.initial());b=part['battle'];counter=s.identity['instance_counter']
        if b and b['status'] not in ('ACTIVE','SETTLED','ABANDONED'):return s
        if not b or b['status'] in ('SETTLED','ABANDONED'):
            p=s.domains['dungeon']
            if a['mode']=='push' and progress.cleared(p,progress.selected(p))==len(progress.definition(self.registry,progress.selected(p)).encounters):return s
            eid=progress.next_encounter(p,self.registry) if a['mode']=='push' else progress.definition(self.registry,progress.selected(p)).encounters[a.get('next_floor',a['floor'])-1]
            counter+=1
            part=battle.start(part,self.registry,s.save_id,f'{s.save_id}:{s.generation}:i:{counter}',eid,player_snapshot=self.app.player_projection(s),growth_snapshot=s.domains.get('cultivation',growth.initial(s.save_id)),equipment_sources=self.app.combat_equipment(s),artifact_snapshot=self.app.combat_artifact(s),equipment_snapshot=self.app.combat_equipment_snapshot(s))
        if progress.floor_of(self.registry,part['battle']['encounter_id']) is None:return s
        outcome,before,rounds=battle.result_only(part,self.registry,s.save_id)
        # After a victory, the scheduled first tick may still carry the prior
        # fight's interval, including the following tick already scheduled by tick().
        # Later rounds use this fight's immutable snapshot.
        attack_interval=interval(part['battle'].get('player_snapshot') or self.app.player_projection(s))
        skipped=rounds-1
        due=w['due_ms']+(w.get('interval_ms',progress.INTERVAL_MS)+(skipped-1)*attack_interval if skipped else 0)
        # Never cross another domain boundary, including equal-time production/meal events.
        if due>target-self.recent_ms or any(e.domain!='dungeon' and e.due_sim_ms<=due for e in events):return s
        p=thaw_json(s.domains['dungeon']);a=p['auto'];n=s.identity['event_counter']
        if skipped:
            a['wake']={**w,'due_ms':due,'event_id':w['next_event_id'] if skipped==1 else f'{s.save_id}:{s.generation}:e:{n+skipped-1}', 'next_event_id':f'{s.save_id}:{s.generation}:e:{n+skipped}'}
            a['wake']['interval_ms']=attack_interval
            a['steps']+=skipped
        t=thaw_json(s.time)
        if t['pending']:t['pending']['processed_total']+=skipped
        self._compressed=outcome
        return replace(s,time=t,identity={**s.identity,'instance_counter':counter,'event_counter':n+skipped},domains={**s.domains,'combat':before,'dungeon':p})
    def wake(self,s):
        s=super().wake(s);a=s.domains['dungeon']['auto']
        if not a['enabled'] or (a['wake'] and a['wake']['next_event_id'] is not None):return s
        p=thaw_json(s.domains['dungeon']);a=p['auto'];counter=s.identity['event_counter']
        if not a['enabled']:return s
        if a['wake'] is None:
            delay=interval(self.app.player_projection(s))
            counter+=2;a['wake']={'event_id':f'{s.save_id}:{s.generation}:e:{counter-1}','next_event_id':f'{s.save_id}:{s.generation}:e:{counter}','due_ms':s.time['sim_time_ms']+delay,'interval_ms':delay}
        elif a['wake']['next_event_id'] is None:
            b=s.domains.get('combat',{}).get('battle')
            snapshot=b.get('player_snapshot') if b and b['status']=='ACTIVE' else None
            a['wake']['interval_ms']=interval(snapshot or self.app.player_projection(s))
            counter+=1;a['wake']['next_event_id']=f'{s.save_id}:{s.generation}:e:{counter}'
        return replace(s,identity={**s.identity,'event_counter':counter},domains={**s.domains,'dungeon':p})
    def stop(self,s,reason):
        p=thaw_json(s.domains['dungeon']);p['auto'].update(enabled=False,wake=None,tick_ready=False,reason=reason,stop_sim_ms=s.time['sim_time_ms'])
        return reports.observe_stop(replace(s,domains={**s.domains,'dungeon':p}),reason)
    def dispatch(self,s):
        s=super().dispatch(s);p=thaw_json(s.domains['dungeon']);a=p['auto']
        if not a['enabled'] or not a['tick_ready']:return s
        a['tick_ready']=False;a['steps']+=1;s=replace(s,domains={**s.domains,'dungeon':p})
        b=s.domains.get('combat',{}).get('battle')
        if b and b['status'] in ('ACTIVE','PLAYER_WIN') and progress.floor_of(self.registry,b['encounter_id']) is None:return self.stop(s,'LEGACY_BATTLE')
        if b and b['status']=='PLAYER_LOSE':return self.stop(s,'DEFEATED')
        if not b or b['status'] in ('SETTLED','ABANDONED'):
            if a['mode']=='push' and progress.cleared(p,progress.selected(p))==len(progress.definition(self.registry,progress.selected(p)).encounters):return self.stop(s,'COMPLETED')
            eid=progress.next_encounter(p,self.registry) if a['mode']=='push' else progress.definition(self.registry,progress.selected(p)).encounters[a.get('next_floor',a['floor'])-1]
            counter=s.identity['instance_counter']+1;part=battle.start(s.domains.get('combat',battle.initial()),self.registry,s.save_id,f'{s.save_id}:{s.generation}:i:{counter}',eid,player_snapshot=self.app.player_projection(s),growth_snapshot=s.domains.get('cultivation',growth.initial(s.save_id)),equipment_sources=self.app.combat_equipment(s),artifact_snapshot=self.app.combat_artifact(s),equipment_snapshot=self.app.combat_equipment_snapshot(s))
            s=replace(s,identity={**s.identity,'instance_counter':counter},domains={**s.domains,'combat':part});b=part['battle']
        if b['status']=='ACTIVE':
            part=self._compressed or battle.attack(s.domains['combat'],self.registry,s.save_id,b['battle_id']);part=thaw_json(part);part['battle']['visual_events_online']=not s.time['pending'] or s.time['pending']['accepted_ms']<=self.recent_ms;self._compressed=None;s=replace(s,domains={**s.domains,'combat':part});b=part['battle']
            if b['status']=='PLAYER_WIN':s=reports.observe_combat(s,'wins')
        if b['status']=='PLAYER_LOSE':
            s=reports.observe_combat(s,'losses')
            return self.stop(s,'DEFEATED')
        if b['status']=='PLAYER_WIN':
            # Preflight only storage errors; unexpected application errors roll back the
            # existing settlement transaction rather than committing a partial reward.
            try:
                s=self.app.settle_combat_candidate(s)
            except ValidationError as exc:
                if str(exc)!='仓库空间不足，战利品等待领取':raise
                return self.stop(s,'STORAGE_FULL')
            combat=thaw_json(s.domains['combat']);combat['battle']['latest_events']=[*b['latest_events'],battle.fact('reward_settled')][-20:]
            p=thaw_json(s.domains['dungeon']);p['auto']['wins']+=1
            auto=p['auto']
            if auto['mode']=='farm':
                start=auto['floor'];count=auto.get('floor_count',1);finished=progress.floor_of(self.registry,b['encounter_id'])
                auto['next_floor']=finished+1 if start<=finished<start+count-1 else start
            s=replace(s,domains={**s.domains,'combat':combat,'dungeon':p})
            if p['auto']['mode']=='push' and progress.cleared(p,progress.selected(p))==len(progress.definition(self.registry,progress.selected(p)).encounters):return self.stop(s,'COMPLETED')
        return self.wake(s)

# Frozen test-only pre-optimization reference; not a runtime fallback.
"""Bounded offline/online automatic battle over the existing event settlement authority."""
from dataclasses import replace
from src.application.item_retirement import RetiredSettlement
from src.core.time.engine import SettlementEngine
from src.core.state.envelope import thaw_json
from src.core.validation import ValidationError
from src.systems.resources import jobs
from src.systems.economy import policy
from src.systems.dungeons import progress
from src.systems.combat import battle
from src.application import offline_reports as reports
from src.systems.combat.equipment_effects import interval

class DungeonSettlement(RetiredSettlement):
    def __init__(self,app):
        super().__init__(app)
        self.core=SettlementEngine({'production':jobs.simulation(self.registry),'automation':policy.simulation(self.registry),'dungeon':progress.simulation(self.registry)})
    def wake(self,s):
        s=super().wake(s);p=thaw_json(s.domains['dungeon']);a=p['auto'];counter=s.identity['event_counter']
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
        p=thaw_json(s.domains['dungeon']);p['auto'].update(enabled=False,wake=None,tick_ready=False,reason=reason)
        return replace(s,domains={**s.domains,'dungeon':p})
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
            counter=s.identity['instance_counter']+1;part=battle.start(s.domains.get('combat',battle.initial()),self.registry,s.save_id,f'{s.save_id}:{s.generation}:i:{counter}',eid,player_snapshot=self.app.player_projection(s))
            s=replace(s,identity={**s.identity,'instance_counter':counter},domains={**s.domains,'combat':part});b=part['battle']
        if b['status']=='ACTIVE':
            part=battle.attack(s.domains['combat'],self.registry,s.save_id,b['battle_id']);s=replace(s,domains={**s.domains,'combat':part});b=part['battle']
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

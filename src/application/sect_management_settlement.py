"""Compose bounded recruitment and supply events with existing dungeon settlement."""
from dataclasses import replace
from src.application.dungeon_settlement import DungeonSettlement
from src.core.time.engine import SettlementEngine
from src.core.state.envelope import thaw_json
from src.core.validation import ValidationError
from src.systems.sect import management
from src.systems.resources import jobs
from src.systems.economy import policy
from src.systems.dungeons import progress
from src.systems.inventory import operations
from src.application import offline_reports as reports
from src.application import market_restock
from src.core.time.world import paused

class ManagementSettlement(DungeonSettlement):
    def __init__(self,app):
        super().__init__(app)
        self.core=SettlementEngine({'production':jobs.simulation(self.registry),'automation':policy.simulation(self.registry),'dungeon':progress.simulation(self.registry),'sect_management':management.simulation(self.registry)})
    def validate_state(self,state):
        super().validate_state(state);p=state.domains['sect_management'];management.validate(p,self.registry)
        r=p['recruit']
        if r and (r['group_id'] not in state.domains['disciples']['groups'] or r['ready']):raise ValidationError('persisted recruitment ownership invalid')
        if p['supply']['tick_ready']:raise ValidationError('persisted meal event must be dispatched')
        wake=p.get('restock',{}).get('wake')
        if wake and wake['next_event_id'] is None:raise ValidationError('persisted restock successor required')
        if r:
            parts=r['order_id'].split(':')
            try:
                generation,counter=int(parts[1]),int(parts[3])
                valid=len(parts)==4 and parts[0]==state.save_id and parts[2]=='i' and str(generation)==parts[1] and str(counter)==parts[3] and 1<=generation<=state.generation and 1<=counter<=state.identity['instance_counter']
            except (ValueError,IndexError):valid=False
            if not valid:raise ValidationError('recruit order namespace invalid')
            used=set(state.domains['sect']['buildings'])|set(state.domains['disciples']['groups'])|set(state.domains.get('equipment',{}).get('instances',{}))|{j['job_id'] for j in state.domains['production']['jobs'].values()}
            b=state.domains.get('combat',{}).get('battle')
            if b:used.add(b['battle_id'])
            if r['order_id'] in used:raise ValidationError('recruitment identity collision')
        return state
    def meals(self,s):
        supply=s.domains['sect_management']['supply']
        if not supply['enabled'] or supply['effect_until_ms']>s.time['sim_time_ms']:return s
        p=thaw_json(s.domains['sect_management']);supply=p['supply'];cfg=management.config(self.registry)
        amount=management.housing(s,self.registry)['people']*cfg['meal_food_per_person'];stock=s.domains['inventory']['holdings'].get('food',0)
        if not amount or stock-amount<supply['reserve']:return s
        inventory,_=operations.consume(s.domains['inventory'],self.registry,{'food':amount})
        supply['effect_until_ms']=s.time['sim_time_ms']+cfg['meal_period_ms'];p['log']=(p['log']+[{'operation':'MEAL','count':amount,'sim_ms':s.time['sim_time_ms']}])[-management.config(self.registry)['log_limit']:]
        return replace(s,domains={**s.domains,'inventory':inventory,'sect_management':p})
    def wake(self,s):
        s=super().wake(s)
        restock=market_restock.policy(s);old=restock['wake']
        active=bool(restock['targets']) and not paused(s.time) and market_restock.workforce(s,self.registry)>0
        due=(s.time['sim_time_ms']//s.time['day_length_ms']+1)*s.time['day_length_ms'] if active else None
        if (old is not None and (old['due_ms']!=due or old['next_event_id'] is None)) or (old is None and due is not None):
            p=thaw_json(s.domains['sect_management']);counter=s.identity['event_counter']
            if due is None:p['restock']['wake']=None
            else:
                counter+=2;p['restock']['wake']={'event_id':f'{s.save_id}:{s.generation}:e:{counter-1}','next_event_id':f'{s.save_id}:{s.generation}:e:{counter}','due_ms':due}
            s=replace(s,identity={**s.identity,'event_counter':counter},domains={**s.domains,'sect_management':p})
        supply=s.domains['sect_management']['supply']
        if not supply['enabled'] or supply['wake'] is not None or supply['effect_until_ms']<=s.time['sim_time_ms']:return s
        p=thaw_json(s.domains['sect_management']);supply=p['supply']
        if supply['enabled'] and supply['wake'] is None and supply['effect_until_ms']>s.time['sim_time_ms']:
            n=s.identity['event_counter']+1;supply['wake']={'event_id':f'{s.save_id}:{s.generation}:e:{n}','due_ms':supply['effect_until_ms']}
            s=replace(s,identity={**s.identity,'event_counter':n},domains={**s.domains,'sect_management':p})
        return s
    def dispatch(self,s):
        part=s.domains['sect_management'];r=part['recruit']
        if not (r and r['ready']) and not part['supply']['tick_ready']:return super().dispatch(market_restock.dispatch(self.meals(s),self.registry))
        p=thaw_json(s.domains['sect_management']);r=p['recruit']
        if r and r['ready']:
            people=thaw_json(s.domains['disciples']);people['groups'][r['group_id']]['count']+=r['count'];p['recruit']=None
            p['log']=(p['log']+[{'operation':'RECRUIT','count':r['count'],'sim_ms':s.time['sim_time_ms']}])[-management.config(self.registry)['log_limit']:]
            s=reports.observe_recruitment(replace(s,domains={**s.domains,'disciples':people}))
        p['supply']['tick_ready']=False;s=replace(s,domains={**s.domains,'sect_management':p})
        s=self.meals(s)
        return super().dispatch(market_restock.dispatch(s,self.registry))

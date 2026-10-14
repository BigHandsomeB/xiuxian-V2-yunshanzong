"""Dungeon orchestration over the existing combat, reward and persistent command lane."""
from dataclasses import replace
from src.application.item_retirement import RetiredEconomyApplication
from src.application.equipment import EconomyPersistence
from src.application.work import references
from src.application import sect
from src.systems.resources import jobs
from src.systems.disciples import work
from src.systems.economy import policy
from src.systems.dungeons import progress
from src.systems.combat import battle
from src.core.state.envelope import freeze_json,thaw_json
from src.core.validation import ValidationError,ConflictError
from src.application.dungeon_settlement import DungeonSettlement
from src.application.danding import envelope,SliceRequestError
from src.application.memory import Command,Receipt
from src.core.save.codec import StoredReceipt
from src.core.time.world import require_running
from src.core.time.model import plan_window
from src.data.dungeons import loot,expeditions
from src.application import equipment as equip
from src.systems.inventory import holdings
from src.systems.combat.equipment_effects import interval

def partition(state):return state.domains.get('dungeon',progress.initial())
class DungeonPersistence(EconomyPersistence):
    def _validate(self,state):
        s=super()._validate(state);progress.validate(partition(s),self.registry)
        a=partition(s)['auto'];wake=a['wake']
        if a['enabled'] and (wake is None or wake['next_event_id'] is None or a['tick_ready']):raise ValidationError('persisted auto schedule incomplete')
        if wake:
            occupied={j['event_id'] for j in s.domains['production']['jobs'].values()}
            if s.domains['automation']['wake']:occupied.add(s.domains['automation']['wake']['event_id'])
            for eid in (wake['event_id'],wake['next_event_id']):
                parts=eid.split(':')
                try:g,n=int(parts[1]),int(parts[3])
                except (ValueError,IndexError) as exc:raise ValidationError('invalid auto event identity') from exc
                if len(parts)!=4 or parts[0]!=s.save_id or parts[2]!='e' or str(g)!=parts[1] or str(n)!=parts[3] or not 1<=g<=s.generation or not 1<=n<=s.identity['event_counter'] or eid in occupied:raise ValidationError('auto event outside allocated namespace')
                occupied.add(eid)
        b=s.domains.get('combat',{}).get('battle')
        if b:
            did=expeditions.owner(self.registry,b['encounter_id']);f=progress.floor_of(self.registry,b['encounter_id'])
            if b['status'] in ('ACTIVE','PLAYER_WIN') and (did or 'thorn_path')!=progress.selected(partition(s)):raise ValidationError('active battle must belong to selected dungeon')
            if f is not None:
                progress.require_unlocked(partition(s),self.registry,b['encounter_id'])
                if b['status']=='SETTLED' and f>progress.cleared(partition(s),expeditions.owner(self.registry,b['encounter_id'])):raise ValidationError('settled floor missing progress')
        return s
from src.application.sect_economy import SectEconomyFeatures
class DungeonApplication(SectEconomyFeatures,RetiredEconomyApplication):
    def _settlement_engine(self):return DungeonSettlement(self)
    def _application(self,specs):
        validators={**sect.validators(self.registry),'production':lambda p:jobs.validate(p,self.registry),'disciples':lambda p:work.validate(p,self.registry),'automation':lambda p:policy.validate(p,self.registry)}
        return DungeonPersistence(self.store,self.registry,specs,references=lambda s:references(s,self.registry),validators=validators,settlement_engine=self.engine,clock=self.clock)
    def create(self,state):return super().create(replace(state,domains={**state.domains,'dungeon':partition(state)}))
    def default_encounter(self,state):return progress.next_encounter(partition(state),self.registry)
    def prepare_combat_start(self,state,encounter_id):
        if encounter_id not in progress.definition(self.registry,progress.selected(partition(state))).encounters:raise ConflictError('该战斗版本已退役，请刷新后进入副本')
        return progress.require_unlocked(partition(state),self.registry,encounter_id)
    def require_manual_combat(self,state):
        if partition(state)['auto']['enabled']:raise ConflictError('请先停止挂机再手动操作')
    def combat_reward_candidate(self,state,candidate):
        b=candidate.domains['combat']['battle'];p=progress.claimed(partition(state),self.registry,b)
        return replace(candidate,domains={**candidate.domains,'dungeon':p})
    def reward_amounts(self,b):
        return {**super().reward_amounts(b),**loot.plan(self.registry,b)['amounts']}
    def reward_grant(self,state,b):
        from src.systems.economy.overflow import rewards,conversion_coins
        from src.data.economy.sect_rules import settings
        amounts,converted=rewards(state.domains['automation'],state.domains['inventory']['holdings'],self.registry,self.reward_amounts(b),reserves=state.domains.get('sect_management',{}).get('material_reserves',{}))
        if converted:
            cfg=settings(self.registry);auto=thaw_json(state.domains['automation'])
            auto['overflow_log']=(auto.get('overflow_log',[])+[{'battle_id':b['battle_id'],'amounts':converted,'coins':conversion_coins(self.registry,converted)}])[-cfg['overflow_audit_limit']:]
            state=replace(state,domains={**state.domains,'automation':auto})
        return amounts,state
    def settle_combat_candidate(self,state):
        b=state.domains.get('combat',{}).get('battle')
        if not b or b['status']=='SETTLED':return super().settle_combat_candidate(state)
        drop=loot.plan(self.registry,b)
        candidate=super().settle_combat_candidate(state)
        if drop['equipment']:
            candidate,identity=equip.acquire(candidate,self.registry,drop['equipment'],b['battle_id'],roll_version=loot.equipment_roll_version(b))
            e=thaw_json(equip.equipment(candidate));e['latest_reward']={'battle_id':b['battle_id'],'instance_id':identity,'definition_id':drop['equipment']}
            candidate=replace(candidate,domains={**candidate.domains,'equipment':e})
        from src.systems.economy.overflow import rewards,conversion_coins
        from src.application import offline_reports as reports
        amounts,converted=rewards(state.domains['automation'],state.domains['inventory']['holdings'],self.registry,self.reward_amounts(b),reserves=state.domains.get('sect_management',{}).get('material_reserves',{}))
        return reports.observe_battle_reward(candidate,amounts,converted,int(bool(drop['equipment'])),conversion_coins(self.registry,converted))
    def project_combat(self,state):
        b=state.domains.get('combat',{}).get('battle');did=progress.selected(partition(state))
        # Terminal history remains saved but another selected dungeon previews its next floor.
        shown=b if b and (expeditions.owner(self.registry,b['encounter_id'])==did or b['status'] in ('ACTIVE','PLAYER_WIN')) else None
        preview=state if shown is b else replace(state,domains={**state.domains,'combat':battle.initial()})
        v=thaw_json(super().project_combat(preview));b=shown
        v['material_overflow']=next((thaw_json(r) for r in reversed(state.domains['automation'].get('overflow_log',())) if b and r['battle_id']==b['battle_id']),None)
        v['dungeon']=progress.view(partition(state),self.registry,b);v['start_encounter_id']=self.default_encounter(state)
        v['dungeons']=progress.directory(partition(state),self.registry)
        v['auto']=v['dungeon']['auto']
        from src.core.time.world import paused
        v['stop_reason']='WORLD_PAUSED' if paused(state.time) else v['auto'].get('reason') or ('DEFEATED' if b and b['status']=='PLAYER_LOSE' else None)
        v['stop_sim_ms']=state.time['sim_time_ms'] if paused(state.time) else v['auto'].get('stop_sim_ms')
        v['dungeon']['attack_interval_ms']=interval(b.get('player_snapshot',self.player_projection(state)) if b else self.player_projection(state))
        if b and b['status'] in ('PLAYER_WIN','SETTLED'):
            drop=loot.plan(self.registry,b)
            for key,n in drop['amounts'].items():
                v['reward'].append({'resource_id':key,'name':holdings.definition(self.registry,key).display_name,'quantity':n})
            if drop['equipment']:
                d=equip.items.definition(self.registry,drop['equipment']);v['reward'].append({'resource_id':d.machine_id,'name':d.display_name,'quantity':1,'asset_id':d.asset_id,'category':'equipment','quality':d.quality})
        if v['auto']['enabled']:v['available_commands']=[]
        return freeze_json(v)

    def project_economy(self,state):
        v=super().project_economy(state)
        if partition(state)['auto']['enabled']:v['needs_poll']=v['needs_settlement']=True
        return v
    def act(self,save_id,body):
        if isinstance(body,dict) and isinstance(body.get('command'),dict) and body['command'].get('name') in ('dungeon_auto','dungeon_select'):
            envelope(save_id,body,'command');c=body['command']
            if type(c) is not dict or set(c)!={'name','version','payload'} or c['version']!=1 or type(c['version']) is not int or type(c['payload']) is not dict:raise SliceRequestError('exact auto policy required')
            return self.execute(Command(save_id,body['generation'],body['expected_revision'],body['request_id'],c['name'],c['payload']))
        return super().act(save_id,body)
    def execute(self,q):
        if not isinstance(q,Command):raise ValidationError('Command required')
        if q.name not in ('dungeon_auto','dungeon_select'):
            return super().execute(q)
        with self.store.transaction():
            s=self.query(q.save_id)
            if q.generation!=s.generation:raise ConflictError('存档换代，请更新')
            r=self.store.receipt(s.save_id,s.generation,q.request_id)
            if r:
                if r.kind!='command' or r.intent!=q.digest() or r.committed_revision>s.revision:raise ConflictError('挂机请求内容不一致')
                return self.foundation._decode_receipt(r)
            require_running(s.time)
            if q.expected_revision!=s.revision or s.time['pending']:raise ConflictError('进度正在续算，请更新后操作')
            if q.version!=1:raise ValidationError('未知副本命令版本')
            if q.name=='dungeon_select':
                if set(q.payload)!={'dungeon_id'} or type(q.payload['dungeon_id']) is not str:raise ValidationError('请选择副本')
                b=s.domains.get('combat',{}).get('battle')
                if b and b['status'] in ('ACTIVE','PLAYER_WIN'):raise ConflictError('请先结束当前战斗并领取战利品')
                p=progress.choose(partition(s),self.registry,q.payload['dungeon_id'])
                candidate=replace(s,domains={**s.domains,'dungeon':p})
                if candidate!=s:candidate=replace(candidate,revision=s.revision+1)
                self.foundation.validate_state(candidate)
                receipt=Receipt(q.request_id,candidate.revision,{'operation':q.name,'combat':self.project_combat(candidate)})
                self.store.commit(s,candidate,StoredReceipt(s.save_id,s.generation,q.request_id,q.digest(),candidate.revision,'command',thaw_json(receipt.result)))
                return receipt
            if set(q.payload) not in ({'enabled','mode','floor'},{'enabled','mode','floor','floor_count'}):raise ValidationError('请选择完整挂机策略')
            p=progress.set_auto(partition(s),self.registry,**q.payload)
            b=s.domains.get('combat',{}).get('battle')
            if p['auto']['enabled'] and b and b['status'] in ('ACTIVE','PLAYER_WIN') and progress.floor_of(self.registry,b['encounter_id']) is None:raise ConflictError('请先结束原来的初遇试炼')
            if p['auto']['enabled'] and b and b['status']=='PLAYER_LOSE':
                # A user explicitly restarting auto authorizes retry, not free progress.
                ppart=battle.initial()
                candidate=replace(s,domains={**s.domains,'dungeon':p,'combat':ppart})
            else:candidate=replace(s,domains={**s.domains,'dungeon':p})
            candidate=self.engine.wake(candidate)
            if p['auto']['enabled']:
                # An old wall anchor must never grant battles from before enabling.
                p=thaw_json(candidate.domains['dungeon'])
                p['auto']['wake']['due_ms']=plan_window(s.time,self.clock.now_ms()).target_sim_ms+progress.INTERVAL_MS
                candidate=replace(candidate,domains={**candidate.domains,'dungeon':p})
            candidate=replace(candidate,revision=s.revision+1)
            self.foundation.validate_state(candidate);receipt=Receipt(q.request_id,candidate.revision,{'operation':q.name,'combat':self.project_combat(candidate)})
            self.store.commit(s,candidate,StoredReceipt(s.save_id,s.generation,q.request_id,q.digest(),candidate.revision,'command',thaw_json(receipt.result)))
        return receipt

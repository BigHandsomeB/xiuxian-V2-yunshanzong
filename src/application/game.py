"""Compose real Combat + Inventory using the existing atomic transaction/receipt pattern."""
from src.core.time.world import require_running
from src.core.time.config import OFFLINE_COMBAT_RECENT_MS
from dataclasses import replace
from src.application.danding import DandingApplication, SliceRequestError, envelope
from src.application.persistent import PersistentApplication
from src.application.memory import Command, Receipt
from src.application.work import references
from src.application import sect
from src.core.save.codec import StoredReceipt
from src.core.state.envelope import freeze_json, thaw_json
from src.core.validation import ValidationError, ConflictError, integer
from src.systems.cultivation import growth
from src.systems.combat import battle
from src.systems.inventory import operations, holdings
from src.systems.resources import jobs
from src.systems.disciples import work


def validate_combat(state,registry):
    if 'combat' not in state.domains:return state  # Old save remains valid; GET never writes.
    battle.validate(state.domains['combat'],registry,state.save_id)
    b=state.domains['combat']['battle']
    if b:
        parts=b['battle_id'].split(':')
        if len(parts)!=4 or parts[0]!=state.save_id or parts[2]!='i':raise ValidationError('battle outside save namespace')
        try:g,n=int(parts[1]),int(parts[3])
        except ValueError as exc:raise ValidationError('invalid battle identity') from exc
        if str(g)!=parts[1] or str(n)!=parts[3] or not 1<=g<=state.generation or not 1<=n<=state.identity['instance_counter']:raise ValidationError('unallocated battle identity')
        occupied=set(state.domains['sect']['buildings'])|set(state.domains['disciples']['groups'])
        occupied.update(j['job_id'] for j in state.domains['production']['jobs'].values())
        if b['battle_id'] in occupied:raise ValidationError('battle instance identity collision')
    return state


class GamePersistence(PersistentApplication):
    def _validate(self,state):return validate_combat(super()._validate(state),self.registry)


class GameApplication(DandingApplication):
    def _application(self,specs):
        validators={**sect.validators(self.registry),'production':lambda p:jobs.validate(p,self.registry),
                    'disciples':lambda p:work.validate(p,self.registry)}
        return GamePersistence(self.store,self.registry,specs,references=lambda s:references(s,self.registry),
                               validators=validators,settlement_engine=self.engine,clock=self.clock)

    def player_projection(self,state):return battle.player(self.registry,state.save_id)
    def combat_equipment(self,state):return ()
    def combat_equipment_snapshot(self,state):
        from src.systems.equipment import items
        p=state.domains.get('equipment',items.initial())
        rows={i:p['instances'][i] for i in p['slots'].values()}
        if not any(r.get('refinement') for r in rows.values()):return None
        return freeze_json({'instances':rows,'slots':p['slots'],'audit':[]})
    def combat_artifact(self,state):
        from src.data.artifacts.definitions import settings
        from src.systems.artifacts.artifacts import snapshot
        return snapshot(state,self.registry) if settings(self.registry) else None
    def player_source(self):return "V1基础主角 · 未接入成长加成"

    def default_encounter(self,state):return 'thorn_first'
    def prepare_combat_start(self,state,encounter_id):return encounter_id
    def require_manual_combat(self,state):return None

    def project_combat(self,state):
        validate_combat(state,self.registry)
        b=state.domains.get('combat',battle.initial())['battle']
        encounter=battle.encounter(self.registry,b['encounter_id'] if b else self.default_encounter(state));enemy=battle.monster(self.registry,encounter.monster_id)
        if b:enemy=battle.effective_monster(self.registry,b)
        player=(b.get('player_snapshot') or battle.player(self.registry,state.save_id)) if b else self.player_projection(state)
        view={'battle_id':None,'revision':state.revision,'generation':state.generation,'status':'READY',
              'encounter':{'id':encounter.machine_id,'name':encounter.display_name,'background_asset_id':encounter.background_asset_id},
              'player':{'id':player['id'],'name':player['name'],'max_hp':player['max_hp_milli']/1000,'hp':player['max_hp_milli']/1000,'asset_id':player['asset_id'],'source':self.player_source(),'attack':player['attack_milli']/1000,'armor':player['armor_milli']/1000},
              'enemy':{'definition_id':enemy.machine_id,'name':enemy.display_name,'max_hp':enemy.base_hp_milli/1000,'hp':enemy.base_hp_milli/1000,'asset_id':enemy.asset_id},
              'step':0,'available_commands':['combat_start'],'latest_events':[],'reward_state':'NONE','reward':[],
              'presentation_hints':{'player_action':'idle','enemy_action':'idle'}}
        if b:
            available={'ACTIVE':['combat_attack','combat_abandon'],'PLAYER_WIN':['combat_reward','combat_abandon'],'PLAYER_LOSE':['combat_start'],'ABANDONED':['combat_start'],'SETTLED':['combat_start']}[b['status']]
            view['animation_allowed']=b.get('visual_events_online',True) and not (state.time['pending'] and state.time['pending']['accepted_ms']>OFFLINE_COMBAT_RECENT_MS)
            view.update(battle_id=b['battle_id'],status=b['status'],step=b['step'],available_commands=available,reward_state=b['reward_state'])
            view['player']['hp']=b['player_hp_milli']/1000;view['enemy']['hp']=b['enemy_hp_milli']/1000
            from src.application.combat_effect_views import event_source
            view['latest_events']=[{'kind':e['kind'],'actor':e['actor'],'target':e['target'],'damage':e['damage_milli']/1000,'formula_damage':e['formula_damage_milli']/1000,'target_hp':e['target_hp_milli']/1000,**({'source_name':event_source(self.registry,e)} if 'mechanics' in b else {}),**({'status_id':e['status_id']} if 'status_id' in e else {}),**({k:e[k] for k in ('element','damage_kind')} if 'element' in e else {})} for e in b['latest_events']]
            view['reward']=[{'resource_id':key,'name':holdings.definition(self.registry,key).display_name,'quantity':amount} for key,amount in sorted(b['reward'].items())]
            if view['enemy']['hp']==0:view['presentation_hints']['enemy_action']='death'
            if view['player']['hp']==0:view['presentation_hints']['player_action']='death'
        artifact_value=b.get('artifact_snapshot') if b and b['status'] in ('ACTIVE','PLAYER_WIN') else self.combat_artifact(state)
        if artifact_value:
            from src.data.artifacts.definitions import definition as artifact_definition
            row=artifact_definition(self.registry,artifact_value['artifact_id'])
            view['artifact']={**thaw_json(artifact_value),'name':row['name'],'glyph':row['glyph'],'motion_profile_id':row['motion_profile_id']}
        if b:
            from src.application.combat_effect_views import battle as effects_view
            view.update(effects_view(self.registry,b))
        return freeze_json(view)

    def view(self,save_id):
        state=self.query(save_id)
        return freeze_json({**self.project_view(state),'combat':self.project_combat(state)})

    def combat_view(self,save_id):return self.project_combat(self.query(save_id))

    def act(self,save_id,body):
        envelope(save_id,body,'command');c=body['command']
        if type(c) is not dict or set(c)!={'name','version','payload'} or type(c['version']) is not int or c['version']!=1 or type(c['payload']) is not dict:raise SliceRequestError('invalid game command')
        if c['name'] not in battle.COMMANDS:return super().act(save_id,body)
        try:request=Command(save_id,body['generation'],body['expected_revision'],body['request_id'],c['name'],c['payload'])
        except ValidationError as exc:raise SliceRequestError('invalid combat envelope') from exc
        return self.execute(request)

    def execute(self,request):
        if not isinstance(request,Command):raise ValidationError('Command required')
        if request.name not in battle.COMMANDS:return super().execute(request)
        # Same Foundation transaction/StoredReceipt as Production start. No second authority.
        with self.store.transaction():
            state=self.query(request.save_id)
            if request.generation!=state.generation:raise ConflictError('save generation mismatch')
            previous=self.store.receipt(state.save_id,state.generation,request.request_id)
            if previous:
                if previous.kind!='command' or previous.intent!=request.digest():raise ConflictError('request intent conflict')
                if previous.committed_revision>state.revision:raise ValidationError('receipt ahead of State')
                return self.foundation._decode_receipt(previous)
            require_running(state.time)
            self.require_manual_combat(state)
            if request.expected_revision!=state.revision or state.time['pending'] is not None:raise ConflictError('stale revision or pending settlement')
            if request.version!=1:raise ValidationError('unsupported combat version')
            p=request.payload;partition=state.domains.get('combat',battle.initial());identity=state.identity;stock=state.domains['inventory']
            if request.name=='combat_start':
                if set(p)!={'encounter_id'}:raise ValidationError('exact encounter intent required')
                counter=state.identity['instance_counter']+1
                identity={**state.identity,'instance_counter':counter}
                partition=battle.start(partition,self.registry,state.save_id,f'{state.save_id}:{state.generation}:i:{counter}',self.prepare_combat_start(state,p['encounter_id']),player_snapshot=self.player_projection(state),growth_snapshot=state.domains.get('cultivation',growth.initial(state.save_id)),equipment_sources=self.combat_equipment(state),artifact_snapshot=self.combat_artifact(state),equipment_snapshot=self.combat_equipment_snapshot(state))
            else:
                if set(p)!={'battle_id'}:raise ValidationError('exact battle intent required')
                if request.name=='combat_attack':partition=battle.attack(partition,self.registry,state.save_id,p['battle_id'])
                elif request.name=='combat_abandon':partition=battle.abandon(partition,self.registry,state.save_id,p['battle_id'])
                else:
                    b=battle.current(partition,self.registry,state.save_id,p['battle_id'])
                    if b['status']!='SETTLED':
                        # Validate victory before granting. Rollback covers Inventory and reward marker together.
                        ready=battle.reward_settled(partition,self.registry,state.save_id,p['battle_id'])
                        capacity=sect.capacity_source(state,self.registry)['effective']
                        needed=sum(amount for key,amount in b['reward'].items() if holdings.definition(self.registry,key).warehouse_counted)
                        reserved=sum(amount for job in state.domains['production']['jobs'].values() if job['status']!='COMPLETE' for key,amount in jobs.outputs(job,self.registry).items() if holdings.definition(self.registry,key).warehouse_counted)
                        if holdings.stock_size(stock,self.registry)+needed+reserved>capacity:raise ValidationError('reward storage capacity unavailable')
                        stock,result=operations.grant(stock,self.registry,b['reward'],capacity=capacity)
                        if any(result['discarded'].values()):raise ValidationError('combat cannot discard reward')
                        partition=ready
            candidate=replace(state,identity=identity,domains={**state.domains,'combat':partition,'inventory':stock})
            from src.systems.sect import story
            candidate=story.observe(candidate,self.registry)
            if candidate!=state:candidate=replace(candidate,revision=state.revision+1)
            self.foundation.validate_state(candidate)
            result={'operation':request.name,'combat':self.project_combat(candidate)}
            receipt=Receipt(request.request_id,candidate.revision,result)
            record=StoredReceipt(candidate.save_id,candidate.generation,request.request_id,request.digest(),candidate.revision,'command',thaw_json(receipt.result))
            self.store.commit(state,candidate,record)
        return receipt

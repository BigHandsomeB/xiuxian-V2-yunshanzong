"""Sect economy entry, shared workforce/job/inventory authority; no alternate clock."""
from src.application.world import WorldApplication
from src.systems.combat import battle
from src.application.memory import Command,Receipt
from dataclasses import replace
from src.core.save.codec import StoredReceipt
from src.core.time.world import require_running
from src.core.validation import ConflictError
from src.systems.economy import policy
from src.systems.inventory import operations,holdings
from src.application.economy_settlement import EconomySettlement
from src.application import sect
from src.application.danding import envelope,SliceRequestError
from src.core.state.envelope import freeze_json,thaw_json
from src.core.validation import ValidationError
from src.core.time.world import paused
from src.systems.resources import jobs
from src.systems.disciples import work
from src.systems.sect import buildings
from src.data.registry import DefinitionKey

from src.application import equipment as equip
from src.systems.equipment import items
from src.application.cultivation import partition
from src.systems.cultivation import growth
from src.application.work import references
RECIPES=('herb','ore','wood','forge_sword','forge_ingot_sword')
class EconomyApplication(WorldApplication):
    def _settlement_engine(self):return EconomySettlement(self)
    def _application(self,specs):
        validators={**sect.validators(self.registry),'production':lambda p:jobs.validate(p,self.registry),'disciples':lambda p:work.validate(p,self.registry),'automation':lambda p:policy.validate(p,self.registry)}
        return equip.EconomyPersistence(self.store,self.registry,specs,references=lambda s:references(s,self.registry),validators=validators,settlement_engine=self.engine,clock=self.clock)
    def player_projection(self,state):
        from src.systems.artifacts import artifacts
        actor=items.projection(equip.equipment(state),growth.projection(partition(state),self.registry,state.save_id))
        return artifacts.project(actor,self.registry,self.combat_artifact(state))
    def combat_equipment(self,state):
        p=equip.equipment(state)
        return tuple(p['instances'][identity]['definition_id'] for identity in p['slots'].values())
    def player_source(self):return '等级、里程碑、境界、装备与功法属性 · 开战快照'
    def project_cultivation(self,state):
        v=thaw_json(super().project_cultivation(state));actor=self.player_projection(state);v['combat_projection']=growth.stats(actor)
        v['attributes']=equip.attribute_rows(actor)
        if v['next_realm']:
            p=partition(state);future=({**growth.leveling.normalized(p,self.registry,state.save_id),'current_realm':v['next_realm']['id'],'total_xp':growth.leveling.table(growth.leveling.config(self.registry))[501],'growth_revision':p['growth_revision']+1} if growth.leveling.config(self.registry) else {**p,'current_realm':v['next_realm']['id'],'progress':0,'growth_revision':p['growth_revision']+1})
            from src.systems.artifacts.artifacts import project
            v['next_realm_preview']=growth.stats(project(items.projection(equip.equipment(state),growth.projection(future,self.registry,state.save_id)),self.registry,self.combat_artifact(state)))
        return v
    def create(self,state):
        state=replace(state,domains={**state.domains,'automation':state.domains.get('automation',policy.initial()),'equipment':state.domains.get('equipment',items.initial())})
        if growth.leveling.config(self.registry) and 'cultivation' not in state.domains:
            state=replace(state,domains={**state.domains,'cultivation':growth.leveling.normalized(growth.initial(state.save_id),self.registry,state.save_id)})
        return super().create(state)
    def equipment_count(self,state):return equip.count(state)
    def output_stock(self,state,d):
        return sum(1 for v in equip.equipment(state)['instances'].values() if v['definition_id']==d.equipment_output_id) if d.equipment_output_id else sum(state.domains['inventory']['holdings'].get(k,0) for k,_ in d.outputs)
    def prepare_economy_state(self,state):return state
    def recipe_ids(self):
        from src.data.economy.sect_rules import settings
        cfg=settings(self.registry)
        return tuple(cfg['production_whitelist']) if cfg else (*RECIPES,'pill')
    def start_candidate(self,state,building_id,recipe_id,policy_row=None):
        d=jobs.definition(self.registry,recipe_id)
        if recipe_id not in self.recipe_ids():raise ValidationError('生产配方尚未开放')
        row=buildings.get_building(state.domains['sect'],self.registry,building_id)
        from src.data.economy.sect_rules import settings
        cfg=settings(self.registry);unlock=cfg['recipe_unlock_overrides'].get(recipe_id,{'floor':d.unlock_floor,'realm':d.unlock_realm}) if cfg else {'floor':d.unlock_floor,'realm':d.unlock_realm}
        if row['definition_id']!=d.building_kind or row['level']<d.min_level or unlock['floor'] or unlock['realm']:raise ValidationError('建筑或解锁条件不足')
        if cfg:
            from src.systems.sect.rules import development
            minimum=cfg.get('recipe_sect_minimum',{}).get(recipe_id,1)
            if development(state.domains['sect'],self.registry,state.domains.get('dungeon',{}).get('cleared_floor',0))['level']<minimum:
                raise ValidationError(f'宗门等级不足，需要{minimum}级宗门')
        cap=work.capability(state.domains['disciples'],self.registry,building_id)
        if not cap['workers']:raise ValidationError('请先安排工作弟子')
        amounts={k:n*cap['workers'] for k,n in d.inputs}
        stock,_=operations.consume(state.domains['inventory'],self.registry,amounts)
        counters={**state.identity,'instance_counter':state.identity['instance_counter']+1,'event_counter':state.identity['event_counter']+1}
        job_id=f"{state.save_id}:{state.generation}:i:{counters['instance_counter']}";event_id=f"{state.save_id}:{state.generation}:e:{counters['event_counter']}"
        production=jobs.start(state.domains['production'],self.registry,building_id=building_id,recipe_id=recipe_id,job_id=job_id,event_id=event_id,sim_ms=state.time['sim_time_ms'],workers=cap['workers'],yield_milli=jobs.yield_for_level(cap['worker_power_milli'],row['level']),work_rate_milli=cap['work_rate_milli'])
        domains=self._start_domains(state,production,stock,job_id,{'building_id':building_id,'recipe_id':recipe_id})
        if policy_row and cfg:
            from src.application.sect_economy import reserved
            prepared=replace(state,domains=domains)
            used=holdings.stock_size(stock,self.registry)+reserved(prepared,self.registry)
            material_output=any(holdings.definition(self.registry,k).warehouse_counted for k,_ in d.outputs)
            if material_output and used>sect.capacity_source(state,self.registry)['effective']:raise ValidationError('仓库容量不足，等待库存减少')
        return replace(state,domains=domains,identity=counters)
    def execute(self,q):
        if q.name=='combat_reward':return self.reward(q)
        if q.name not in ('production_start','alchemy_start','automation_production','automation_equipment',*equip.COMMANDS):return super().execute(q)
        with self.store.transaction():
            s=self.query(q.save_id)
            if s.generation!=q.generation:raise ConflictError('存档状态已变化，请更新')
            r=self.store.receipt(s.save_id,s.generation,q.request_id)
            if r:
                if r.kind!='command' or r.intent!=q.digest() or r.committed_revision>s.revision:raise ConflictError('重复请求内容不一致')
                return self.foundation._decode_receipt(r)
            if q.expected_revision!=s.revision or s.time['pending']:raise ConflictError('状态已变化或正在续算，请更新后重试')
            if q.version!=1:raise ValidationError('未知命令版本')
            original=s;s=self.prepare_economy_state(s)
            p=q.payload
            if q.name in ('production_start','alchemy_start'):
                if set(p)!={'building_id','recipe_id'}:raise ValidationError('请选择生产配方')
                if q.name=='alchemy_start' and (p['recipe_id'] not in self.recipe_ids() or jobs.definition(self.registry,p['recipe_id']).building_kind!='alchemy'):raise ValidationError('丹方尚未开放')
                candidate=self.start_candidate(s,p['building_id'],p['recipe_id'])
            elif q.name in equip.COMMANDS:candidate=equip.command(s,self.registry,q.name,p)
            elif q.name=='automation_production':
                if set(p)!={'building_id','policy'}:raise ValidationError('完整生产策略必需')
                if p['policy'].get('recipe_id') not in self.recipe_ids():raise ValidationError('此自动生产类型尚未开放')
                candidate=replace(s,domains={**s.domains,'automation':policy.set_production(s.domains['automation'],self.registry,p['building_id'],p['policy'])})
            elif q.name=='automation_equipment':
                if set(p)!={'policy'}:raise ValidationError('完整装备策略必需')
                candidate=replace(s,domains={**s.domains,'automation':policy.set_equipment(s.domains['automation'],self.registry,p['policy'])})
            candidate=self.engine.wake(candidate);candidate=replace(candidate,revision=original.revision+1 if candidate!=original else original.revision)
            self.foundation.validate_state(candidate)
            details={'operation':q.name}
            if q.name in ('equipment_sell_all','equipment_salvage_all'):
                preview=equip.bulk_preview(s,self.registry);details.update(count=preview['count'],protected_count=preview['protected_count'],amounts=preview['sell' if q.name=='equipment_sell_all' else 'salvage'],selection_digest=preview['selection_digest'])
            elif q.name in equip.COMMANDS and 'instance_ids' in p:
                details['instance_ids']=list(p['instance_ids']);amounts={}
                for identity in p['instance_ids']:
                    row=items.get(equip.equipment(s),identity);d=items.definition(self.registry,row['definition_id'])
                    for key,n in ({'coins':items.sale_price(self.registry,d.machine_id)} if q.name=='equipment_sell' else dict(d.salvage)).items():amounts[key]=amounts.get(key,0)+n
                details['amounts']=amounts
            elif q.name in equip.COMMANDS:
                details['instance_id']=p['instance_id']
                if q.name in ('equipment_sell','equipment_salvage'):
                    row=items.get(equip.equipment(s),p['instance_id']);d=items.definition(self.registry,row['definition_id']);details.update(definition_id=d.machine_id,amounts={'coins':items.sale_price(self.registry,d.machine_id)} if q.name=='equipment_sell' else dict(d.salvage))
            receipt=Receipt(q.request_id,candidate.revision,details)
            self.store.commit(original,candidate,StoredReceipt(s.save_id,s.generation,q.request_id,q.digest(),candidate.revision,'command',thaw_json(receipt.result)))
        return receipt

    def combat_reward_candidate(self,state,candidate):return candidate
    def reward_amounts(self,b):return b['reward']
    def equipment_reward_enabled(self):return True
    def reward_grant(self,state,b):return self.reward_amounts(b),state
    def settle_combat_candidate(self,s):
        p=s.domains.get('combat',battle.initial());b=p['battle']
        if b is None:raise ValidationError('当前没有战斗')
        if b['status']=='SETTLED':return s
        completed=battle.reward_settled(p,self.registry,s.save_id,b['battle_id'])
        reserved=sum(sum(n for k,n in jobs.outputs(j,self.registry).items() if holdings.definition(self.registry,k).warehouse_counted) for j in s.domains['production']['jobs'].values() if j['status']!='COMPLETE')
        amounts,s=self.reward_grant(s,b);equipment_reward=self.equipment_reward_enabled()
        needed=sum(n for k,n in amounts.items() if holdings.definition(self.registry,k).warehouse_counted)
        capacity=sect.capacity_source(s,self.registry)['effective']
        if holdings.stock_size(s.domains['inventory'],self.registry)+reserved+needed>capacity:raise ValidationError('仓库空间不足，战利品等待领取')
        stock,result=operations.grant(s.domains['inventory'],self.registry,amounts,capacity=capacity)
        if any(result['discarded'].values()):raise ValidationError('不能丢弃战利品')
        candidate=replace(s,domains={**s.domains,'combat':completed,'inventory':stock})
        if equipment_reward:
            candidate,item_id=equip.acquire(candidate,self.registry,'basic_head',b['battle_id'])
            e=thaw_json(equip.equipment(candidate));e['latest_reward']={'battle_id':b['battle_id'],'instance_id':item_id,'definition_id':'basic_head'}
            candidate=replace(candidate,domains={**candidate.domains,'equipment':e})
        candidate=self.combat_reward_candidate(s,candidate)
        if growth.leveling.config(self.registry):
            from src.systems.dungeons.progress import floor_of,definition
            from src.data.dungeons.expeditions import owner
            floor=floor_of(self.registry,b['encounter_id']) or 1
            did=owner(self.registry,b['encounter_id']) or 'thorn_path'
            tier=definition(self.registry,did).tiers[floor-1]
            grown,_=growth.leveling.kill(partition(candidate),self.registry,candidate.save_id,floor,tier,b['battle_id'])
            candidate=replace(candidate,domains={**candidate.domains,'cultivation':grown})
            from src.systems.artifacts import artifacts
            candidate=artifacts.award(candidate,self.registry,b,tier)
        return candidate

    def reward(self,q):
        with self.store.transaction():
            s=self.query(q.save_id)
            if s.generation!=q.generation:raise ConflictError('存档状态已变化')
            r=self.store.receipt(s.save_id,s.generation,q.request_id)
            if r:
                if r.kind!='command' or r.intent!=q.digest() or r.committed_revision>s.revision:raise ConflictError('重复请求内容不一致')
                return self.foundation._decode_receipt(r)
            require_running(s.time)
            self.require_manual_combat(s)
            if s.revision!=q.expected_revision or s.time['pending']:raise ConflictError('状态已变化或正在续算')
            if q.version!=1 or set(q.payload)!={'battle_id'}:raise ValidationError('请选择当前战斗')
            p=s.domains.get('combat',battle.initial());b=battle.current(p,self.registry,s.save_id,q.payload['battle_id']);candidate=s
            if b['status']!='SETTLED':
                candidate=self.settle_combat_candidate(s)
                candidate=replace(candidate,revision=s.revision+1)
            self.foundation.validate_state(candidate)
            receipt=Receipt(q.request_id,candidate.revision,{'operation':q.name,'xp_gained':max(0,growth.leveling.xp(partition(candidate),growth.leveling.config(self.registry))-growth.leveling.xp(partition(s),growth.leveling.config(self.registry))) if growth.leveling.config(self.registry) else 0,'levels_gained':growth.leveling.level(partition(candidate),growth.leveling.config(self.registry))-growth.leveling.level(partition(s),growth.leveling.config(self.registry)) if growth.leveling.config(self.registry) else 0,'combat':self.project_combat(candidate),'equipment_reward':'青布冠' if self.equipment_reward_enabled() and equip.equipment(candidate).get('latest_reward',{} ) and equip.equipment(candidate)['latest_reward']['battle_id']==b['battle_id'] else None})
            self.store.commit(s,candidate,StoredReceipt(s.save_id,s.generation,q.request_id,q.digest(),candidate.revision,'command',thaw_json(receipt.result)))
        return receipt
    def project_combat(self,state):
        v=thaw_json(super().project_combat(state))
        marker=equip.equipment(state).get('latest_reward')
        if v['status']=='PLAYER_WIN' or (v['status']=='SETTLED' and marker and marker['battle_id']==v['battle_id']):
            d=items.definition(self.registry,'basic_head');v['reward'].append({'resource_id':d.machine_id,'name':d.display_name,'quantity':1,'asset_id':d.asset_id,'category':'equipment'})
        return freeze_json(v)

    def act(self,save_id,body):
        envelope(save_id,body,'command');c=body['command']
        if type(c) is not dict or set(c)!={'name','version','payload'} or type(c['version']) is not int or c['version']!=1 or type(c['payload']) is not dict:raise SliceRequestError('invalid economy command')
        if c['name'] not in ('production_start','work_assign','work_unassign','work_reassign','automation_production','automation_equipment',*equip.COMMANDS) or not c['payload']:return super().act(save_id,body)
        return self.execute(Command(save_id,body['generation'],body['expected_revision'],body['request_id'],c['name'],c['payload']))
    def _prepare_start(self,state,p,*,command_name='production_start'):
        if command_name=='production_start':
            if set(p)!={'building_id','recipe_id'} or p['recipe_id'] not in RECIPES:raise ValidationError('请选择已开放的生产配方')
            p={**p,'unlock_floor':0,'unlock_realm':0}
        return super()._prepare_start(state,p,command_name=command_name)
    def _start_domains(self,state,production,stock,job_id,p):
        domains=super()._start_domains(state,production,stock,job_id,p)
        from src.application.alchemy import _capacity_allows
        output=jobs.outputs(production['jobs'][p['building_id']],self.registry)
        if any(holdings.definition(self.registry,k).warehouse_counted for k in output) and not _capacity_allows(state,self.registry,stock,production):raise ValidationError('仓库空间不足，请先整理仓库')
        return domains
    def crafting_equipment_preview(self,definition_id,quantity):
        from src.data.economy.definitions import EQUIPMENT_SLOTS
        d=items.definition(self.registry,definition_id)
        ranges=d.craft_stat_ranges or d.stat_ranges
        stats=dict(d.stats)
        from src.data.combat.mechanics import settings as effect_settings,equipment_ranges
        effects=effect_settings(self.registry)
        if effects and definition_id in effects['equipment']:
            ranges=equipment_ranges(definition_id,craft=True);stats={key:(low+high)//2 for key,low,high,step in ranges}
        return {'definition_id':d.machine_id,'name':d.display_name,'asset_id':d.asset_id,
                'quantity':quantity,'quality':d.quality,
                'quality_name':{'white':'凡品','green':'灵品','blue':'玄品','rare':'稀有'}[d.quality],
                'slot_name':dict(EQUIPMENT_SLOTS)[d.slot],
                'stats':{k.removesuffix('_milli').removesuffix('_bps'):n/(100 if k.endswith('_bps') else 1000) for k,n in stats.items()},
                'stat_ranges':{k.removesuffix('_milli').removesuffix('_bps'):[a/(100 if k.endswith('_bps') else 1000),b/(100 if k.endswith('_bps') else 1000)] for k,a,b,step in ranges}}

    def project_economy(self,state):
        from src.data.economy.sect_rules import settings
        recipes=[]
        for building_id,row in state.domains['sect']['buildings'].items():
            for key in self.recipe_ids():
                d=jobs.definition(self.registry,key)
                if d.building_kind!=row['definition_id']:continue
                reasons=[];cap=work.capability(state.domains['disciples'],self.registry,building_id)
                try:self.start_candidate(state,building_id,key)
                except (ValidationError,ConflictError) as exc:
                    message=str(exc)
                    reasons.append(message if any('\u4e00'<=c<='\u9fff' for c in message) else '生产条件不足，请查看材料、岗位与仓库')
                if state.time['pending']:reasons.append('宗门进度续算中，请稍候')
                job=state.domains['production']['jobs'].get(building_id)
                if job and job['status']!='COMPLETE':reasons.append('当前生产尚未完成')
                if any(state.domains['inventory']['holdings'].get(k,0)<n*cap['workers'] for k,n in d.inputs):reasons.append('材料不足')
                inputs={k:n*max(1,cap['workers']) for k,n in d.inputs};output=jobs.outputs({'recipe_id':key,'yield_milli':jobs.yield_for_level(cap['worker_power_milli'] or 1000,row['level'])},self.registry)
                recipes.append({'building_id':building_id,'recipe_id':key,'name':d.display_name,'building_kind':d.building_kind,'min_level':d.min_level,'min_sect_level':(settings(self.registry).get('recipe_sect_minimum',{}).get(key,1) if settings(self.registry) else 1),'inputs':[{'resource_id':k,'name':self.registry.lookup(DefinitionKey('resources',k)).display_name,'quantity':n,'current':state.domains['inventory']['holdings'].get(k,0)} for k,n in inputs.items()], 'outputs':[{'resource_id':k,'name':self.registry.lookup(DefinitionKey('resources',k)).display_name,'quantity':n} for k,n in output.items()], 'equipment_output':None if not d.equipment_output_id else self.crafting_equipment_preview(d.equipment_output_id,max(1,cap['worker_power_milli']//1000)),'duration_seconds':d.duration_ms/1000,'workers':cap['workers'],'can_start':not reasons,'blocking_reasons':reasons,'job':job,'job_duration_seconds':jobs.duration(job,self.registry)/1000 if job else None,'remaining_seconds':0 if not job else max(0,job['due_ms']-state.time['sim_time_ms'])/1000,'work':work.project(state.domains['disciples'],self.registry,building_id)})
        automation=thaw_json(state.domains['automation']);can_auto=False
        for b,p in automation['production'].items():
            reason='自动生产关闭'
            if p['enabled']:
                d=jobs.definition(self.registry,p['recipe_id'])
                if self.output_stock(state,d)>=p['target']:reason='目标库存已达到'
                else:
                    try:self.start_candidate(state,b,p['recipe_id'],policy_row=p);reason='等待自动续产';can_auto=True
                    except (ValidationError,ConflictError) as exc:reason=str(exc) if any('\u4e00'<=c<='\u9fff' for c in str(exc)) else '等待材料、岗位或仓库条件'
            automation['production'][b]['waiting_reason']=reason
        working=any(j['status']=='WORKING' for j in state.domains['production']['jobs'].values())
        awaiting=any(r['evaluation']=='PENDING' for r in equip.equipment(state)['instances'].values())
        needs=not paused(state.time) and bool(state.time['pending'] or working or can_auto or awaiting)
        return {'recipes':recipes,'automation':automation,'needs_poll':needs,'needs_settlement':needs}
    def view(self,save_id):
        # Validate the persisted snapshot before entering the projection-only scope.
        # Inheritance layers share untouched read-only branches instead of copying
        # the entire display tree each time. Seal once before returning to callers.
        from contextlib import nullcontext
        from src.core.state.draft import batch_scope
        from src.core.state.projection import projection_checks
        state=self.query(save_id)
        with projection_checks(),(batch_scope() if state.time['pending'] is None else nullcontext()):
            view=self.project_full_view(state)
        return freeze_json(view)
    def project_full_view(self,state):
        v=thaw_json(self.project_world(state));v['economy']=self.project_economy(state);v['equipment']=equip.view(state,self.registry);return freeze_json(v)

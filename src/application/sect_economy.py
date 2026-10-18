"""Shipping economy commands over the existing SQLite/receipt authority."""
from dataclasses import replace
from src.data.economy.sect_rules import settings
from src.core.state.envelope import thaw_json
from src.core.validation import ValidationError,ConflictError
from src.application.memory import Command,Receipt
from src.core.save.codec import StoredReceipt
from src.application.danding import envelope,SliceRequestError
from src.application import sect,equipment as equip
from src.systems.inventory import holdings,operations
from src.systems.sect import buildings,rules
from src.systems.resources import jobs
from src.systems.disciples import work

COMMANDS=('material_overflow','building_upgrade','equipment_craft')

def defaults(state,registry):
    """Pure read defaults. Persist only as part of the next atomic mutation."""
    cfg=settings(registry)
    if not cfg:return state
    rows=thaw_json(state.domains['sect']);counter=state.identity['instance_counter']
    for kind,level in cfg['read_default_buildings'].items():
        if any(r['definition_id']==kind for r in rows['buildings'].values()):continue
        counter+=1;rows['buildings'][f'{state.save_id}:{state.generation}:i:{counter}']={'definition_id':kind,'level':level,'construction_target':None}
    auto=thaw_json(state.domains.get('automation',{}))
    # Missing automation is handled by EconomyApplication.create; read requires it.
    if auto:
        auto.setdefault('material_overflow',cfg['legacy_material_overflow']);auto.setdefault('overflow_log',[])
    return replace(state,identity={**state.identity,'instance_counter':counter},domains={**state.domains,'sect':rows,**({'automation':auto} if auto else {})})

def initialize(state,registry):
    cfg=settings(registry)
    if not cfg:return state
    from src.systems.economy import policy
    state=replace(state,domains={**state.domains,'automation':policy.initial()});state=defaults(state,registry)
    disciples=thaw_json(state.domains['disciples']);disciples['assignments']={}
    auto=thaw_json(state.domains['automation']);auto['material_overflow']=cfg['new_save_material_overflow']
    for kind,row in cfg['new_save_production'].items():
        bid=next(k for k,v in state.domains['sect']['buildings'].items() if v['definition_id']==kind)
        remaining=row['workers']
        for gid,group in sorted(disciples['groups'].items()):
            allocated=sum(disciples['assignments'].get(gid,{}).values());n=min(remaining,group['count']-allocated)
            if n:
                disciples=thaw_json(work.assign(disciples,registry,gid,bid,n));remaining-=n
            if not remaining:break
        if remaining:raise ValidationError('initial workforce does not cover configured production')
        auto['production'][bid]={'enabled':True,'recipe_id':row['recipe_id'],'target':row['target'],'max_consumption':row['max_consumption'],'reserves':{}}
    return replace(state,domains={**state.domains,'disciples':disciples,'automation':auto})

def reserved(state,registry):
    return sum(sum(n for k,n in jobs.outputs(j,registry).items() if holdings.definition(registry,k).warehouse_counted) for j in state.domains['production']['jobs'].values() if j['status']!='COMPLETE')

def craft_cost(registry,key):
    from src.systems.economy.valuation import craft_inputs
    cost=craft_inputs(registry,key)
    if cost is None:raise ValidationError('此装备打造尚未开放')
    return cost

def craft_gate(state,registry,key):
    cfg=settings(registry).get('management',{});gate=cfg.get('craft_gates',{}).get(key)
    if not gate:return equip.items.definition(registry,key).craft_roll_version or 'thorn-roll-v2'
    from src.systems.dungeons import progress
    if rules.development(state.domains['sect'],registry,state.domains['dungeon']['cleared_floor'])['level']<cfg['new_craft_min_sect_level']:raise ValidationError('宗门二级解锁副本装备制造')
    if max((r['level'] for r in state.domains['sect']['buildings'].values() if r['definition_id']=='forge'),default=0)<gate['forge_level']:raise ValidationError('炼器阁等级不足')
    if not progress.unlocked(state.domains['dungeon'],registry,gate['dungeon_id']):raise ValidationError('对应副本尚未解锁')
    return gate['dungeon_id']+'-roll-v1'

class SectEconomyFeatures:
    def prepare_economy_state(self,state):return defaults(state,self.registry)
    def act(self,save_id,body):
        if isinstance(body,dict) and isinstance(body.get('command'),dict) and body['command'].get('name') in COMMANDS:
            envelope(save_id,body,'command');c=body['command']
            if set(c)!={'name','version','payload'} or type(c['payload']) is not dict or type(c['version']) is not int:raise SliceRequestError('invalid sect economy command')
            return self.execute(Command(save_id,body['generation'],body['expected_revision'],body['request_id'],c['name'],c['payload'],c['version']))
        return super().act(save_id,body)
    def execute(self,q):
        if not isinstance(q,Command):raise ValidationError('Command required')
        cfg=settings(self.registry)
        if not cfg or q.name not in (*COMMANDS,'work_assign','work_unassign','work_reassign'):return super().execute(q)
        with self.store.transaction():
            original=self.query(q.save_id)
            if original.generation!=q.generation:raise ConflictError('存档换代，请更新')
            record=self.store.receipt(original.save_id,original.generation,q.request_id)
            if record:
                if record.kind!='command' or record.intent!=q.digest() or record.committed_revision>original.revision:raise ConflictError('重复请求内容不一致')
                return self.foundation._decode_receipt(record)
            if q.expected_revision!=original.revision or original.time['pending']:raise ConflictError('状态已变化或正在续算，请更新')
            if q.version!=1:raise ValidationError('未知命令版本')
            state=defaults(original,self.registry);p=q.payload;details={'operation':q.name}
            if q.name=='material_overflow':
                if set(p)!={'enabled'} or type(p['enabled']) is not bool:raise ValidationError('请选择材料折算开关')
                auto=thaw_json(state.domains['automation']);auto['material_overflow']=p['enabled'];candidate=replace(state,domains={**state.domains,'automation':auto})
            elif q.name=='building_upgrade':
                if set(p)!={'building_id'}:raise ValidationError('请选择建筑实例')
                bid=p['building_id'];quote=rules.quote_upgrade(state.domains['sect'],self.registry,bid)
                row=buildings.get_building(state.domains['sect'],self.registry,bid)
                if row['definition_id'] not in cfg['building_upgrade']['materials']:raise ValidationError('此建筑升级尚未开放')
                stock,_=operations.consume(state.domains['inventory'],self.registry,quote['cost'])
                part=thaw_json(state.domains['sect']);part['buildings'][bid]['level']=quote['target_level']
                candidate=replace(state,domains={**state.domains,'sect':part,'inventory':stock});details.update(building_id=bid,target_level=quote['target_level'],amounts=quote['cost'])
            elif q.name=='equipment_craft':
                if set(p)!={'equipment_id'} or type(p['equipment_id']) is not str:raise ValidationError('请选择装备')
                key=p['equipment_id'];version=craft_gate(state,self.registry,key);cost=craft_cost(self.registry,key);stock,_=operations.consume(state.domains['inventory'],self.registry,cost)
                candidate=replace(state,domains={**state.domains,'inventory':stock})
                from src.data.combat.mechanics import settings as effects_settings,ROLL_VERSION,CRAFT_ROLL_VERSION
                if effects_settings(self.registry) and key in effects_settings(self.registry)['equipment']:
                    version=CRAFT_ROLL_VERSION if effects_settings(self.registry)['equipment'][key].get('craft_ranges') else ROLL_VERSION
                seed=f'{state.save_id}:{state.generation}:i:{state.identity["instance_counter"]+1}'
                candidate,identity=equip.acquire(candidate,self.registry,key,seed,roll_version=version)
                details.update(instance_id=identity,definition_id=key,amounts=cost)
            else:
                if q.name=='work_assign':
                    if set(p) not in ({'worker_id','building_id','count'},{'building_id','count'}):raise ValidationError('完整岗位分配必需')
                    buildings.get_building(state.domains['sect'],self.registry,p['building_id'])
                    part=work.assign(state.domains['disciples'],self.registry,p['worker_id'],p['building_id'],p['count']) if 'worker_id' in p else work.assign_shared(state.domains['disciples'],self.registry,p['building_id'],p['count'])
                elif q.name=='work_unassign':
                    if set(p) not in ({'worker_id','building_id'},{'building_id'}):raise ValidationError('完整解除岗位必需')
                    part=work.unassign(state.domains['disciples'],self.registry,p['worker_id'],p['building_id']) if 'worker_id' in p else work.unassign_shared(state.domains['disciples'],self.registry,p['building_id'])
                else:
                    if set(p)!={'worker_id','from_building_id','to_building_id'}:raise ValidationError('完整岗位转移必需')
                    buildings.get_building(state.domains['sect'],self.registry,p['to_building_id'])
                    part=work.reassign(state.domains['disciples'],self.registry,p['worker_id'],p['from_building_id'],p['to_building_id'])
                candidate=replace(state,domains={**state.domains,'disciples':part})
            candidate=self.engine.wake(candidate);candidate=replace(candidate,revision=original.revision+1 if candidate!=original else original.revision)
            self.foundation.validate_state(candidate)
            receipt=Receipt(q.request_id,candidate.revision,details)
            self.store.commit(original,candidate,StoredReceipt(original.save_id,original.generation,q.request_id,q.digest(),candidate.revision,'command',thaw_json(receipt.result)))
        return receipt
    def project_world(self,state):
        original=state;prepared=defaults(state,self.registry);v=thaw_json(super().project_world(prepared))
        cfg=settings(self.registry)
        if cfg:
            rank=rules.development(prepared.domains['sect'],self.registry,prepared.domains.get('dungeon',{}).get('cleared_floor',0))
            rank['unlocks']=[{**r,'unlocked':rank['level']>=r['level']} for r in cfg.get('sect_unlocks',())]
            v['sect_development']=rank
        if original.time['pending']:
            from dataclasses import asdict
            from src.core.time.model import Continuation
            v=thaw_json(v);v['time']['continuation']=asdict(Continuation.for_state(original))
        return v
    def project_view(self,state):return super().project_view(defaults(state,self.registry))
    def project_economy(self,state):
        state=defaults(state,self.registry);v=super().project_economy(state);cfg=settings(self.registry)
        if not cfg:return v
        v['material_overflow']=state.domains['automation'].get('material_overflow',cfg['legacy_material_overflow'])
        v['material_cap_rows']=[{'resource_id':k,'name':holdings.definition(self.registry,k).display_name,'cap':n} for k,n in cfg['material_caps'].items()]
        if cfg.get('management'):
            from src.data.economy.market import settings as market_settings
            v['protected_material_ids']=[rid for rid,row in market_settings(self.registry)['items'].items() if row['boss_only']]
        v['material_caps']=dict(cfg['material_caps']);v['overflow_coin_per_item']=cfg['overflow_coin_per_item'];v['auto_production_capacity_ratio']=cfg['auto_production_capacity_ratio']
        rows=[]
        for key in (*cfg['craft']['materials'],*cfg['craft']['boss_equipment']):
            d=equip.items.definition(self.registry,key);cost=craft_cost(self.registry,key);reasons=[]
            try:
                craft_gate(state,self.registry,key)
                if state.time['pending']:raise ConflictError('宗门进度正在续算')
                stock,_=operations.consume(state.domains['inventory'],self.registry,cost)
            except (ValidationError,ConflictError) as exc:reasons.append(str(exc))
            rows.append({**self.crafting_equipment_preview(key,1),'equipment_id':key,'name':d.display_name,'asset_id':d.asset_id,'quality':d.quality,'requirements':[{'resource_id':r,'name':holdings.definition(self.registry,r).display_name,'quantity':n,'current':state.domains['inventory']['holdings'].get(r,0)} for r,n in cost.items()],'can_craft':not reasons,'blocking_reasons':reasons})
        v['crafting']=rows
        return v

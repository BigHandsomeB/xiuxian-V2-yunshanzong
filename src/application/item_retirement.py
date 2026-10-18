"""Explicit content retirement over existing transactions, legacy definitions retained."""
from dataclasses import replace
from src.application.economy import EconomyApplication
from src.application.economy_settlement import EconomySettlement
from src.application import equipment as equip
from src.application.cultivation import partition
from src.application.memory import Receipt
from src.core.save.codec import StoredReceipt
from src.core.state.envelope import thaw_json,freeze_json
from src.core.validation import ValidationError,ConflictError
from src.systems.inventory import operations
from src.systems.cultivation import growth
from src.systems.equipment import items

RETIRED_ITEMS=frozenset(('basic_left','basic_head'))
RETIRED_RECIPES=frozenset(('forge_sword','forge_ingot_sword'))

def discard_retired(state,registry):
    if state.time['pending']:raise ConflictError('请先完成进度续算，再移除旧物品')
    for j in state.domains['production']['jobs'].values():
        if j['recipe_id'] in RETIRED_RECIPES and j['status']!='COMPLETE':raise ConflictError('存在旧炼器任务，需先审查处理')
    amount=state.domains['inventory']['holdings'].get('dewleaf',0)
    stock,_=operations.consume(state.domains['inventory'],registry,{'dewleaf':amount} if amount else {})
    e=thaw_json(equip.equipment(state));removed={k:r['definition_id'] for k,r in e['instances'].items() if r['definition_id'] in RETIRED_ITEMS}
    for k in removed:del e['instances'][k]
    e['slots']={k:v for k,v in e['slots'].items() if v not in removed}
    if e.get('latest_reward',{} ) and e['latest_reward']['definition_id'] in RETIRED_ITEMS:e['latest_reward']=None
    auto=thaw_json(state.domains['automation'])
    auto['production']={k:v for k,v in auto['production'].items() if v['recipe_id'] not in RETIRED_RECIPES}
    candidate=replace(state,domains={**state.domains,'inventory':stock,'equipment':e,'automation':auto})
    return candidate,{'removed_resources':{'dewleaf':amount},'removed_equipment':removed,'compensation':{}}

class RetiredSettlement(EconomySettlement):
    def advance(self,state,**kwargs):
        # Recovery snapshots remain valid and GET stays pure. Explicit settlement
        # removes retired holdings without touching history/checkpoint or the clock.
        clean,_=discard_retired(state,self.registry) if not state.time['pending'] else (state,None)
        candidate,result=super().advance(clean,**kwargs)
        if not candidate.time['pending']:candidate,_=discard_retired(candidate,self.registry)
        candidate=replace(candidate,revision=state.revision+int(replace(candidate,revision=state.revision)!=state))
        if candidate.time['pending']:
            t=thaw_json(candidate.time);t['pending']['revision']=candidate.revision;candidate=replace(candidate,time=t)
        return candidate,result

class RetiredEconomyApplication(EconomyApplication):
    """Live content selection; original EconomyApplication is historical compatibility."""
    def _settlement_engine(self):return RetiredSettlement(self)
    def start_candidate(self,state,building_id,recipe_id,policy_row=None):
        if recipe_id in RETIRED_RECIPES:raise ValidationError('此装备及配方已移除')
        return super().start_candidate(state,building_id,recipe_id,policy_row)
    def equipment_reward_enabled(self):return False
    def reward_amounts(self,b):return {k:v for k,v in b['reward'].items() if k!='dewleaf'}
    def player_projection(self,state):
        e=equip.equipment(state)
        kept={k:v for k,v in e['slots'].items() if e['instances'][v]['definition_id'] not in RETIRED_ITEMS}
        if len(kept)!=len(e['slots']):e={**e,'slots':kept}
        from src.systems.artifacts.artifacts import project
        return project(items.projection(e,growth.projection(partition(state),self.registry,state.save_id)),self.registry,self.combat_artifact(state))
    def project_cultivation(self,state):
        v=thaw_json(super().project_cultivation(state))
        if v['next_realm'] and not growth.leveling.config(self.registry):
            p=partition(state);future={**p,'current_realm':v['next_realm']['id'],'progress':0,'growth_revision':p['growth_revision']+1}
            v['next_realm_preview']=growth.stats(growth.projection(future,self.registry,state.save_id))
        return freeze_json(v)
    def project_combat(self,state):
        v=thaw_json(super().project_combat(state));v['reward']=[r for r in v['reward'] if r['resource_id'] not in (*RETIRED_ITEMS,'dewleaf')];return freeze_json(v)
    def project_economy(self,state):
        v=super().project_economy(state);v['recipes']=[r for r in v['recipes'] if r['recipe_id'] not in RETIRED_RECIPES];return v
    def project_full_view(self,state):
        v=thaw_json(super().project_full_view(state));retired=[r for r in v['equipment']['instances'] if r['definition_id'] in RETIRED_ITEMS]
        v['equipment']['instances']=[r for r in v['equipment']['instances'] if r['definition_id'] not in RETIRED_ITEMS];v['equipment']['count']=len(v['equipment']['instances'])
        v['capacity']['used']-=len(retired)+v['inventory'].get('dewleaf',{}).get('quantity',0)
        for key in ('inventory','holdings'):v[key].pop('dewleaf',None)
        return freeze_json(v)
    def execute(self,q):
        if q.name in equip.COMMANDS:
            s=self.query(q.save_id);identities=q.payload.get('instance_ids',(q.payload.get('instance_id'),))
            if isinstance(identities,(list,tuple)):
                for identity in identities:
                    row=equip.equipment(s)['instances'].get(identity) if type(identity) is str else None
                    if row and row['definition_id'] in RETIRED_ITEMS:raise ValidationError('此装备已移除')
        if q.name=='automation_production' and q.payload.get('policy',{}).get('recipe_id') in RETIRED_RECIPES:raise ValidationError('此装备配方已移除')
        return super().execute(q)
    def retire_owned(self,q):
        """Trusted maintenance command only; no browser endpoint or automatic grant."""
        if q.name!='retire_three_items' or q.version!=1 or q.payload:raise ValidationError('exact retirement command required')
        with self.store.transaction():
            state=self.query(q.save_id)
            if q.generation!=state.generation:raise ConflictError('generation mismatch')
            old=self.store.receipt(state.save_id,state.generation,q.request_id)
            if old:
                if old.intent!=q.digest() or old.kind!='command':raise ConflictError('retirement receipt conflict')
                return self.foundation._decode_receipt(old)
            if q.expected_revision!=state.revision:raise ConflictError('存档已变化，请重新审查')
            candidate,details=discard_retired(state,self.registry)
            candidate=self.engine.wake(candidate);candidate=replace(candidate,revision=state.revision+int(candidate!=state))
            self.foundation.validate_state(candidate)
            receipt=Receipt(q.request_id,candidate.revision,{'operation':q.name,**details})
            self.store.commit(state,candidate,StoredReceipt(state.save_id,state.generation,q.request_id,q.digest(),candidate.revision,'command',thaw_json(receipt.result)))
            return receipt

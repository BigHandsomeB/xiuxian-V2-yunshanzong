"""@module application/alchemy
@purpose Minimal explicit alchemy command/admission/query; reuse Work/Production transaction.
@depends application/work,sect; systems/alchemy,resources,inventory,sect,disciples; Core/Data
@usedBy tests/systems/test_alchemy; future authorized game integration
@see ./INDEX.md
"""
from src.application.work import WorkApplication,new_state
from src.application import sect
from src.core.state.envelope import freeze_json
from src.core.validation import ValidationError
from src.systems.alchemy import recipes
from src.systems.resources import jobs
from src.systems.inventory import holdings,operations
from src.systems.sect import buildings
from src.systems.disciples import work


def _capacity_allows(state,registry,stock,production,extra_outputs=None):
    """Admission only, not another reservation authority. Completion rechecks capacity."""
    amounts=[jobs.outputs(j,registry) for j in production['jobs'].values() if j['status']!='COMPLETE']
    if extra_outputs is not None:amounts.append(extra_outputs)
    needed=sum(n for output in amounts for key,n in output.items() if holdings.definition(registry,key).warehouse_counted)
    return holdings.stock_size(stock,registry)+needed<=sect.capacity_source(state,registry)['effective']


class AlchemyApplication(WorkApplication):
    start_commands=('production_start','alchemy_start')

    def __init__(self,store,registry,clock):
        for key in recipes.recipe_ids(registry):recipes.definition(registry,key)
        super().__init__(store,registry,clock)

    def _prepare_start(self,state,p,*,command_name='production_start'):
        if command_name=='alchemy_start':
            if set(p)!={'building_id','recipe_id'}:raise ValidationError('exact alchemy intent required')
            d=recipes.definition(self.registry,p['recipe_id'])
            # Selected minimal recipe has no unmet story/realm dependency. No new unlock authority.
            if d.unlock_floor or d.unlock_realm:raise ValidationError('alchemy progression evaluation deferred')
            p={**p,'unlock_floor':0,'unlock_realm':0}
        return super()._prepare_start(state,p,command_name=command_name)

    def _start_domains(self,state,production,stock,job_id,p):
        job=production['jobs'][p['building_id']]
        if p['recipe_id'] in recipes.recipe_ids(self.registry) and any(holdings.definition(self.registry,k).warehouse_counted for k in jobs.outputs(job,self.registry)):
            if not _capacity_allows(state,self.registry,stock,production):raise ValidationError('alchemy output capacity unavailable at start')
        return super()._start_domains(state,production,stock,job_id,p)

    def query_recipes(self,save_id):
        self.query(save_id)
        return tuple(recipes.requirements(self.registry,key) for key in recipes.recipe_ids(self.registry))

    def query_alchemy(self,save_id,building_id):
        state=self.query(save_id)
        return self.project_alchemy(state,building_id)

    def project_alchemy(self,state,building_id):
        """Pure existing admission/query projection; aggregate views share one snapshot."""
        row=buildings.get_building(state.domains['sect'],self.registry,building_id)
        cap=work.capability(state.domains['disciples'],self.registry,building_id)
        production=state.domains['production'];job=production['jobs'].get(building_id)
        projected=[]
        for key in recipes.recipe_ids(self.registry):
            d=recipes.definition(self.registry,key);reasons=[];inputs={};outputs={}
            if row['definition_id']!=d.building_kind:reasons.append('WRONG_BUILDING')
            if row['level']<d.min_level:reasons.append('BUILDING_NOT_READY')
            if not cap['workers']:reasons.append('NO_ASSIGNED_WORKERS')
            if job is not None and job['status']!='COMPLETE':reasons.append('BUILDING_BUSY')
            if state.time['pending'] is not None:reasons.append('PENDING_SETTLEMENT')
            if d.unlock_floor or d.unlock_realm:reasons.append('PROGRESSION_DEFERRED')
            if cap['workers'] and row['level']>=d.min_level:
                inputs={k:n*cap['workers'] for k,n in d.inputs}
                outputs=jobs.outputs({'recipe_id':key,'yield_milli':jobs.yield_for_level(cap['worker_power_milli'],row['level'])},self.registry)
                if any(state.domains['inventory']['holdings'].get(k,0)<n for k,n in inputs.items()):reasons.append('INSUFFICIENT_INPUTS')
                else:
                    stock,_=operations.consume(state.domains['inventory'],self.registry,inputs)
                    if not _capacity_allows(state,self.registry,stock,production,outputs):reasons.append('INVENTORY_CAPACITY')
            projected.append({**recipes.requirements(self.registry,key),'batch_inputs':inputs,'batch_outputs':outputs,
                              'can_start':not reasons,'blocking_reasons':reasons})
        view=recipes.project_job(production,self.registry,building_id,state.time['sim_time_ms']) if job is None or job['recipe_id'] in recipes.recipe_ids(self.registry) else {'status':'OTHER_PRODUCTION','job':None}
        return freeze_json({'building_id':building_id,'simulation_time_ms':state.time['sim_time_ms'],
                            'pending':state.time['pending'] is not None,'recipes':projected,'current':view})

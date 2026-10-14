"""@module application/danding
@purpose Single-snapshot playable slice read model and narrow existing command entry.
@depends application/alchemy,memory,settlement,sect; Systems/Core/Data
@usedBy transport/danding via injected Application factory; tests/transport/test_danding
@see ./INDEX.md
"""
from src.core.time.config import OFFLINE_CAP_MS
from dataclasses import asdict, replace
from src.application.alchemy import AlchemyApplication, new_state
from src.application.memory import Command
from src.application.settlement import SettlementRequest
from src.application import sect
from src.core.state.envelope import freeze_json
from src.core.time.model import Continuation
from src.core.validation import ValidationError, NotFoundError
from src.systems.sect import buildings
from src.systems.disciples import work
from src.systems.inventory import holdings, operations
from src.data.registry import DefinitionKey


class SliceRequestError(ValidationError):
    """Malformed transport envelope; distinguish from a valid rejected Domain intent."""


def envelope(save_id,body,extra):
    fields={'protocol_version','save_id','request_id','generation','expected_revision',extra}
    if (type(body) is not dict or set(body)!=fields or type(body['protocol_version']) is not int or
        body['protocol_version']!=1 or body['save_id']!=save_id):
        raise SliceRequestError('invalid private protocol envelope')


def target(state):
    rows=[k for k,v in state.domains['sect']['buildings'].items() if v['definition_id']=='alchemy']
    if len(rows)!=1:raise ValidationError('slice requires one Danding instance')
    return rows[0]


def worker(state):
    rows=[k for k,v in state.domains['disciples']['groups'].items() if v['definition_id']=='ordinary_alchemy']
    if len(rows)!=1:raise ValidationError('slice requires the existing alchemy work source')
    return rows[0]


def initial_slice(registry, *, last_settled_at_ms):
    """Explicit, once-only scenario setup. Uses Domain owners; no refill endpoint."""
    state=new_state(registry,last_settled_at_ms=last_settled_at_ms)
    stock,result=operations.grant(state.domains['inventory'],registry,{'herb':30},
                                  capacity=sect.capacity_source(state,registry)['effective'])
    if any(result['discarded'].values()):raise ValidationError('initial scenario does not fit')
    assigned=work.assign(state.domains['disciples'],registry,worker(state),target(state),1)
    result=replace(state,domains={**state.domains,'inventory':stock,'disciples':assigned})
    from src.application.sect_economy import initialize
    return initialize(result,registry)


def resource_category(definition):
    """Read-model grouping of existing resource identities; no new item definitions."""
    category=getattr(definition,'category',None)
    if category in ('herb','pill','resource','equipment','other'):return category
    key=definition.machine_id
    if key=='pill' or key.startswith('pill_') or key.endswith('_pill'):return 'pill'
    if key in ('herb','rare_herb','dewleaf','moonleaf','divine_leaf',
               'material_1_1','material_2_1','material_3_0','material_4_1'):return 'herb'
    return 'resource'


class DandingApplication(AlchemyApplication):
    def history(self,save_id,kind,**kwargs):
        from src.application.history import details
        return details(self,save_id,kind,**kwargs)
    def view(self,save_id):
        return self.project_view(self.query(save_id))

    def project_view(self,state):
        # All following fields come from this validated snapshot.
        building_id=target(state);row=buildings.get_building(state.domains['sect'],self.registry,building_id)
        alchemy=self.project_alchemy(state,building_id)
        group_id=worker(state);group=state.domains['disciples']['groups'][group_id]
        assigned=state.domains['disciples']['assignments'].get(group_id,{}).get(building_id,0)
        allocated=sum(work.allocations(state.domains['disciples'],group_id).values())
        current=alchemy['current'];job=current['job']
        resource_ids=set(state.domains['inventory']['holdings'])
        for recipe in alchemy['recipes']:
            resource_ids.update(recipe['inputs_per_worker']);resource_ids.update(recipe['outputs_per_base_worker'])
        inventory={key:{'name':self.registry.lookup(DefinitionKey('resources',key)).display_name,
                        'quantity':holdings.get_quantity(state.domains['inventory'],self.registry,key)} for key in sorted(resource_ids)}
        held={}
        for key,quantity in holdings.project(state.domains['inventory'],self.registry).items():
            definition=holdings.definition(self.registry,key)
            held[key]={'resource_id':key,'name':definition.display_name,'quantity':quantity,
                       'grade':definition.grade,'tier':definition.tier,'capacity_counted':definition.warehouse_counted,
                       'category':resource_category(definition)}
        building_rows={}
        for identity,item in sorted(state.domains['sect']['buildings'].items()):
            building_rows[identity]={'instance_id':identity,**item,
                'name':buildings.definition(self.registry,item['definition_id']).display_name,
                'slot_capacity':buildings.work_slots(state.domains['sect'],self.registry,identity),
                **work.project(state.domains['disciples'],self.registry,identity)}
        disciples=state.domains['disciples'];groups=[]
        for identity,item in sorted(disciples['groups'].items()):
            assignments=disciples['assignments'].get(identity,{})
            claims=work.allocations(disciples,identity)
            working=sum(c['workers'].get(identity,0) for c in disciples['commitments'].values())
            occupied=sum(claims.values())
            groups.append({'instance_id':identity,**item,
                'name':work.group_definition(self.registry,item['definition_id']).display_name,
                'assignments':[{'building_id':target_id,'name':building_rows[target_id]['name'],'count':count}
                               for target_id,count in sorted(assignments.items())],
                'allocations':claims,'assigned_count':sum(assignments.values()),
                'working_count':working,'occupied_count':occupied,'available_count':item['count']-occupied})
        capacity=sect.capacity_source(state,self.registry)
        capacity={**capacity,'used':holdings.stock_size(state.domains['inventory'],self.registry)}
        return freeze_json({'protocol_version':1,'save_schema_version':state.save_schema_version,'data_schema_version':state.data_schema_version,
            'content_version':state.content_version,'save_id':state.save_id,'generation':state.generation,'revision':state.revision,
            'building':{'instance_id':building_id,'name':buildings.definition(self.registry,row['definition_id']).display_name,
                        'level':row['level'],'busy':job is not None and job['status']!='COMPLETE'},
            'alchemy':alchemy,'inventory':inventory,'inventory_items':list(held.values()),
            'holdings':held,'buildings':building_rows,
            'disciples':{'groups':groups,'commitments':disciples['commitments']},'capacity':capacity,
            'work':{**work.project(state.domains['disciples'],self.registry,building_id),
                    'slot_capacity':buildings.work_slots(state.domains['sect'],self.registry,building_id),
                    'can_assign':not assigned and allocated<group['count'] and row['level']>=1,
                    'can_unassign':bool(assigned)},
            'time':{'offline_cap_ms':OFFLINE_CAP_MS,'simulation_time_ms':state.time['sim_time_ms'],'day_length_ms':state.time['day_length_ms'],
                    'pending':state.time['pending'] is not None,
                    **({'from_sim_ms':state.time['pending']['from_sim_ms'],'target_sim_ms':state.time['pending']['target_sim_ms'],
                        'offline_duration_ms':state.time['pending']['accepted_ms']+state.time['pending']['discarded_ms'],
                        'settlement_duration_ms':state.time['pending']['accepted_ms']} if state.time['pending'] else {}),
                    'continuation':asdict(Continuation.for_state(state)) if state.time['pending'] is not None else None}})

    def act(self,save_id,body):
        """Versioned private intent; server resolves the single scenario target/worker."""
        envelope(save_id,body,'command')
        command=body['command']
        if (type(command) is not dict or set(command)!={'name','version','payload'} or
            type(command['version']) is not int or command['version']!=1 or command['payload']!={}):
            raise SliceRequestError('invalid slice command')
        state=self.query(save_id);building_id=target(state);name=command['name']
        if name=='alchemy_start':payload={'building_id':building_id,'recipe_id':'pill'}
        elif name=='work_assign':payload={'worker_id':worker(state),'building_id':building_id,'count':1}
        elif name=='work_unassign':payload={'worker_id':worker(state),'building_id':building_id}
        else:raise NotFoundError('unknown slice command')
        try:request=Command(save_id,body['generation'],body['expected_revision'],body['request_id'],name,payload)
        except ValidationError as exc:raise SliceRequestError('invalid command envelope') from exc
        return self.execute(request)

    def advance(self,save_id,body):
        envelope(save_id,body,'continuation')
        c=body['continuation']
        try:
            if c is not None:
                if type(c) is not dict or set(c)!=set(Continuation.__dataclass_fields__):raise ValidationError('invalid continuation')
                c=Continuation(**c)
            request=SettlementRequest(save_id,body['generation'],body['expected_revision'],body['request_id'],getattr(self,'settlement_max_events',32),c)
        except ValidationError as exc:raise SliceRequestError('invalid settlement envelope') from exc
        return self.settle(request)

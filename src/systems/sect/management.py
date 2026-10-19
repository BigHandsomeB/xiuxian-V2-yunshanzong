"""Recruitment, housing and meal state on the existing simulation axis."""
from collections.abc import Mapping
from src.core.state.envelope import freeze_json,thaw_json
from src.core.time.model import Event,SimulationDomain
from src.core.validation import ValidationError,integer
from src.data.economy.sect_rules import settings
from src.systems.disciples import work
from src.systems.sect.rules import development

def config(registry):return settings(registry)['management']
def initial(registry):
    return freeze_json({'recruit':None,'supply':{'enabled':False,'reserve':config(registry)['meal_reserve_default'],'effect_until_ms':0,'wake':None,'tick_ready':False},'log':[],'material_reserves':{}})
def housing(state,registry):
    cfg=config(registry);people=sum(r['count'] for r in state.domains['disciples']['groups'].values())
    beds=sum(r['level']*cfg['housing_beds_per_level'] for r in state.domains['sect']['buildings'].values() if r['definition_id']=='house')
    rank=development(state.domains['sect'],registry,state.domains.get('dungeon',{}).get('cleared_floor',0))['level']
    limit=min(beds,rank*cfg['population_per_sect_level']);order=state.domains['sect_management']['recruit'];reserved=order['count'] if order else 0
    occupied=sum(sum(work.allocations(state.domains['disciples'],gid).values()) for gid in state.domains['disciples']['groups'])
    return {'people':people,'beds':beds,'limit':limit,'reserved':reserved,'available':max(0,limit-people-reserved),'idle':people-occupied,'occupied':occupied}
def validate(p,registry):
    if not isinstance(p,Mapping) or set(p)-{'commerce','activities','restock','exploration','story'}!={'recruit','supply','log','material_reserves'}:raise ValidationError('invalid sect management partition')
    if 'story' in p:
        from .story import validate as validate_story
        validate_story(p['story'])
    if 'exploration' in p:
        from .exploration import validate as validate_exploration
        validate_exploration(p['exploration'],registry)
    if 'restock' in p:
        from .restock import validate as validate_restock
        validate_restock(p['restock'],registry)
    if 'activities' in p:
        from .activities import validate as validate_activities
        validate_activities(p['activities'],registry)
    if 'commerce' in p:
        from .commerce import validate as validate_commerce
        validate_commerce(p['commerce'],registry)
    if not isinstance(p['material_reserves'],Mapping):raise ValidationError('material reserves object required')
    for key,n in p['material_reserves'].items():
        from src.data.economy.market import settings as market_settings
        if key not in market_settings(registry)['items']:raise ValidationError('unknown protected material')
        integer(n,'material reserve')
    order=p['recruit']
    if order is not None:
        if not isinstance(order,Mapping) or set(order)!={'order_id','event_id','group_id','count','started_ms','due_ms','ready'}:raise ValidationError('invalid recruitment order')
        for key in ('count','started_ms','due_ms'):integer(order[key],key,1 if key=='count' else 0)
        if order['count']>config(registry)['max_recruit_count'] or order['due_ms']!=order['started_ms']+config(registry)['recruit_duration_ms']*order['count'] or type(order['ready']) is not bool:raise ValidationError('recruitment deadline/count invalid')
        if any(type(order[k]) is not str for k in ('order_id','event_id','group_id')):raise ValidationError('recruit identities required')
    s=p['supply']
    if not isinstance(s,Mapping) or set(s)!={'enabled','reserve','effect_until_ms','wake','tick_ready'} or type(s['enabled']) is not bool or type(s['tick_ready']) is not bool:raise ValidationError('invalid supply policy')
    integer(s['reserve'],'meal reserve');integer(s['effect_until_ms'],'meal expiry')
    if s['wake'] is not None:
        if not isinstance(s['wake'],Mapping) or set(s['wake'])!={'event_id','due_ms'} or type(s['wake']['event_id']) is not str:raise ValidationError('invalid supply event')
        integer(s['wake']['due_ms'],'meal due')
        if not s['enabled'] or s['wake']['due_ms']!=s['effect_until_ms']:raise ValidationError('meal event/expiry mismatch')
    if not isinstance(p['log'],(list,tuple)) or len(p['log'])>config(registry)['log_limit'] or any(not isinstance(x,Mapping) or set(x)!={'operation','count','sim_ms'} or x['operation'] not in ('RECRUIT','MEAL') or type(x['count']) is not int or x['count']<1 or type(x['sim_ms']) is not int or x['sim_ms']<0 for x in p['log']):raise ValidationError('invalid management audit')
    return p
def simulation(registry):
    def events(p):
        rows=[];r=p['recruit'];w=p['supply']['wake']
        if r and not r['ready']:rows.append(Event(r['event_id'],'sect_management',r['due_ms'],3,{'kind':'recruit'}))
        if w:rows.append(Event(w['event_id'],'sect_management',w['due_ms'],4,{'kind':'meal'}))
        restock_wake=p.get('restock',{}).get('wake')
        if restock_wake:rows.append(Event(restock_wake['event_id'],'sect_management',restock_wake['due_ms'],5,{'kind':'restock'}))
        return tuple(rows)
    def apply(p,event):
        if event.payload['kind']=='recruit':p['recruit']['ready']=True
        elif event.payload['kind']=='restock':
            wake=p['restock']['wake']
            if wake['next_event_id'] is None:raise ValidationError('restock successor required')
            p['restock']['wake']={'event_id':wake['next_event_id'],'next_event_id':None,'due_ms':event.due_sim_ms+1}
        else:p['supply']['wake']=None;p['supply']['tick_ready']=True
    return SimulationDomain(events,apply,None,lambda p:validate(p,registry))

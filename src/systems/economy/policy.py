"""Persisted conservative production policy, no inventory or clock authority."""
from collections.abc import Mapping
from src.core.state.envelope import freeze_json,thaw_json
from src.core.validation import ValidationError,integer
from src.core.time.model import Event,SimulationDomain
from src.data.registry import DefinitionKey

MODES=('OFF','REVIEW','SELL','SALVAGE')
def initial():return freeze_json({'production':{},'equipment':{'mode':'OFF','min_quality':'rare','keep_stat':'attack_milli','min_stat':100000,'keep_upgrades':True},'epoch':0,'wake':None,'log':[]})
def validate(p,registry):
    if not isinstance(p,Mapping) or not {'production','equipment','epoch','wake','log'}<=set(p) or bool(set(p)-{'production','equipment','epoch','wake','log','material_overflow','overflow_log','recipe_production'}) or not isinstance(p['production'],Mapping):raise ValidationError('invalid automation policy')
    if 'material_overflow' in p and type(p['material_overflow']) is not bool:raise ValidationError('invalid overflow switch')
    from src.data.economy.sect_rules import settings
    cfg=settings(registry)
    if 'overflow_log' in p:
        if not cfg or not isinstance(p['overflow_log'],(list,tuple)) or len(p['overflow_log'])>cfg['overflow_audit_limit']:raise ValidationError('invalid overflow audit')
        for row in p['overflow_log']:
            if set(row)!={'battle_id','amounts','coins'} or type(row['battle_id']) is not str:raise ValidationError('invalid overflow receipt')
            integer(row['coins'],'converted coins')
            for key,n in row['amounts'].items():
                if key not in cfg['material_caps']:raise ValidationError('unknown overflow material')
                integer(n,'converted quantity',1)
    integer(p['epoch'],'policy epoch')
    all_production=list(p['production'].items())
    queues=p.get('recipe_production',{})
    if not isinstance(queues,Mapping):raise ValidationError('recipe production must be an object')
    for bid,queue in queues.items():
        if type(bid) is not str or not isinstance(queue,Mapping) or set(queue)!={'recipes','last_recipe_id'} or not isinstance(queue['recipes'],Mapping):raise ValidationError('invalid recipe production queue')
        if queue['last_recipe_id'] is not None:registry.lookup(DefinitionKey('production',queue['last_recipe_id']))
        for rid,row in queue['recipes'].items():
            if not isinstance(row,Mapping) or row.get('recipe_id')!=rid:raise ValidationError('recipe policy key mismatch')
            all_production.append((bid,row))
    for building,row in all_production:
        if type(building) is not str or not isinstance(row,Mapping) or set(row)!={'enabled','recipe_id','target','reserves','max_consumption'}:raise ValidationError('invalid production policy')
        if type(row['enabled']) is not bool:raise ValidationError('policy enabled must be boolean')
        registry.lookup(DefinitionKey('production',row['recipe_id']));integer(row['target'],'target',1)
        if row['target']>10000:raise ValidationError('生产目标不能超过10000')
        if not isinstance(row['reserves'],Mapping):raise ValidationError('reserve object required')
        for key,n in row['reserves'].items():registry.lookup(DefinitionKey('resources',key));integer(n,'reserve')
        integer(row['max_consumption'],'maximum batch consumption')
    e=p['equipment']
    if not isinstance(e,Mapping) or set(e)!={'mode','min_quality','keep_stat','min_stat','keep_upgrades'} or e['mode'] not in MODES or e['min_quality'] not in ('white','green','blue','rare') or e['keep_stat'] not in ('attack_milli','armor_milli','max_hp_milli') or type(e['keep_upgrades']) is not bool:raise ValidationError('invalid equipment policy')
    integer(e['min_stat'],'minimum retained stat')
    if p['wake'] is not None:
        w=p['wake']
        if not isinstance(w,Mapping) or set(w)!={'event_id','due_ms'} or type(w['event_id']) is not str:raise ValidationError('invalid dispatch wake')
        integer(w['due_ms'],'dispatch due')
    if not isinstance(p['log'],(list,tuple)) or len(p['log'])>20:raise ValidationError('bounded automation log required')
    for row in p['log']:
        if not isinstance(row,Mapping) or set(row)!={'kind','identity','message'} or any(type(v) is not str for v in row.values()):raise ValidationError('invalid automation audit row')
    return p

def set_production(p,registry,building_id,row):
    r=thaw_json(p)
    if isinstance(row,Mapping) and set(row)=={'enabled','recipe_id','target'}:
        row={**row,'reserves':{},'max_consumption':0}
    if not isinstance(row,Mapping) or type(row.get('recipe_id')) is not str:raise ValidationError('请选择生产配方与完整策略')
    if building_id in r.get('recipe_production',{}):r['recipe_production'][building_id]['recipes'][row['recipe_id']]=row
    else:r['production'][building_id]=row
    validate(r,registry);return freeze_json(r)
def set_equipment(p,registry,row):
    r=thaw_json(p);r['equipment']=row;r['epoch']+=1;validate(r,registry);return freeze_json(r)
def record(p,kind,identity,message):
    r=thaw_json(p);r['log']=(r['log']+[{'kind':kind,'identity':identity,'message':message}])[-20:];return freeze_json(r)
def simulation(registry):
    def events(p):
        w=p['wake'];return () if w is None else (Event(w['event_id'],'automation',w['due_ms'],1,{}),)
    def apply(p,event):
        if not p['wake'] or p['wake']['event_id']!=event.event_id:raise ValidationError('dispatch event mismatch')
        p['wake']=None
    return SimulationDomain(events,apply,validate=lambda p:validate(p,registry))


def recipe_queue(p,building_id,recipe_id=None):
    """Materialize legacy policy once, preserving its exact limits and enabled state."""
    r=thaw_json(p);queues=r.setdefault('recipe_production',{})
    if building_id not in queues:
        old=r['production'].get(building_id)
        queues[building_id]={'recipes':{old['recipe_id']:dict(old)} if old else {},'last_recipe_id':None}
    if recipe_id is not None:
        queues[building_id]['recipes'].setdefault(recipe_id,{'enabled':True,'recipe_id':recipe_id,'target':30,'reserves':{},'max_consumption':0})
    return freeze_json(r)

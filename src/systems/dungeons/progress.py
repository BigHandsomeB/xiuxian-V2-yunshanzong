"""Persistent high-water progress; unlock only after an atomic, explicit reward claim."""
from collections.abc import Mapping
from src.core.state.envelope import freeze_json,thaw_json
from src.core.time.model import Event,SimulationDomain
from src.core.validation import ValidationError,ConflictError,integer
from src.data.registry import DefinitionKey
from src.data.dungeons.definitions import DungeonDefinition,ID
from src.data.dungeons import expeditions, catalog

def definition(registry,dungeon_id=ID):
    d=registry.lookup(DefinitionKey('dungeons',dungeon_id))
    if not isinstance(d,DungeonDefinition):raise ValidationError('dungeon definition required')
    return d

INTERVAL_MS=2000
def initial():return freeze_json({'cleared_floor':0,'auto':{'enabled':False,'mode':'push','floor':1,'reason':None,'wake':None,'tick_ready':False,'steps':0,'wins':0,'stop_sim_ms':None}})
def validate(p,registry):
    definition(registry)
    if not isinstance(p,Mapping) or not {'cleared_floor','auto'}<=set(p) or set(p)-{'cleared_floor','auto','selected_id','progress'}:raise ValidationError('exact dungeon progress required')
    integer(p['cleared_floor'],'cleared floor')
    if p['cleared_floor']>100:raise ValidationError('dungeon progress out of range')
    definition(registry,selected(p))
    extra=p.get('progress',{})
    if not isinstance(extra,Mapping) or set(extra)-(set(catalog.registered_ids(registry))-{ID}):raise ValidationError('invalid expedition progress')
    for did,n in extra.items():
        d=definition(registry,did);integer(n,'expedition cleared floor')
        if n>len(d.encounters):raise ValidationError('expedition progress out of range')
    require_dungeon(p,registry,selected(p))
    for did,n in extra.items():
        if n:require_dungeon(p,registry,did)
    a=p['auto']
    if not isinstance(a,Mapping) or not {'enabled','mode','floor','reason','wake','tick_ready','steps','wins'}<=set(a) or set(a)-{'enabled','mode','floor','reason','wake','tick_ready','steps','wins','floor_count','next_floor','stop_sim_ms'} or type(a['enabled']) is not bool or type(a['tick_ready']) is not bool or a['mode'] not in ('push','farm') or a['reason'] not in (None,'DEFEATED','STORAGE_FULL','COMPLETED','LEGACY_BATTLE'):raise ValidationError('invalid dungeon auto policy')
    if a.get('stop_sim_ms') is not None:integer(a['stop_sim_ms'],'auto stop time')
    integer(a['floor'],'farm floor',1);integer(a['steps'],'auto steps');integer(a['wins'],'auto wins')
    count=a.get('floor_count',1);cursor=a.get('next_floor',a['floor'])
    integer(count,'farm floor count',1);integer(cursor,'next farm floor',1)
    if a['floor']+count-1>100 or not a['floor']<=cursor<a['floor']+count:raise ValidationError('invalid farm range')
    if a['floor']>100:raise ValidationError('farm floor out of range')
    if not a['enabled'] and (a['wake'] is not None or a['tick_ready']):raise ValidationError('disabled auto cannot schedule combat')
    if a['wake'] is not None:
        w=a['wake']
        if not isinstance(w,Mapping) or not {'event_id','next_event_id','due_ms'}<=set(w) or set(w)-{'event_id','next_event_id','due_ms','interval_ms'} or type(w['event_id']) is not str or (w['next_event_id'] is not None and type(w['next_event_id']) is not str):raise ValidationError('invalid auto wake')
        integer(w['due_ms'],'auto due')
        if 'interval_ms' in w:
            integer(w['interval_ms'],'attack interval',1000)
            if w['interval_ms']>INTERVAL_MS:raise ValidationError('unsupported attack interval')
def selected(p):return p.get('selected_id',ID)
def cleared(p,dungeon_id=ID):return p['cleared_floor'] if dungeon_id==ID else p.get('progress',{}).get(dungeon_id,0)
def floor_of(registry,eid):
    did=expeditions.owner(registry,eid)
    if did is None:return None
    d=definition(registry,did)
    return (d.encounters.index(eid)+1) if eid in d.encounters else d.legacy_encounters.index(eid)+1

def unlocked(p,registry,dungeon_id):
    definition(registry,dungeon_id)
    if dungeon_id==ID:return True
    condition=expeditions.content(dungeon_id)['unlock']
    return cleared(p,condition['dungeon_id'])>=condition['cleared_floor']

def require_dungeon(p,registry,dungeon_id):
    if not unlocked(p,registry,dungeon_id):
        c=expeditions.content(dungeon_id)['unlock'];name=definition(registry,c['dungeon_id']).display_name
        raise ConflictError(f"需通关{name}{c['cleared_floor']}层")

def choose(p,registry,dungeon_id):
    validate(p,registry);require_dungeon(p,registry,dungeon_id)
    if p['auto']['enabled']:raise ConflictError('请先停止挂机再切换副本')
    r=thaw_json(p);r['selected_id']=dungeon_id
    # The previous farm floor belongs to the previous dungeon; do not silently reuse it.
    if selected(p)!=dungeon_id:r['auto'].update(floor=1,floor_count=1,next_floor=1,mode='push',reason=None)
    validate(r,registry);return freeze_json(r)

def next_encounter(p,registry,dungeon_id=None):
    validate(p,registry);did=dungeon_id or selected(p);d=definition(registry,did)
    return d.encounters[min(cleared(p,did),len(d.encounters)-1)]
def require_unlocked(p,registry,eid):
    validate(p,registry);did=expeditions.owner(registry,eid);f=floor_of(registry,eid)
    if did is None or f is None:raise ConflictError('该层尚未解锁，请先领取上一层战利品')
    require_dungeon(p,registry,did)
    if f>min(cleared(p,did)+1,len(definition(registry,did).encounters)):raise ConflictError('该层尚未解锁，请先领取上一层战利品')
    return eid

def claimed(p,registry,b):
    validate(p,registry);did=expeditions.owner(registry,b['encounter_id']);f=floor_of(registry,b['encounter_id'])
    if f is None:return p
    if b['status']!='SETTLED':raise ValidationError('floor progress requires settled reward')
    require_unlocked(p,registry,b['encounter_id']);r=thaw_json(p)
    if did==ID:r['cleared_floor']=max(p['cleared_floor'],f)
    else:r.setdefault('progress',{})[did]=max(cleared(p,did),f)
    return freeze_json(r)

def view(p,registry,b=None,dungeon_id=None):
    validate(p,registry);did=dungeon_id or selected(p);d=definition(registry,did);total=len(d.encounters);high=cleared(p,did)
    f=floor_of(registry,b['encounter_id']) if b and expeditions.owner(registry,b['encounter_id'])==did else None
    condition=None if did==ID else dict(expeditions.content(did)['unlock'])
    return {'id':did,'name':d.display_name,'total_floors':total,'cleared_floor':high,'completed':high==total,'next_floor':min(high+1,total),'next_encounter_id':next_encounter(p,registry,did),'current_floor':f,'tier':d.tiers[f-1] if f else None,'elite_floors':[i+1 for i,t in enumerate(d.tiers) if t=='elite'],'boss_floor':total,'unlocked':unlocked(p,registry,did),'unlock_condition':condition,'auto':{k:v for k,v in p['auto'].items() if k not in ('wake','tick_ready')},'attack_interval_ms':INTERVAL_MS}

def directory(p,registry):
    return [view(p,registry,dungeon_id=did) for did in catalog.registered_ids(registry)]


def set_auto(p,registry,enabled,mode,floor,floor_count=None):
    validate(p,registry)
    if type(enabled) is not bool or mode not in ('push','farm'):raise ValidationError('请选择完整挂机策略')
    integer(floor,'farm floor',1)
    if floor>max(1,cleared(p,selected(p))):raise ValidationError('只能重复刷已通关的楼层')
    count=1 if floor_count is None else floor_count
    integer(count,'farm floor count',1)
    if mode=='farm' and floor_count is not None and floor+count-1>cleared(p,selected(p)):raise ValidationError('循环范围只能包含已通关楼层')
    if enabled:require_dungeon(p,registry,selected(p))
    r=thaw_json(p);r['auto'].update(enabled=enabled,mode=mode,floor=floor,floor_count=count,next_floor=floor,reason=None,wake=None,tick_ready=False)
    if 'stop_sim_ms' in r['auto']:r['auto']['stop_sim_ms']=None
    validate(r,registry);return freeze_json(r)

def simulation(registry):
    def events(p):
        w=p['auto']['wake'];return () if w is None else (Event(w['event_id'],'dungeon',w['due_ms'],2,{}),)
    def apply(p,event):
        a=p['auto'];w=a['wake']
        if not w or event.event_id!=w['event_id'] or w['next_event_id'] is None:raise ValidationError('auto event mismatch')
        # The next ID is allocated before settlement: the Core sees the next boundary
        # and cannot jump over the remaining offline combat window.
        a['wake']={'event_id':w['next_event_id'],'next_event_id':None,'due_ms':w['due_ms']+w.get('interval_ms',INTERVAL_MS),**({'interval_ms':w['interval_ms']} if 'interval_ms' in w else {})};a['tick_ready']=True
    return SimulationDomain(events,apply,validate=lambda p:validate(p,registry))

"""Targeted permanent training stats and shared-combat wave rules; no clock or storage."""
from collections.abc import Mapping
from dataclasses import replace
from src.core.state.envelope import thaw_json
from src.core.validation import ValidationError,integer
from src.core.time.model import Event,SimulationDomain
from src.data.registry import DefinitionKey
from src.data.economy.sect_rules import settings
from src.systems.combat import battle

from src.data.cultivation.attribute_trials import STATS,NAMES
COMMANDS=('attribute_trial_start','attribute_trial_stop')

def config(registry):return (settings(registry) or {}).get('attribute_trials')
def initial():
    return {'running':False,'stat':None,'wave':1,'battle':None,'wake':None,'tick_ready':False,'highest':{k:0 for k in STATS},'wins':0,'reason':None,'latest_xp':0}
def part(growth):return growth.get('attribute_trial',initial())
def running(growth):return bool(growth.get('attribute_trial',{}).get('running',False))
def threshold(c,n):return n*c['first_level_xp']+c['level_cost_growth']*n*(n-1)//2

def level(c,xp):
    # Integer binary search works for any configured positive growth, no rounding drift.
    lo,hi=0,c['max_level']
    while lo<hi:
        mid=(lo+hi+1)//2
        if threshold(c,mid)<=xp:lo=mid
        else:hi=mid-1
    return lo

def bonuses(growth,registry):
    c=config(registry)
    return {k:level(c,growth.get('trial_attributes',{}).get(k,0))*c['gains'][k] for k in STATS} if c else {}


def validate_growth(growth,registry):
    c=config(registry);xp=growth.get('trial_attributes',{})
    if not isinstance(xp,Mapping) or set(xp)-set(STATS):raise ValidationError('invalid trial attribute XP')
    for k,n in xp.items():
        integer(n,'attribute XP')
        if not c or n>threshold(c,c['max_level']):raise ValidationError('attribute XP exceeds configured cap')
    if 'attribute_trial' not in growth:return
    p=growth['attribute_trial']
    if not c or not isinstance(p,Mapping) or set(p)!=set(initial()):raise ValidationError('invalid attribute trial fields')
    if type(p['running']) is not bool or type(p['tick_ready']) is not bool or p['stat'] not in (None,*STATS) or p['reason'] not in (None,'STOPPED','DEFEATED','COMPLETED','MAXED'):raise ValidationError('invalid attribute trial state')
    integer(p['wave'],'trial wave',1);integer(p['wins'],'trial wins');integer(p['latest_xp'],'latest trial XP')
    if p['wave']>c['max_wave'] or not isinstance(p['highest'],Mapping) or set(p['highest'])!=set(STATS):raise ValidationError('trial wave bounds')
    for n in p['highest'].values():
        integer(n,'trial highest wave')
        if n>c['max_wave']:raise ValidationError('trial unlock out of bounds')
    if p['stat'] and p['wave']>min(c['max_wave'],p['highest'][p['stat']]+1):raise ValidationError('trial wave locked')
    if p['running'] and p['stat'] is None:raise ValidationError('running trial needs attribute')
    if not p['running'] and (p['wake'] is not None or p['tick_ready']):raise ValidationError('stopped trial has scheduled work')
    w=p['wake']
    if w is not None:
        if not isinstance(w,Mapping) or set(w)!={'event_id','next_event_id','due_ms','interval_ms'}:raise ValidationError('invalid trial wake')
        if not isinstance(w['event_id'],str) or not w['event_id']:raise ValidationError('trial event ID required')
        for k in ('event_id','next_event_id'):
            if w[k] is not None and not isinstance(w[k],str):raise ValidationError('invalid trial event identity')
        integer(w['due_ms'],'trial event time');integer(w['interval_ms'],'trial interval',1000)
        if w['interval_ms']>2000:raise ValidationError('trial attack interval out of bounds')

def snapshot(growth):
    # Never embed an active trial/battle recursively inside its own growth snapshot.
    return {k:thaw_json(v) for k,v in growth.items() if k!='attribute_trial'}

class TrialRegistry:
    """Read-only scaled monster view; all player skills and combat code stay shared."""
    def __init__(self,registry,wave):
        self.base=registry;c=config(registry)
        did=registry.lookup(DefinitionKey('dungeons','thorn_path'));self.encounter_id=did.encounters[0]
        e=battle.encounter(registry,self.encounter_id);m=battle.monster(registry,e.monster_id)
        self.enemy=replace(m,base_hp_milli=m.base_hp_milli*(10000+(wave-1)*c['hp_growth_bps'])//10000,attack_milli=m.attack_milli*(10000+(wave-1)*c['attack_growth_bps'])//10000,armor_milli=m.armor_milli+(wave-1)*c['armor_growth_milli'])
    def lookup(self,key):
        return self.enemy if key==DefinitionKey('monsters',self.enemy.machine_id) else self.base.lookup(key)
    def __getattr__(self,key):return getattr(self.base,key)

def simulation(registry):
    def events(growth):
        w=part(growth)['wake'];return (Event(w['event_id'],'cultivation',w['due_ms'],2,{}),) if w else ()
    def apply(growth,event):
        p=growth['attribute_trial'];w=p['wake']
        if not p['running'] or not w or w['event_id']!=event.event_id or w['next_event_id'] is None:raise ValidationError('trial event mismatch')
        p['wake']={**w,'event_id':w['next_event_id'],'next_event_id':None,'due_ms':w['due_ms']+w['interval_ms']};p['tick_ready']=True
    return SimulationDomain(events,apply,None,lambda p:validate_growth(p,registry))

def view(growth,registry,blocked=False):
    c=config(registry)
    if not c:return None
    p=part(growth);rows=[]
    for stat in STATS:
        xp=growth.get('trial_attributes',{}).get(stat,0);n=level(c,xp);cap=threshold(c,min(c['max_level'],n+1));base=threshold(c,n)
        rows.append({'id':stat,'name':NAMES[stat]+'试炼场','level':n,'bonus':n*c['gains'][stat]/1000,'gain':c['gains'][stat]/1000,'xp':xp,'progress':xp-base,'needed':cap-base,'highest_wave':p['highest'][stat],'next_wave':min(c['max_wave'],p['highest'][stat]+1),'maxed':n==c['max_level']})
    b=p['battle'];actor=b.get('player_snapshot') if b else None;enemy=battle.effective_monster(TrialRegistry(registry,p['wave']),b) if b else None
    return {'running':p['running'],'stat':p['stat'],'wave':p['wave'],'reason':p['reason'],'wins':p['wins'],'latest_xp':p['latest_xp'],'xp_per_win':c['xp_per_first_wave']+(p['wave']-1)*c['xp_per_extra_wave'],'max_wave':c['max_wave'],'can_start':not blocked and not p['running'],'rows':rows,'battle':{'status':b['status'],'step':b['step'],'player_hp':b['player_hp_milli']/1000,'player_max_hp':actor['max_hp_milli']/1000,'enemy_hp':b['enemy_hp_milli']/1000,'enemy_max_hp':enemy.base_hp_milli/1000,'enemy_name':enemy.display_name,'enemy_asset_id':enemy.asset_id,'enemy_attack':enemy.attack_milli/1000,'enemy_armor':enemy.armor_milli/1000} if b else None}

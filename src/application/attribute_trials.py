"""Optional targeted trials on the existing transactional command/event lane."""
from dataclasses import replace
from src.core.state.envelope import thaw_json
from src.core.validation import ValidationError,ConflictError,integer
from src.core.time.world import require_running,paused
from src.systems.cultivation import attribute_trials as rules
from src.systems.combat import battle
from src.systems.combat.equipment_effects import interval
from src.application.cultivation import partition


def put(state,growth):return replace(state,domains={**state.domains,'cultivation':growth})
def blocked(state):
    b=state.domains.get('combat',{}).get('battle') or {}
    return state.domains['dungeon']['auto']['enabled'] or b.get('status') in ('ACTIVE','PLAYER_WIN')

def validate_state(state,registry):
    growth=partition(state);rules.validate_growth(growth,registry);p=rules.part(growth)
    if p['running'] and blocked(state):raise ValidationError('trial and adventure are mutually exclusive')
    w=p['wake']
    if not w and not p['battle'] and not p['running']:return state
    if p['running'] and (not w or w['next_event_id'] is None or p['tick_ready']):raise ValidationError('trial schedule incomplete')
    occupied=set()
    def event_ids(value):
        if hasattr(value,'items'):
            for key,item in value.items():
                if key in ('event_id','next_event_id') and isinstance(item,str):occupied.add(item)
                elif key!='attribute_trial':event_ids(item)
        elif isinstance(value,(list,tuple)):
            for item in value:event_ids(item)
    if w:event_ids(state.domains)
    for identity in ([w['event_id'],w['next_event_id']] if w else []):
        pieces=identity.split(':')
        try:valid=len(pieces)==4 and pieces[0]==state.save_id and int(pieces[1])==state.generation and pieces[2]=='e' and 1<=int(pieces[3])<=state.identity['event_counter']
        except ValueError:valid=False
        if not valid or identity in occupied or str(int(pieces[1]))!=pieces[1] or str(int(pieces[3]))!=pieces[3]:raise ValidationError('trial event outside allocated namespace')
        occupied.add(identity)
    if p['battle']:
        b=p['battle'];identity=b['battle_id'].split(':')
        try:valid=len(identity)==4 and identity[0]==state.save_id and 1<=int(identity[1])<=state.generation and identity[2]=='i' and 1<=int(identity[3])<=state.identity['instance_counter']
        except ValueError:valid=False
        if not valid or b['battle_id']==(state.domains.get('combat',{}).get('battle') or {}).get('battle_id') or 'attribute_trial' in b.get('growth_snapshot',{}):raise ValidationError('invalid trial battle snapshot identity')
        battle.validate({'battle':b},rules.TrialRegistry(registry,p['wave']),state.save_id)
    return state

def transition(app,state,name,payload):
    growth=thaw_json(partition(state));p=thaw_json(rules.part(growth));c=rules.config(app.registry)
    if name=='attribute_trial_stop':
        if payload:raise ValidationError('停止试炼不需要参数')
        p.update(running=False,wake=None,tick_ready=False,reason='STOPPED')
    else:
        require_running(state.time)
        if set(payload)!={'stat','wave'} or payload['stat'] not in rules.STATS:raise ValidationError('请选择属性试炼场')
        integer(payload['wave'],'trial wave',1);stat=payload['stat'];wave=payload['wave']
        if p['running'] or blocked(state):raise ConflictError('请先停止挂机并结束当前战斗，再进入属性试炼场。')
        if wave>min(c['max_wave'],p['highest'][stat]+1):raise ValidationError('该波次尚未解锁')
        if rules.level(c,growth.get('trial_attributes',{}).get(stat,0))>=c['max_level']:raise ValidationError('该属性试炼已达到当前上限')
        p.update(running=True,stat=stat,wave=wave,battle=None,wake=None,tick_ready=False,reason=None,latest_xp=0)
    growth['attribute_trial']=p
    return put(state,growth),{'operation':name,'stat':p['stat'],'wave':p['wave']}

def wake(app,state):
    if paused(state.time):return state
    growth=partition(state);p=rules.part(growth);w=p['wake']
    if not p['running'] or (w and w['next_event_id'] is not None):return state
    growth=thaw_json(growth);p=growth['attribute_trial'];n=state.identity['event_counter'];b=p['battle']
    delay=interval(b['player_snapshot'] if b and b['status']=='ACTIVE' else app.player_projection(state))
    if w is None:
        n+=2;p['wake']={'event_id':f'{state.save_id}:{state.generation}:e:{n-1}','next_event_id':f'{state.save_id}:{state.generation}:e:{n}','due_ms':state.time['sim_time_ms']+delay,'interval_ms':delay}
    else:
        n+=1;p['wake']['next_event_id']=f'{state.save_id}:{state.generation}:e:{n}';p['wake']['interval_ms']=delay
    return put(replace(state,identity={**state.identity,'event_counter':n}),growth)

def dispatch(app,state):
    growth=partition(state);p=rules.part(growth)
    if not p['running'] or not p['tick_ready']:return state
    growth=thaw_json(growth);p=growth['attribute_trial'];p['tick_ready']=False;c=rules.config(app.registry);b=p['battle']
    if not b or b['status']=='PLAYER_WIN':
        if b:p['wave']+=1
        registry=rules.TrialRegistry(app.registry,p['wave']);counter=state.identity['instance_counter']+1
        snap=rules.snapshot(growth)
        part=battle.start(battle.initial(),registry,state.save_id,f'{state.save_id}:{state.generation}:i:{counter}',registry.encounter_id,player_snapshot=app.player_projection(put(state,growth)),growth_snapshot=snap,equipment_sources=app.combat_equipment(state),artifact_snapshot=app.combat_artifact(state),equipment_snapshot=app.combat_equipment_snapshot(state))
        state=replace(state,identity={**state.identity,'instance_counter':counter});b=part['battle']
    registry=rules.TrialRegistry(app.registry,p['wave']);part=battle.attack({'battle':b},registry,state.save_id,b['battle_id']);p['battle']=thaw_json(part['battle']);b=p['battle']
    if b['status']=='PLAYER_LOSE':p.update(running=False,wake=None,reason='DEFEATED')
    elif b['status']=='PLAYER_WIN':
        stat=p['stat'];xp=growth.setdefault('trial_attributes',{});old=xp.get(stat,0);gain=c['xp_per_first_wave']+(p['wave']-1)*c['xp_per_extra_wave'];xp[stat]=min(rules.threshold(c,c['max_level']),old+gain)
        p['latest_xp']=xp[stat]-old;p['highest'][stat]=max(p['highest'][stat],p['wave']);p['wins']+=1
        growth['growth_revision']+=1
        if p['wave']==c['max_wave'] or rules.level(c,xp[stat])==c['max_level']:p.update(running=False,wake=None,reason='MAXED' if rules.level(c,xp[stat])==c['max_level'] else 'COMPLETED')
    return wake(app,put(state,growth))

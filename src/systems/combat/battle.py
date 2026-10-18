"""Single deterministic Combat authority; no time, RNG, Inventory writes or art paths."""
from collections.abc import Mapping
from dataclasses import replace
from src.data.dungeons import durability
from src.core.state.envelope import freeze_json, thaw_json
from src.core.validation import ValidationError, ConflictError, NotFoundError, integer, text
from src.data.registry import DefinitionKey
from src.data.combat.definitions import PlayerDefinition, MonsterDefinition, EncounterDefinition
from src.systems.combat import equipment_effects as effects
from src.data.dungeons.expeditions import loot_version,valid_loot_version
from src.data.combat import mechanics as effect_definitions
from src.systems.combat import mechanics

STATUSES=('ACTIVE','PLAYER_WIN','PLAYER_LOSE','ABANDONED','SETTLED')
COMMANDS=('combat_start','combat_attack','combat_abandon','combat_reward')
EVENTS=('battle_started','player_attack','enemy_attack','damage','player_hit','enemy_hit','enemy_defeated','player_defeated','battle_won','battle_lost','reward_ready','reward_settled','battle_abandoned','critical','miss','reflect','poison','lifesteal',*mechanics.EVENTS)
RULES_VERSION='attributes-v2'

def player(registry,save_id):
    d=registry.lookup(DefinitionKey('players','hero'))
    if not isinstance(d,PlayerDefinition):raise ValidationError('formal player definition required')
    # Stable save-scoped identity; the projection never creates another growing Hero.
    return freeze_json({'id':save_id+':hero','definition_id':'hero','name':d.display_name,
        'max_hp_milli':max(20000,(70+d.level*10+d.realm*25)*1000),
        'attack_milli':max(1000,(8+d.level*2+d.realm*3)*1000),'armor_milli':d.level*500,'asset_id':d.asset_id})

def encounter(registry,key):
    d=registry.lookup(DefinitionKey('encounters',key))
    if not isinstance(d,EncounterDefinition):raise ValidationError('Encounter definition required')
    return d

def monster(registry,key):
    d=registry.lookup(DefinitionKey('monsters',key))
    if not isinstance(d,MonsterDefinition):raise ValidationError('Monster definition required')
    return d

def effective_monster(registry,b):
    e=monster(registry,b['enemy_id'])
    return replace(e,base_hp_milli=e.base_hp_milli*b.get('enemy_hp_scale_bps',10000)//10000,
                   reward=tuple((k,durability.amount(v,b,k)) for k,v in e.reward))

def initial():return freeze_json({'battle':None})

def damage(attack_milli,armor_milli):
    integer(attack_milli,'attack');integer(armor_milli,'armor')
    return max(1000,attack_milli-armor_milli)

def validate(partition,registry,save_id):
    if not isinstance(partition,Mapping) or set(partition)!={'battle'}:raise ValidationError('exact combat partition required')
    b=partition['battle']
    if b is None:return
    fields={'battle_id','encounter_id','player_id','enemy_id','status','player_hp_milli','enemy_hp_milli','step','latest_events','reward_state','reward'}
    if not isinstance(b,Mapping) or not fields<=set(b) or set(b)-fields-{'player_snapshot','loot_version','rules_version','enemy_hp_scale_bps','reward_compensation_bps','visual_events_online','growth_snapshot','mechanics'}:raise ValidationError('exact battle state required')
    for key in ('enemy_hp_scale_bps','reward_compensation_bps'):
        if key in b:integer(b[key],key,10000)
    if 'visual_events_online' in b and type(b['visual_events_online']) is not bool:raise ValidationError('boolean visual event source required')
    if 'rules_version' in b and b['rules_version'] not in (RULES_VERSION,effect_definitions.VERSION):raise ValidationError('unsupported combat rules version')
    cfg=effect_definitions.settings(registry)
    if b.get('rules_version')==effect_definitions.VERSION:
        if not cfg or 'mechanics' not in b:raise ValidationError('missing effect battle state')
        mechanics.validate(b['mechanics'],cfg,b['step'])
    elif 'mechanics' in b:raise ValidationError('historical battle cannot carry new effects')
    if 'loot_version' in b and not valid_loot_version(registry,b['encounter_id'],b['loot_version']):raise ValidationError('unknown battle loot version')
    version=loot_version(registry,b['encounter_id'])
    if version and not b['encounter_id'].startswith('thorn_path_') and not valid_loot_version(registry,b['encounter_id'],b.get('loot_version')):raise ValidationError('expedition battle requires its loot version')
    d=encounter(registry,b['encounter_id']);e=effective_monster(registry,b);p=b['player_snapshot'] if 'player_snapshot' in b else player(registry,save_id)
    if 'player_snapshot' in b:validate_player_input(p,registry,save_id)
    text(b['battle_id'],'battle id')
    if b['player_id']!=p['id'] or b['enemy_id']!=e.machine_id:raise ValidationError('combat identity mismatch')
    if b['status'] not in STATUSES:raise ValidationError('unsupported battle state')
    integer(b['step'],'combat step');integer(b['player_hp_milli'],'player hp');integer(b['enemy_hp_milli'],'enemy hp')
    if b['player_hp_milli']>p['max_hp_milli'] or b['enemy_hp_milli']>e.base_hp_milli:raise ValidationError('hp outside definition bounds')
    if b['status']=='ACTIVE' and (not b['player_hp_milli'] or not b['enemy_hp_milli']):raise ValidationError('active actors must be alive')
    if b['status'] in ('PLAYER_WIN','SETTLED') and (b['enemy_hp_milli'] or not b['player_hp_milli']):raise ValidationError('win requires dead enemy and live player')
    if b['status']=='PLAYER_LOSE' and (b['player_hp_milli'] or not b['enemy_hp_milli']):raise ValidationError('loss requires player death')
    if b['reward_state']!={'PLAYER_WIN':'READY','SETTLED':'SETTLED'}.get(b['status'],'NONE'):raise ValidationError('reward state mismatch')
    expected=dict(e.reward) if b['status'] in ('PLAYER_WIN','SETTLED') else {}
    if b['reward']!=expected:raise ValidationError('reward must match immutable monster definition')
    events=b['latest_events']
    if not isinstance(events,(tuple,list)) or not 1<=len(events)<=(cfg['balance']['event_limit'] if 'mechanics' in b else 20):raise ValidationError('bounded combat facts required')
    for event in events:
        if not isinstance(event,Mapping) or set(event)-{'source_id','status_id','element','damage_kind'}!={'kind','actor','target','damage_milli','formula_damage_milli','target_hp_milli'} or event['kind'] not in EVENTS:raise ValidationError('invalid combat fact')
        if 'source_id' in event:
            if 'mechanics' not in b or not isinstance(event['source_id'],str):raise ValidationError('effect source requires versioned battle')
        if 'status_id' in event and ('mechanics' not in b or event['status_id'] not in cfg['statuses']):raise ValidationError('unknown combat status fact')
        if 'element' in event or 'damage_kind' in event:
            if 'mechanics' not in b or event.get('element') not in effect_definitions.ELEMENTS or event.get('damage_kind') not in ('direct','skill','ranged','dot','reflect','counter','extra_hit'):raise ValidationError('invalid damage presentation facts')
            if event['kind'] not in ('damage','dot','reflect','counter','extra_hit'):raise ValidationError('damage details require a damage fact')
        if event['actor'] not in ('player','enemy','battle') or event['target'] not in ('player','enemy','battle'):raise ValidationError('invalid fact actor')
        for key in ('damage_milli','formula_damage_milli','target_hp_milli'):integer(event[key],key)
        if event['damage_milli']>event['formula_damage_milli']:raise ValidationError('damage cannot exceed formula')

def fact(kind,actor='battle',target='battle',amount=0,formula=0,hp=0):
    return {'kind':kind,'actor':actor,'target':target,'damage_milli':amount,'formula_damage_milli':formula,'target_hp_milli':hp}

def validate_player_input(p,registry,save_id):
    base=player(registry,save_id)
    if not isinstance(p,Mapping) or not set(base)<=set(p) or set(p)-set(base)-set(effects.CAPS):raise ValidationError("exact readonly Combat stat input required")
    effects.validate(p)
    for k in ("id","definition_id","name","asset_id"):
        if p[k]!=base[k]:raise ValidationError("player input identity mismatch")
    for k in ("max_hp_milli","attack_milli"):integer(p[k],k,1)
    integer(p["armor_milli"],"armor")

def start(partition,registry,save_id,battle_id,encounter_id,*,player_snapshot=None,growth_snapshot=None,equipment_sources=()):
    validate(partition,registry,save_id)
    old=partition['battle']
    if old and old['status'] in ('ACTIVE','PLAYER_WIN'):raise ConflictError('finish or settle current battle before start')
    d=encounter(registry,encounter_id);e=monster(registry,d.monster_id);p=player_snapshot if player_snapshot is not None else player(registry,save_id)
    validate_player_input(p,registry,save_id)
    b={'battle_id':battle_id,'encounter_id':encounter_id,'player_id':p['id'],'enemy_id':e.machine_id,'status':'ACTIVE',
       'player_hp_milli':p['max_hp_milli'],'enemy_hp_milli':e.base_hp_milli,'step':0,
       'latest_events':[fact('battle_started')],'reward_state':'NONE','reward':{},'rules_version':RULES_VERSION}
    b.update(durability.snapshot(registry,encounter_id))
    b['enemy_hp_milli']=effective_monster(registry,b).base_hp_milli
    if player_snapshot is not None:b['player_snapshot']=p
    if growth_snapshot is not None:b['growth_snapshot']=growth_snapshot
    version=loot_version(registry,encounter_id)
    if version:b['loot_version']=version
    cfg=effect_definitions.settings(registry)
    if cfg:
        sources=[]
        if growth_snapshot:
            from src.systems.cultivation import techniques
            part=growth_snapshot.get('techniques',techniques.initial());manuals=techniques.config(registry)
            for key in part['slots'].values():
                if key in cfg['techniques']:
                    row=techniques.definition(manuals,key)
                    sources.append({'group':'techniques','id':key,'level':techniques.level(manuals,row,part['owned'][key])})
        for key in equipment_sources:
            if key in cfg['equipment']:sources.append({'group':'equipment','id':key,'level':1})
        enemy_source=e.asset_id.replace('.','_')
        b['mechanics']=mechanics.initial(cfg,sources,enemy_source if enemy_source in cfg['enemies'] else None)
        b['rules_version']=effect_definitions.VERSION
    result=freeze_json({'battle':b});validate(result,registry,save_id);return result

def current(partition,registry,save_id,battle_id):
    validate(partition,registry,save_id);b=partition['battle']
    if b is None or b['battle_id']!=battle_id:raise NotFoundError('unknown battle id')
    return b

def attack(partition,registry,save_id,battle_id):
    b=thaw_json(current(partition,registry,save_id,battle_id))
    if b['status']!='ACTIVE':raise ValidationError('battle no longer active')
    _round(b,effective_monster(registry,b),b.get('player_snapshot') or player(registry,save_id),config=effect_definitions.settings(registry))
    result=freeze_json({'battle':b});validate(result,registry,save_id);return result

def _round(b,e,p,*,emit=True,config=None):
    if b.get('rules_version')==effect_definitions.VERSION:
        mechanics.Round(b,e,p,config,emit).turn()
        return
    # Shared arithmetic and deterministic rolls; result-only settlement emits no attacks.
    b['step']+=1;events=[]
    fact=globals()['fact'] if emit else lambda *args,**kwargs: None
    advanced=b.get('rules_version')==RULES_VERSION
    def hit(actor,target,amount):
        field=target+'_hp_milli';actual=min(b[field],amount);b[field]=max(0,b[field]-amount)
        events.extend([fact(actor+'_attack',actor,target),fact('damage',actor,target,actual,amount,b[field]),fact(target+'_hit',actor,target,actual,amount,b[field])])
        return actual
    # Legacy actors with no extended stats keep guaranteed hits and old damage.
    extended=bool(set(p)&set(effects.CAPS))
    accuracy=min(10000,9500+p.get('accuracy_bps',0)) if extended else 10000
    if effects.roll(b,'player_hit')<accuracy:
        attack,critical=effects.attack_value(p,b,e)
        if critical:events.append(fact('critical','player','enemy'))
        amount=damage(attack,max(0,e.armor_milli-p.get('pierce_milli',0)))
        actual=hit('player','enemy',effects.outgoing_damage(amount,p) if advanced else amount)
        if advanced and p.get('lifesteal_bps',0):
            healed=min(p['max_hp_milli']-b['player_hp_milli'],actual*p['lifesteal_bps']//10000)
            if healed:
                b['player_hp_milli']+=healed;events.append(fact('lifesteal','player','player',healed,healed,b['player_hp_milli']))
    else:events.extend([fact('player_attack','player','enemy'),fact('miss','player','enemy')])
    if b['enemy_hp_milli']==0:
        b.update(status='PLAYER_WIN',reward_state='READY',reward=dict(e.reward));events.extend([fact('enemy_defeated','player','enemy'),fact('battle_won'),fact('reward_ready')])
    else:
        if effects.roll(b,'enemy_hit')>=10000-p.get('evasion_bps',0):events.extend([fact('enemy_attack','enemy','player'),fact('miss','enemy','player')])
        else:
            enemy_attack,critical=effects.enemy_attack_value(e,p,b) if advanced else (e.attack_milli,False)
            if critical:events.append(fact('critical','enemy','player'))
            incoming=damage(enemy_attack,p['armor_milli'])
            if advanced:incoming=effects.incoming_damage(incoming,p)
            before=b['player_hp_milli'];hit('enemy','player',incoming)
            received=before-b['player_hp_milli']
            poison=(e.poison_milli if b.get('loot_version') else 0)*(10000-p.get('poison_resist_bps',0))//10000
            if advanced:poison=poison*(10000-p.get('damage_reduction_bps',0))//10000
            if poison and b['player_hp_milli']:
                actual=min(poison,b['player_hp_milli']);b['player_hp_milli']-=actual;events.append(fact('poison','enemy','player',actual,poison,b['player_hp_milli']))
            reflected=received*p.get('reflect_bps',0)//10000
            if reflected and b['player_hp_milli']:
                actual=min(reflected,b['enemy_hp_milli']);b['enemy_hp_milli']-=actual;events.append(fact('reflect','player','enemy',actual,reflected,b['enemy_hp_milli']))
                if not b['enemy_hp_milli']:
                    b.update(status='PLAYER_WIN',reward_state='READY',reward=dict(e.reward));events.extend([fact('enemy_defeated','player','enemy'),fact('battle_won'),fact('reward_ready')])
        if b['player_hp_milli']==0:b['status']='PLAYER_LOSE';events.extend([fact('player_defeated','enemy','player'),fact('battle_lost')])
    b['latest_events']=events if emit else [globals()['fact']('battle_won' if b['status']=='PLAYER_WIN' else 'battle_lost' if b['status']=='PLAYER_LOSE' else 'battle_started')]

def result_only(partition,registry,save_id):
    """Pure whole-fight outcome plus state before its final round; rewards stay in Application."""
    validate(partition,registry,save_id)
    b=thaw_json(partition['battle'])
    if b is None or b['status']!='ACTIVE':raise ValidationError('result requires active battle')
    e=effective_monster(registry,b);p=b.get('player_snapshot') or player(registry,save_id)
    rounds=0;before=None
    while b['status']=='ACTIVE':
        before=thaw_json(b) if 'mechanics' in b else dict(b)
        _round(b,e,p,emit=False,config=effect_definitions.settings(registry));rounds+=1
    result=freeze_json({'battle':b});validate(result,registry,save_id)
    return result,freeze_json({'battle':before}),rounds


def abandon(partition,registry,save_id,battle_id):
    b=thaw_json(current(partition,registry,save_id,battle_id))
    if b['status'] not in ('ACTIVE','PLAYER_WIN'):raise ValidationError('only active or unclaimed victorious battle may be abandoned')
    b.update(status='ABANDONED',reward_state='NONE',reward={},latest_events=[fact('battle_abandoned')]);return freeze_json({'battle':b})

def reward_settled(partition,registry,save_id,battle_id):
    b=thaw_json(current(partition,registry,save_id,battle_id))
    if b['status']=='SETTLED':return freeze_json(partition)
    if b['status']!='PLAYER_WIN':raise ValidationError('reward requires victory')
    b.update(status='SETTLED',reward_state='SETTLED',latest_events=[fact('reward_settled')]);return freeze_json({'battle':b})

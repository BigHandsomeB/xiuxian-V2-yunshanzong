"""Single player Growth authority. No inventory mutation, clock, RNG or Combat import."""
from collections.abc import Mapping
from dataclasses import replace
from src.data.economy.sect_rules import settings
from src.data.cultivation.definitions import RealmDefinition,CultivationAction,START
from src.data.registry import DefinitionKey
from src.core.state.envelope import freeze_json
from src.core.validation import ValidationError,integer
COMMANDS=('cultivation_train','cultivation_breakthrough','cultivation_use_pill')
class CultivationBlocked(ValidationError):
    def __init__(self,reasons):self.reasons=tuple(reasons);super().__init__(';'.join(r['message'] for r in reasons))
def realm(registry,key):
    d=registry.lookup(DefinitionKey('realms',key))
    if not isinstance(d,RealmDefinition):raise ValidationError('realm definition required')
    cfg=settings(registry)
    if cfg and cfg.get('leveling') and d.machine_id==START:
        cost=cfg['leveling']['realms'][0]['cost']
        return replace(d,cost=tuple(sorted(cost.items())),references=tuple(DefinitionKey('resources',k) for k in sorted(cost))+(DefinitionKey('realms',d.next_realm_id),))
    if cfg and d.machine_id==START:d=replace(d,cost=tuple(sorted(cfg['cultivation']['breakthrough_cost'].items())),references=tuple(DefinitionKey('resources',k) for k in sorted(cfg['cultivation']['breakthrough_cost']))+(DefinitionKey('realms',d.next_realm_id),))
    return d
def action(registry):
    d=registry.lookup(DefinitionKey('cultivation_actions','pill_train'))
    if not isinstance(d,CultivationAction):raise ValidationError('pill action required')
    cfg=settings(registry)
    return replace(d,gain=cfg['cultivation']['pill_gain']) if cfg else d
def initial(save):return freeze_json({'player_id':save+':hero','current_realm':START,'progress':0,'growth_revision':0})
def validate(p,registry,save):
    if not isinstance(p,Mapping) or set(p)!={'player_id','current_realm','progress','growth_revision'} or p['player_id']!=save+':hero':raise ValidationError('exact stable player Growth required')
    d=realm(registry,p['current_realm']);integer(p['progress'],'progress');integer(p['growth_revision'],'growth revision')
    if p['progress']>progress_limit(p,registry):raise ValidationError('progress outside realm threshold')
    if d.next_realm_id is None and p['growth_revision']<1:raise ValidationError('advanced realm requires growth history')
    return p
def projection(p,registry,save):
    validate(p,registry,save);d=realm(registry,p['current_realm']);base=registry.lookup(DefinitionKey('players','hero'))
    bonus=stage(p,registry)['bonus_bps']
    return freeze_json({'id':p['player_id'],'definition_id':base.machine_id,'name':base.display_name,'asset_id':base.asset_id,
      'max_hp_milli':max(20000,(70+base.level*10+d.index*25)*1000)*d.power*(10000+bonus)//10000,
      'attack_milli':max(1000,(8+base.level*2+d.index*3)*1000)*d.power*(10000+bonus)//10000,'armor_milli':base.level*500*d.power})
def stage(p,registry):
    cfg=settings(registry)
    if not cfg:return {'name':None,'bonus_bps':0,'next_progress':None,'remaining':0}
    stage_cfg=cfg['cultivation'] if p['current_realm']==START else cfg.get('foundation_cultivation')
    if not stage_cfg:return {'name':None,'bonus_bps':0,'next_progress':None,'remaining':0}
    rows=stage_cfg['stages'];index=max(i for i,r in enumerate(rows) if p['progress']>=r['minimum_progress'])
    selected=rows[index];next_progress=rows[index+1]['minimum_progress'] if index+1<len(rows) else progress_limit(p,registry)
    return {'name':selected['name'],'bonus_bps':selected['bonus_bps'],'next_progress':next_progress,'remaining':max(0,next_progress-p['progress'])}
def reason(code,message):return {'code':code,'message':message}
def blockers(p,registry,save,stock,active=False,pending=False):
    validate(p,registry,save);d=realm(registry,p['current_realm']);a=action(registry);common=[]
    if active:common.append(reason('ACTIVE_BATTLE','当前战斗中，请先结束或放弃战斗。'))
    if pending:common.append(reason('PENDING','宗门进度正在续算，请先更新状态。'))
    if d.next_realm_id is None:common.append(reason('MAX_FOR_PHASE','当前阶段已达到可开放的最高境界。'))
    train=list(common);breaking=list(common)
    if d.next_realm_id is not None:
        if p['progress']>=d.threshold:train.append(reason('PROGRESS_FULL','修为已满，请突破。'))
        if stock.get(a.required_item_id,0)<a.quantity:train.append(reason('MISSING_PILL','凝气丹不足，请前往丹鼎阁炼制。'))
        if p['progress']<d.threshold:breaking.append(reason('PROGRESS_LOW','尚未达到突破条件。'))
        for key,n in d.cost:
            if stock.get(key,0)<n:
                name=registry.lookup(DefinitionKey('resources',key)).display_name
                breaking.append(reason('MISSING_MATERIAL',f'突破需要{name} ×{n}，当前不足。'))
    return {'train':train,'breakthrough':breaking}
def train(p,registry,save,stock,active=False,*,count=1):
    integer(count,'pill count',1)
    reasons=blockers(p,registry,save,stock,active)['train']
    if reasons:raise CultivationBlocked(reasons)
    d=realm(registry,p['current_realm']);a=action(registry)
    used=min(count,(d.threshold-p['progress']+a.gain-1)//a.gain)
    if stock.get(a.required_item_id,0)<used*a.quantity:raise CultivationBlocked([reason('MISSING_PILL','凝气丹不足，请减少使用数量。')])
    amount=min(a.gain*used,d.threshold-p['progress']);q={**p,'progress':p['progress']+amount,'growth_revision':p['growth_revision']+used}
    events=[{'kind':'pill_consumed','item_id':a.required_item_id,'quantity':a.quantity*used},{'kind':'cultivation_gained','amount':amount}]
    if q['progress']==d.threshold:events.append({'kind':'breakthrough_available'})
    validate(q,registry,save);return freeze_json(q),freeze_json(events)
def breakthrough(p,registry,save,stock,active=False):
    reasons=blockers(p,registry,save,stock,active)['breakthrough']
    if reasons:raise CultivationBlocked(reasons)
    d=realm(registry,p['current_realm']);q={**p,'current_realm':d.next_realm_id,'progress':0,'growth_revision':p['growth_revision']+1}
    validate(q,registry,save);return freeze_json(q),freeze_json([{'kind':'breakthrough_completed','from_realm':d.machine_id,'to_realm':d.next_realm_id}])
def stats(p):return {'max_hp':p['max_hp_milli']/1000,'attack':p['attack_milli']/1000,'armor':p['armor_milli']/1000}
def view(p,registry,save,stock,active=False,pending=False):
    validate(p,registry,save);d=realm(registry,p['current_realm']);a=action(registry);blocks=blockers(p,registry,save,stock,active,pending);n=realm(registry,d.next_realm_id) if d.next_realm_id else None
    future={**p,'current_realm':n.machine_id,'progress':0,'growth_revision':max(1,p['growth_revision'])} if n else None
    result={'player':{'id':p['player_id'],'name':registry.lookup(DefinitionKey('players','hero')).display_name},'current_realm':d.machine_id,'realm_name':d.display_name,'progress':p['progress'],'threshold':d.threshold,'progress_percentage':p['progress']*100/d.threshold if d.threshold else 100,'growth_revision':p['growth_revision'],'stage':stage(p,registry),
      'status':'MAX_FOR_PHASE' if n is None else 'BREAKTHROUGH_AVAILABLE' if p['progress']>=d.threshold else 'READY',
      'pill':{'item_id':a.required_item_id,'quantity':stock.get(a.required_item_id,0),'required_quantity':a.quantity,'effect':a.gain},'can_train':not blocks['train'],'can_use_pill':not blocks['train'],'can_breakthrough':not blocks['breakthrough'],'blocking_reasons':blocks,
      'next_realm':{'id':n.machine_id,'name':n.display_name} if n else None,'combat_projection':stats(projection(p,registry,save)),'next_realm_preview':stats(projection(future,registry,save)) if future else None,
      'breakthrough_costs':[{'item_id':k,'name':registry.lookup(DefinitionKey('resources',k)).display_name,'quantity':v,'current_quantity':stock.get(k,0)} for k,v in d.cost]}
    foundation=foundation_rules(registry)
    if foundation and p['current_realm']=='realm_1':
        result.update(foundation=True,threshold=foundation['threshold'],progress_percentage=p['progress']*100/foundation['threshold'],
            status='FOUNDATION_FULL' if p['progress']>=foundation['threshold'] else 'FOUNDATION_TRAINING')
    if foundation:
        result['foundation_pills']=[{'item_id':key,'name':registry.lookup(DefinitionKey('resources',key)).display_name,'quantity':stock.get(key,0),
            'gain':row['gain'],'can_use':not pill_blockers(p,registry,save,stock,key,active,pending),
            'blocking_reasons':pill_blockers(p,registry,save,stock,key,active,pending)} for key,row in foundation['pills'].items()]
    return freeze_json(result)


def foundation_rules(registry):
    cfg=settings(registry)
    return cfg.get('foundation_cultivation') if cfg else None


def progress_limit(p,registry):
    cfg=foundation_rules(registry)
    return cfg['threshold'] if cfg and p['current_realm']=='realm_1' else realm(registry,p['current_realm']).threshold


def pill_blockers(p,registry,save,stock,item_id,active=False,pending=False):
    validate(p,registry,save);cfg=foundation_rules(registry)
    if not cfg or type(item_id) is not str or item_id not in cfg['pills']:raise ValidationError('筑基修炼丹尚未开放')
    reasons=[]
    if p['current_realm']!='realm_1':reasons.append(reason('REALM_LOW','炼气突破完成后才能服用筑基修炼丹。'))
    if active:reasons.append(reason('ACTIVE_BATTLE','当前战斗中，请先结束或放弃战斗。'))
    if pending:reasons.append(reason('PENDING','宗门进度正在续算，请先更新状态。'))
    if p['current_realm']=='realm_1' and p['progress']>=cfg['threshold']:reasons.append(reason('PROGRESS_FULL','筑基修为已满，本批暂无下一境界。'))
    if stock.get(item_id,0)<1:reasons.append(reason('MISSING_PILL','修炼丹不足，请前往丹鼎阁炼制。'))
    return reasons


def use_foundation_pill(p,registry,save,stock,item_id,active=False,*,count=1):
    integer(count,'pill count',1)
    reasons=pill_blockers(p,registry,save,stock,item_id,active)
    if reasons:raise CultivationBlocked(reasons)
    cfg=foundation_rules(registry);gain=cfg['pills'][item_id]['gain'];remaining=cfg['threshold']-p['progress']
    used=min(count,(remaining+gain-1)//gain)
    if stock.get(item_id,0)<used:raise CultivationBlocked([reason('MISSING_PILL','修炼丹不足，请减少使用数量。')])
    amount=min(gain*used,remaining)
    q={**p,'progress':p['progress']+amount,'growth_revision':p['growth_revision']+used}
    validate(q,registry,save)
    return freeze_json(q),freeze_json([{'kind':'pill_consumed','item_id':item_id,'quantity':used},{'kind':'cultivation_gained','amount':amount}])

# Historical registries retain their original contracts; shipping opts into levels.
from . import leveling
_legacy_validate=validate
_legacy_projection=projection
_legacy_blockers=blockers
_legacy_breakthrough=breakthrough
_legacy_view=view
_legacy_train=train
_legacy_pill_blockers=pill_blockers
_legacy_use_foundation_pill=use_foundation_pill

def validate(p,registry,save):
    return leveling.validate(p,registry,save) if leveling.config(registry) else _legacy_validate(p,registry,save)
def projection(p,registry,save):
    return leveling.projection(p,registry,save) if leveling.config(registry) else _legacy_projection(p,registry,save)
def blockers(p,registry,save,stock,active=False,pending=False):
    return leveling.blockers(p,registry,save,stock,active,pending) if leveling.config(registry) else _legacy_blockers(p,registry,save,stock,active,pending)
def breakthrough(p,registry,save,stock,active=False):
    return leveling.breakthrough(p,registry,save,stock,active) if leveling.config(registry) else _legacy_breakthrough(p,registry,save,stock,active)
def view(p,registry,save,stock,active=False,pending=False,world_ms=0):
    return leveling.view(p,registry,save,stock,active,pending,world_ms) if leveling.config(registry) else _legacy_view(p,registry,save,stock,active,pending)
def train(p,registry,save,stock,active=False,*,count=1,world_ms=0):
    return leveling.use_pill(p,registry,save,stock,'pill',active,count=count,world_ms=world_ms) if leveling.config(registry) else _legacy_train(p,registry,save,stock,active,count=count)
def pill_blockers(p,registry,save,stock,item_id,active=False,pending=False):
    return leveling.pill_reasons(p,registry,save,stock,item_id,active,pending) if leveling.config(registry) else _legacy_pill_blockers(p,registry,save,stock,item_id,active,pending)
def use_foundation_pill(p,registry,save,stock,item_id,active=False,*,count=1,world_ms=0):
    return leveling.use_pill(p,registry,save,stock,item_id,active,count=count,world_ms=world_ms) if leveling.config(registry) else _legacy_use_foundation_pill(p,registry,save,stock,item_id,active,count=count)

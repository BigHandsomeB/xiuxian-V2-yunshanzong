"""Pure cumulative XP, realm gates, compatible stats and simulation-time pills."""
from bisect import bisect_right
from collections.abc import Mapping
from src.data.cultivation.levels import thresholds
from src.data.economy.sect_rules import settings
from src.core.state.envelope import freeze_json
from src.core.validation import ValidationError,integer
from src.data.registry import DefinitionKey


def config(registry):return (settings(registry) or {}).get('leveling')
def table(c):return thresholds(c['xp_curve']['A'],c['max_level'],c['xp_curve']['exponent_numerator'],c['xp_curve']['exponent_denominator'])
def realm_index(p):return int(p['current_realm'].split('_')[1])
def cap(p,c):return table(c)[(realm_index(p)+1)*c['levels_per_realm']+1]
def xp(p,c):
    if 'total_xp' in p:return p['total_xp']
    start=realm_index(p)*500+1;limit=1800 if start==1 else 6000
    return table(c)[start+499*min(limit,p['progress'])//limit]
def level(p,c):return min((realm_index(p)+1)*500,max(realm_index(p)*500+1,bisect_right(table(c),xp(p,c))-1))
def validate(p,registry,save):
    required={'player_id','current_realm','growth_revision'}
    allowed=required|{'progress','total_xp','legacy_stat_floor','pill_window_start_ms','pill_count','latest_xp','techniques','trial_attributes','attribute_trial'}
    if not isinstance(p,Mapping) or not required<=set(p) or set(p)-allowed or ('total_xp' not in p and 'progress' not in p):raise ValidationError('invalid cumulative Growth fields')
    if p['player_id']!=save+':hero':raise ValidationError('invalid Growth player')
    from .attribute_trials import validate_growth
    validate_growth(p,registry)
    c=config(registry)
    if p['current_realm'] not in tuple(row['id'] for row in c['realms'][:c['open_realms']]):raise ValidationError('realm is not open')
    i=realm_index(p)
    integer(p['growth_revision'],'growth revision')
    if i and p['growth_revision']<1:raise ValidationError('advanced realm requires growth history')
    if 'progress' in p:
        integer(p['progress'],'legacy progress')
        if p['progress']>(1800 if i==0 else 6000):raise ValidationError('legacy progress outside realm')
    integer(xp(p,c),'total XP')
    if not table(c)[i*500+1]<=xp(p,c)<=cap(p,c):raise ValidationError('XP outside realm gate')
    for k in ('pill_count','pill_window_start_ms'):integer(p.get(k,0),k)
    floor=p.get('legacy_stat_floor',{})
    if not isinstance(floor,Mapping) or set(floor)-{'max_hp_milli','attack_milli','armor_milli'}:raise ValidationError('invalid legacy floor')
    for k,n in floor.items():integer(n,k)
    latest=p.get('latest_xp')
    if latest:
        if set(latest)!={'battle_id','xp_gained','levels_gained'} or not isinstance(latest['battle_id'],str):raise ValidationError('invalid XP receipt')
        integer(latest['xp_gained'],'XP gained');integer(latest['levels_gained'],'levels gained')
    if 'techniques' in p:
        from . import techniques
        techniques.validate(p['techniques'],registry)
    return p


def legacy_stats(p,registry):
    c=settings(registry);i=realm_index(p);base=registry.lookup(DefinitionKey('players','hero'))
    stages=c['cultivation']['stages'] if i==0 else c['foundation_cultivation']['stages']
    bonus=max(row['bonus_bps'] for row in stages if row['minimum_progress']<=p.get('progress',0))
    return {'max_hp_milli':max(20000,(70+base.level*10+i*25)*1000)*(i+1)*(10000+bonus)//10000,'attack_milli':max(1000,(8+base.level*2+i*3)*1000)*(i+1)*(10000+bonus)//10000,'armor_milli':base.level*500*(i+1)}


def normalized(p,registry,save):
    validate(p,registry,save);c=config(registry)
    q={k:v for k,v in p.items() if k!='progress'}
    q['total_xp']=xp(p,c)
    if 'total_xp' not in p:q['legacy_stat_floor']=legacy_stats(p,registry)
    q.setdefault('pill_window_start_ms',0);q.setdefault('pill_count',0)
    return q


def projection(p,registry,save):
    validate(p,registry,save);c=config(registry);L=level(p,c);i=realm_index(p);base=registry.lookup(DefinitionKey('players','hero'))
    stats=stat_totals(L,i,c)
    floor=p.get('legacy_stat_floor',legacy_stats(p,registry) if 'total_xp' not in p else {})
    for key,n in floor.items():stats[key]=max(stats[key],n)
    from .attribute_trials import bonuses as trial_bonuses
    for key,n in trial_bonuses(p,registry).items():stats[key]=stats.get(key,0)+n
    from . import techniques
    for key,n in techniques.bonuses(p,registry).items():stats[key]=stats.get(key,0)+n
    for key,limit in [('speed_bps',3000),('evasion_bps',2500)]:
        if key in stats:stats[key]=min(stats[key],limit)
    return freeze_json({'id':p['player_id'],'definition_id':base.machine_id,'name':base.display_name,'asset_id':base.asset_id,**stats})


def multiplier(L,recommended,c):
    integer(recommended,'recommended level',1)
    return min(100*recommended,max(c['minimum_multiplier_percent']*recommended,(100+c['penalty_start_percent'])*recommended-100*L)),100*recommended


def gain(p,registry,save,amount):
    integer(amount,'XP gain');c=config(registry);q=normalized(p,registry,save);old=level(q,c);before=q['total_xp']
    q['total_xp']=min(cap(q,c),before+amount)
    if q['total_xp']!=before:q['growth_revision']+=1
    return q,{'xp_gained':q['total_xp']-before,'levels_gained':level(q,c)-old}


def kill(p,registry,save,floor,tier,battle_id):
    c=config(registry);n,d=multiplier(level(p,c),floor*c['recommended_level_per_floor'],c)
    amount=c['X0']*c['tier_multipliers'][tier]*n//(c['kills_per_hour']*d)
    from . import techniques
    tc=techniques.config(registry)
    if tc and tc['kill_xp_requires_equipped'] and not p.get('techniques',{}).get('slots'):amount=0
    q,result=gain(p,registry,save,amount)
    if tc:q,_=techniques.award(q,registry,tier,(n,d) if tc.get('low_floor_penalty') else (1,1))
    q['latest_xp']={'battle_id':battle_id,**result}
    return freeze_json(q),result


def pill_reasons(p,registry,save,stock,key,active=False,pending=False):
    from .growth import CultivationBlocked,reason
    validate(p,registry,save);c=config(registry);row=c['pills'].get(key)
    if row is None:raise ValidationError('此丹药不能增加修为')
    out=[];L=level(p,c)
    if not row['minimum_level']<=L<=row['maximum_level']:out.append(reason('LEVEL_RANGE',f"此丹药仅在第{row['minimum_level']}–{row['maximum_level']}级有效；本次不消耗。"))
    if active:out.append(reason('ACTIVE_BATTLE','当前战斗中，请先结束战斗。'))
    if pending:out.append(reason('PENDING','宗门进度正在续算。'))
    if xp(p,c)>=cap(p,c):out.append(reason('PROGRESS_FULL','境界修为已满，请先突破；未开放境界暂不能突破。'))
    if stock.get(key,0)<1:out.append(reason('MISSING_PILL','丹药不足。'))
    return out


def use_pill(p,registry,save,stock,key,active=False,*,count=1,world_ms=0):
    from .growth import CultivationBlocked,reason
    integer(count,'pill count',1);integer(world_ms,'world time')
    reasons=pill_reasons(p,registry,save,stock,key,active)
    if reasons:raise CultivationBlocked(reasons)
    c=config(registry);q=normalized(p,registry,save);start=q['pill_window_start_ms']
    if world_ms<start:raise ValidationError('world time cannot move backwards')
    if world_ms-start>=c['pill_period_ms']:
        q['pill_window_start_ms']=start+(world_ms-start)//c['pill_period_ms']*c['pill_period_ms'];q['pill_count']=0
    before=xp(q,c);old=level(q,c);used=0;row=c['pills'][key]
    while used<count and row['minimum_level']<=level(q,c)<=row['maximum_level'] and xp(q,c)<cap(q,c):
        if used>=stock.get(key,0):raise CultivationBlocked([reason('MISSING_PILL','丹药不足，请减少数量。')])
        full=q['pill_count']<c['pill_full_count'];amount=c['X0']*c['pill_minutes']*(100 if full else c['pill_reduced_percent'])//(60*100)
        q,result=gain(q,registry,save,amount);q['pill_count']+=1;used+=1
    return freeze_json(q),freeze_json([{'kind':'pill_consumed','item_id':key,'quantity':used},{'kind':'cultivation_gained','amount':xp(q,c)-before,'levels_gained':level(q,c)-old}])


def blockers(p,registry,save,stock,active=False,pending=False):
    from .growth import reason
    c=config(registry);i=realm_index(p);out=[]
    if active:out.append(reason('ACTIVE_BATTLE','请先结束战斗。'))
    if pending:out.append(reason('PENDING','请先完成续算。'))
    if i+1>=c['open_realms']:out.append(reason('MAX_FOR_PHASE','下一境界尚未开放。'))
    if xp(p,c)<cap(p,c):out.append(reason('PROGRESS_LOW','需境界满级且修为条满。'))
    for key,n in c['realms'][i]['cost'].items():
        if stock.get(key,0)<n:out.append(reason('MISSING_MATERIAL',f'突破材料不足：{registry.lookup(DefinitionKey("resources",key)).display_name} ×{n}。'))
    return {'train':pill_reasons(p,registry,save,stock,'pill',active,pending),'breakthrough':out}


def breakthrough(p,registry,save,stock,active=False):
    from .growth import CultivationBlocked
    reasons=blockers(p,registry,save,stock,active)['breakthrough']
    if reasons:raise CultivationBlocked(reasons)
    q=normalized(p,registry,save);old=q['current_realm'];q['current_realm']=config(registry)['realms'][realm_index(p)+1]['id'];q['growth_revision']+=1
    return freeze_json(q),freeze_json([{'kind':'breakthrough_completed','from_realm':old,'to_realm':q['current_realm']}])


def view(p,registry,save,stock,active=False,pending=False,world_ms=0):
    from .growth import stats
    validate(p,registry,save);c=config(registry);L=level(p,c);i=realm_index(p);T=table(c);total=xp(p,c)
    next_row=c['realms'][i+1] if i+1<c['open_realms'] else None
    future={**normalized(p,registry,save),'current_realm':next_row['id'],'total_xp':T[(i+1)*500+1],'growth_revision':max(1,p['growth_revision'])} if next_row else None
    blocks=blockers(p,registry,save,stock,active,pending);n=(L//100+1)*100
    milestone={'level':n,'remaining':n-L,**c['milestones'][(n//100-1)%5]} if n<=c['open_realms']*500 else None
    gain_amount=c['X0']*c['pill_minutes']//60;period=c['pill_period_ms'];start=p.get('pill_window_start_ms',0);used=p.get('pill_count',0) if world_ms-start<period else 0
    pills=[{'item_id':key,'name':registry.lookup(DefinitionKey('resources',key)).display_name,'quantity':stock.get(key,0),'gain':gain_amount,'minimum_level':row['minimum_level'],'maximum_level':row['maximum_level'],'can_use':not pill_reasons(p,registry,save,stock,key,active,pending),'blocking_reasons':pill_reasons(p,registry,save,stock,key,active,pending)} for key,row in c['pills'].items()]
    return freeze_json({'player':{'id':p['player_id'],'name':registry.lookup(DefinitionKey('players','hero')).display_name},'current_realm':p['current_realm'],'realm_name':c['realms'][i]['name'],'level':L,'total_xp':total,'progress':total-T[L],'threshold':T[L+1]-T[L],'progress_percentage':(total-T[L])*100/(T[L+1]-T[L]),'growth_revision':p['growth_revision'],'stage':{'name':None},'milestone':milestone,'status':'BREAKTHROUGH_AVAILABLE' if total>=cap(p,c) and next_row else 'MAX_FOR_PHASE' if total>=cap(p,c) else 'READY','pill':{'item_id':'pill','quantity':stock.get('pill',0),'required_quantity':1,'effect':gain_amount},'can_train':not blocks['train'],'can_use_pill':not blocks['train'],'can_breakthrough':not blocks['breakthrough'],'blocking_reasons':blocks,'next_realm':{'id':next_row['id'],'name':next_row['name']} if next_row else None,'combat_projection':stats(projection(p,registry,save)),'next_realm_preview':stats(projection(future,registry,save)) if future else None,'breakthrough_costs':[{'item_id':key,'name':registry.lookup(DefinitionKey('resources',key)).display_name,'quantity':v,'current_quantity':stock.get(key,0)} for key,v in c['realms'][i]['cost'].items()],'foundation_pills':pills,'pill_daily_used':used,'pill_daily_full_limit':c['pill_full_count'],'pill_reduced_percent':c['pill_reduced_percent']})


def stat_totals(L,i,c):
    stats=dict(c['base_stats'])
    for key,n in c['equipment_anchor'].items():stats[key]+=n*(L-1)*c.get('growth_stat_coefficients_bps',{}).get(key,c['growth_coefficient_bps'])//(500*10000)
    for j in range(1,L//100+1):
        row=c['milestones'][(j-1)%5];stats[row['stat']]=stats.get(row['stat'],0)+row['amount']
    for row in c['realms'][1:i+1]:
        for key,n in row['breakthrough_bonus'].items():stats[key]=stats.get(key,0)+n
    return stats

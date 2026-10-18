"""Owned techniques, integer XP and additive stats; no clock or combat mutation."""
from collections.abc import Mapping
from src.core.state.envelope import thaw_json
from src.core.validation import ValidationError, integer
from src.data.economy.sect_rules import settings

COMMANDS=('technique_equip','technique_unequip','technique_buy','technique_claim','technique_exchange')
def config(registry):return (settings(registry) or {}).get('techniques')
def initial():return {'owned':{},'slots':{}}
def definition(c,key):
    row=next((r for r in (*c['techniques'],*c.get('legacy_test_definitions',())) if r['id']==key),None)
    if row is None:raise ValidationError('未知功法')
    return row
def threshold(c,L,row=None):return (c.get('xp_per_level_by_grade',{}).get(row['grade'],c['xp_per_level_factor']) if row and not row.get('test') else c['xp_per_level_factor'])*L*(L-1)//2
def level(c,row,xp):
    maximum=c['grades'][row['grade']]
    return max(L for L in range(1,maximum+1) if threshold(c,L,row)<=xp)
def validate(part,registry):
    c=config(registry)
    if not c or not isinstance(part,Mapping) or not {'owned','slots'}<=set(part) or set(part)-{'owned','slots','formal_version','claims','boss_wins','stone_first_claimed','latest_stone_reward'}:raise ValidationError('invalid technique state')
    if not isinstance(part['owned'],Mapping) or not isinstance(part['slots'],Mapping):raise ValidationError('invalid technique collections')
    for key,xp in part['owned'].items():
        row=definition(c,key);integer(xp,'technique XP')
        if xp>threshold(c,c['grades'][row['grade']],row):raise ValidationError('technique XP exceeds grade cap')
    if len(set(part['slots'].values()))!=len(part['slots']):raise ValidationError('功法不能重复装备')
    for slot,key in part['slots'].items():
        if slot not in c['slots'] or key not in part['owned']:raise ValidationError('invalid technique slot')
        if definition(c,key)['category']!=('passive' if slot.startswith('passive_') else slot):raise ValidationError('功法类型与槽位不符')
    if 'formal_version' in part and part['formal_version']!=1:raise ValidationError('invalid formal manual version')
    claims=part.get('claims',{})
    if not isinstance(claims,Mapping) or set(claims)-{'blue','purple'}:raise ValidationError('invalid manual claims')
    for grade,key in claims.items():
        if key not in part['owned'] or definition(c,key)['grade']!=grade:raise ValidationError('invalid claimed manual')
    integer(part.get('boss_wins',0),'manual boss wins')
    first=part.get('stone_first_claimed',())
    if not isinstance(first,(list,tuple)) or any(k!='cold_jade_cave' for k in first) or len(set(first))!=len(first):raise ValidationError('invalid stone first claims')
    latest=part.get('latest_stone_reward')
    if latest:
        if set(latest)!={'battle_id','amounts'} or type(latest['battle_id']) is not str or not isinstance(latest['amounts'],Mapping):raise ValidationError('invalid stone reward receipt')
        for key,n in latest['amounts'].items():
            if key not in ('spirit_stone_supreme','spirit_stone_immortal'):raise ValidationError('invalid stone reward resource')
            integer(n,'stone reward')
    return part
def grant_test(p,registry):
    c=config(registry);q=thaw_json(p);part=q.setdefault('techniques',initial())
    for row in c.get('legacy_test_definitions',c['techniques']):part['owned'].setdefault(row['id'],0)
    for slot,row in zip(c['slots'],c.get('legacy_test_definitions',c['techniques'])):part['slots'][slot]=row['id']
    validate(part,registry)
    if q!=p:q['growth_revision']+=1
    return q
def change(p,registry,name,payload):
    c=config(registry);q=thaw_json(p);part=q.setdefault('techniques',initial())
    if name=='technique_equip':
        if set(payload)!={'technique_id','slot'}:raise ValidationError('请选择功法与槽位')
        key=payload['technique_id'];slot=payload['slot']
        if not isinstance(key,str) or not isinstance(slot,str):raise ValidationError('invalid technique selection')
        if definition(c,key).get('test'):raise ValidationError('测试功法已退出')
        if key not in part['owned']:raise ValidationError('尚未拥有这部功法')
        part['slots']={s:k for s,k in part['slots'].items() if k!=key};part['slots'][slot]=key
    elif name=='technique_unequip':
        if set(payload)!={'slot'} or payload['slot'] not in c['slots']:raise ValidationError('请选择功法槽位')
        part['slots'].pop(payload['slot'],None)
    else:raise ValidationError('未知功法操作')
    validate(part,registry)
    if q!=p:q['growth_revision']+=1
    return q
def bonuses(p,registry):
    c=config(registry);part=p.get('techniques',initial());out={}
    if not c:return out
    for key in part['slots'].values():
        row=definition(c,key);L=level(c,row,part['owned'][key])
        for stat,n in effective_bonus(c,row,L).items():out[stat]=out.get(stat,0)+n
    return out
def award(p,registry,tier,multiplier=(1,1)):
    c=config(registry);q=thaw_json(p);part=q.get('techniques',initial());gained=0;upgrades=0
    for key in part['slots'].values():
        row=definition(c,key);before=part['owned'][key];old=level(c,row,before)
        part['owned'][key]=min(threshold(c,c['grades'][row['grade']],row),before+c['kill_xp'][tier]*multiplier[0]//multiplier[1])
        gained+=part['owned'][key]-before;upgrades+=level(c,row,part['owned'][key])-old
    if gained:q['growth_revision']+=1
    return q,{'xp_gained':gained,'levels_gained':upgrades}
def view(p,registry,blocked=False,stock=None,cleared=0,source_blocked=None):
    c=config(registry)
    if not c:return None
    part=p.get('techniques',initial());rows=[]
    for key,xp in part['owned'].items():
        row=definition(c,key)
        if row.get('test') and c.get('version'):continue
        L=level(c,row,xp);maximum=c['grades'][row['grade']]
        effective=effective_bonus(c,row,L)
        rows.append({**thaw_json(row),'bonus':effective,'level':L,'max_level':maximum,'xp':xp,'progress':xp-threshold(c,L,row),'threshold':threshold(c,L+1,row)-threshold(c,L,row) if L<maximum else 0,'equipped_slot':next((s for s,k in part['slots'].items() if k==key),None)})
    catalog=[]
    for row in c['techniques']:
        source=source_quote(p,registry,row['id'],stock or {},cleared,blocked if source_blocked is None else source_blocked) if c.get('sources') else None
        alternatives=[source]
        if row['grade'] in c.get('sources',{}).get('first_clear',{}):alternatives.append(source_quote(p,registry,row['id'],stock or {},cleared,blocked if source_blocked is None else source_blocked,kind='claim'))
        if row['id'] in c.get('sources',{}).get('green_stone_ids',()):alternatives.append(source_quote(p,registry,row['id'],stock or {},cleared,blocked if source_blocked is None else source_blocked,kind='exchange'))
        catalog.append({**thaw_json(row),'owned':row['id'] in part['owned'],'source':source,'alternatives':alternatives,'max_level':c['grades'][row['grade']]})
    return {'catalog':catalog,'sources':thaw_json(c.get('sources',{})),'page_count':(stock or {}).get('manual_page',0),'open':c['open'],'instances':rows,'slots':thaw_json(part['slots']),'can_change':not blocked,'blocking_reason':'请先恢复世界并完成续算。' if blocked else '', 'kill_xp_requires_equipped':c['kill_xp_requires_equipped'],'grades':thaw_json(c['grades'])}


def effective_bonus(c,row,L):
    if row.get('test') or 'max_bonus' not in row:
        return {k:n*(10000+(L-1)*c['bonus_growth_bps_per_level'])//10000 for k,n in row['bonus'].items()}
    M=c['grades'][row['grade']]
    return {k:n*(25*(M-1)+75*(L-1))//(100*(M-1)) for k,n in row['max_bonus'].items()}

def migrate(p,registry):
    c=config(registry)
    if not c or not c.get('version'):return p
    if p.get('techniques',{}).get('formal_version')==1:return p
    q=thaw_json(p);part=q.setdefault('techniques',initial())
    retired={r['id'] for r in c.get('legacy_test_definitions',())}
    part['owned']={k:n for k,n in part['owned'].items() if k not in retired}
    part['slots']={s:k for s,k in part['slots'].items() if k not in retired}
    for slot,key in zip(('movement','passive_1'),c['starter_ids']):
        part['owned'].setdefault(key,0);part['slots'].setdefault(slot,key)
    part.update(formal_version=1,claims=part.get('claims',{}));q['growth_revision']+=1
    validate(part,registry);return q

def source_quote(p,registry,key,stock,cleared,blocked=False,kind=None):
    c=config(registry);row=definition(c,key);grade=row['grade'];rules=c['sources'];part=p.get('techniques',initial())
    kind=kind or ('buy' if grade in rules['coin_prices'] else 'exchange')
    if kind=='buy' and grade in rules['coin_prices']:cost={'coins':rules['coin_prices'][grade]};floor=0
    elif kind=='claim' and grade in rules['first_clear']:cost={};floor=rules['first_clear'][grade]
    elif kind=='exchange' and grade in rules['stone_costs']:cost=rules['stone_costs'][grade];floor=0
    elif kind=='exchange' and key in rules.get('green_stone_ids',()):cost=rules['green_stone_cost'];floor=0
    else:return {'kind':kind,'cost':{},'required_floor':0,'available':False,'blocking_reasons':['此功法不支持该获取方式']}
    reasons=[]
    if blocked:reasons.append('世界暂停或进度续算中，请恢复后再试。')
    if row.get('test'):reasons.append('测试功法已退出')
    if key in part['owned']:reasons.append('已拥有此功法')
    if floor and cleared<floor:reasons.append(f'需要荆棘古道通关{floor}层')
    if floor and grade in part.get('claims',{}):reasons.append('此品阶首通奖励已领取')
    for key,n in cost.items():
        if stock.get(key,0)<n:
            from src.data.registry import DefinitionKey
            reasons.append(registry.lookup(DefinitionKey('resources',key)).display_name+'不足')
    return {'kind':kind,'cost':thaw_json(cost),'required_floor':floor,'available':not reasons,'blocking_reasons':reasons}

def acquire(p,registry,name,payload,stock,cleared):
    if set(payload)!={'technique_id'} or type(payload['technique_id']) is not str:raise ValidationError('请选择一部功法')
    key=payload['technique_id'];quote=source_quote(p,registry,key,stock,cleared,kind=name.removeprefix('technique_'))
    if name!='technique_'+quote['kind']:raise ValidationError('功法获取方式不符')
    if not quote['available']:raise ValidationError('；'.join(quote['blocking_reasons']))
    q=thaw_json(p);part=q.setdefault('techniques',initial());part['owned'][key]=0
    if quote['kind']=='claim':part.setdefault('claims',{})[definition(config(registry),key)['grade']]=key
    q['growth_revision']+=1;validate(part,registry);return q,quote['cost']

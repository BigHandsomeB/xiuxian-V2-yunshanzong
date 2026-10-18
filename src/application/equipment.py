"""Equipment capacity/projection/atomic transaction composition, shared Inventory."""
from dataclasses import replace
from functools import lru_cache
from math import gcd
import hashlib,json
from src.application.game import GamePersistence
from src.application.cultivation import partition
from src.systems.cultivation import growth
from src.systems.equipment import items
from src.systems.economy import policy
from src.systems.inventory import holdings,operations
from src.core.validation import ValidationError,ConflictError
from src.core.state.envelope import thaw_json,freeze_json
from src.application import sect
from src.application import offline_reports as reports
from src.data.economy.definitions import EQUIPMENT_IDS,EQUIPMENT_SLOTS,EquipmentDefinition,COMBAT_AFFIX_RANGES

@lru_cache(maxsize=8)
def projection_groups(definitions):
    groups=[]
    for slot,_ in EQUIPMENT_SLOTS:
        choices={tuple((0,0,0) for _ in items.STATS)}
        for s,stats,ranges in definitions:
            if s!=slot:continue
            values={k:(a,b,step) for k,a,b,step in ranges} if ranges else {k:(n,n,0) for k,n in stats}
            choices.add(tuple(values.get(k,(0,0,0)) for k in items.STATS))
        groups.append(tuple(sorted(choices)))
    return tuple(sorted(groups,key=len))

@lru_cache(maxsize=512)
def matches_projection(bonuses,definitions,base_stats=()):
    """Search only combinations that can match the saved snapshot; never materialize a product.

    Keeps historical min/max/step and cap checks, with per-stat lower/upper bounds.
    Adding expedition equipment must not allocate millions of projection records.
    """
    if any(n<0 for n in bonuses):return False
    groups=projection_groups(definitions);size=len(items.STATS)
    base_stats=base_stats or (0,)*size
    # Equipment fills only the remaining capacity after Growth (including techniques).
    caps=tuple(max(0,items.RATE_CAPS[k]-base_stats[i]) if k in items.RATE_CAPS else None for i,k in enumerate(items.STATS))
    # Nonnegative contributions cannot undo a single item's excess, even at a cap.
    groups=tuple(sorted((tuple(row for row in group if all((min(a,cap) if cap is not None else a)<=n for n,(a,_,_),cap in zip(bonuses,row,caps))) for group in groups),key=len))
    if any(not group for group in groups):return False
    remaining=[(0,)*size for _ in range(len(groups)+1)]
    for i in range(len(groups)-1,-1,-1):remaining[i]=tuple(remaining[i+1][j]+max(row[j][1] for row in groups[i]) for j in range(size))
    def fits(low,high,steps,tail,final=False):
        for n,a,b,step,cap,extra in zip(bonuses,low,high,steps,caps,tail):
            if cap is not None:a=min(a,cap);b=min(b+extra,cap)
            else:b+=extra
            if not a<=n<=b or (final and n!=cap and step and (n-a)%step):return False
        return True
    def search(i,low,high,steps):
        if not fits(low,high,steps,remaining[i],i==len(groups)):return False
        if i==len(groups):return True
        for row in groups[i]:
            nl=tuple(low[j]+row[j][0] for j in range(size));nh=tuple(high[j]+row[j][1] for j in range(size));ns=tuple(gcd(steps[j],row[j][2]) for j in range(size))
            if search(i+1,nl,nh,ns):return True
        return False
    return search(0,(0,)*size,(0,)*size,(0,)*size)

def matches_random_projection(bonuses,registry,base=None):
    definitions=[(d.slot,d.stats,d.stat_ranges) for d in registry._definitions.values() if isinstance(d,EquipmentDefinition)]
    for d in registry._definitions.values():
        if not isinstance(d,EquipmentDefinition):continue
        key,low,high,step=COMBAT_AFFIX_RANGES[d.slot]
        ranges=d.stat_ranges or tuple((k,n,n,0) for k,n in d.stats)
        definitions.append((d.slot,(*d.stats,(key,low)),(*ranges,(key,low,high,step))))
    from src.data.combat.mechanics import settings as effect_settings,equipment_ranges
    if effect_settings(registry):
        for d in registry._definitions.values():
            if isinstance(d,EquipmentDefinition) and d.machine_id in effect_settings(registry)['equipment']:
                ranges=equipment_ranges(d.machine_id)
                stats=tuple((k,(a+b)//2) for k,a,b,_ in ranges)
                definitions.append((d.slot,stats,ranges))
                key,low,high,step=COMBAT_AFFIX_RANGES[d.slot]
                definitions.append((d.slot,(*stats,(key,low)),(*ranges,(key,low,high,step))))
    from src.data.economy.sect_rules import settings
    cfg=(settings(registry) or {}).get('management',{})
    for slot,stats,ranges in tuple(definitions):
        for level in range(1,cfg.get('enhancement_max_level',0)+1):
            bonus=level*cfg['enhancement_bonus_bps_per_level']
            def scale(k,n):return n+n*bonus//10000 if k in ('max_hp_milli','attack_milli','armor_milli') else n
            expanded=[]
            for k,a,b,step in ranges:
                values=[scale(k,n) for n in (range(a,b+1,step) if step else [a])];stride=0
                for n in values:stride=gcd(stride,n-values[0])
                expanded.append((k,values[0],values[-1],stride))
            definitions.append((slot,tuple((k,scale(k,n)) for k,n in stats),tuple(expanded)))
    return matches_projection(bonuses,tuple(definitions),tuple((base or {}).get(k,0) for k in items.STATS))

COMMANDS=('equipment_equip','equipment_unequip','equipment_lock','equipment_favorite','equipment_sell','equipment_salvage','equipment_sell_all','equipment_salvage_all')
def equipment(state):return state.domains.get('equipment',items.initial())
def count(state):return len(equipment(state)['instances'])
def attribute_rows(actor):
    """Final, capped combat facts for the character panel; not another stat authority."""
    rows=[]
    for key,name,icon,description in [
        ('max_hp_milli','生命','hp','最大生命值'),('attack_milli','攻击','attack','基础攻击力'),('armor_milli','护甲','defense','抵消敌方直接攻击'),
        ('pierce_milli','破甲','pierce','减少目标参与结算的护甲'),('crit_bps','暴击','crit','触发暴击的概率'),
        ('crit_damage_bps','暴击伤害','crit_damage','暴击倍率，基础150%'),('crit_resist_bps','抗暴','crit_resist','抵消敌方暴击率'),
        ('accuracy_bps','命中','accuracy','普通攻击实际命中率'),('evasion_bps','闪避','evasion','躲避敌方直接攻击的概率'),
        ('speed_bps','攻速','speed','自动战斗攻击速度加成'),('lifesteal_bps','吸血','lifesteal','按实际直接伤害回复生命，不含毒伤或反伤'),
        ('damage_bonus_bps','伤害加成','damage_bonus','护甲结算后增加直接攻击伤害'),('damage_reduction_bps','伤害减免','damage_reduction','降低受到的直接攻击与毒伤'),
        ('reflect_bps','反伤','reflect','反弹实际承受的直接攻击伤害'),('poison_resist_bps','抗毒','poison_resist','降低敌方毒伤'),
        ('execute_bps','斩杀增伤','execute','目标生命低于30%时提高攻击')]:
        raw=actor.get(key,0)
        if key=='crit_damage_bps':raw+=15000
        if key=='accuracy_bps':raw=min(10000,9500+raw) if any(k in actor for k in items.RATE_CAPS) or 'pierce_milli' in actor else 10000
        rows.append({'id':key,'name':name,'icon':icon,'value':raw/(100 if key.endswith('_bps') else 1000),'unit':'%' if key.endswith('_bps') else '', 'description':description})
    from src.data.combat.mechanics import CAPS as effect_caps
    names={'block_bps':'格挡','spirit_milli':'灵力','dot_reduction_bps':'持续伤害减免','heal_bonus_bps':'回复强化','shield_bonus_bps':'护盾强化','burn_apply_bps':'灼烧概率','burn_bonus_bps':'灼烧强化','chill_bonus_bps':'寒冷强化'}
    for element,label in [('wood','木'),('earth','土'),('metal','金'),('water','水'),('fire','火'),('ice','冰'),('yin','阴'),('lightning','雷'),('poison','毒')]:
        names[element+'_damage_bps']=label+'伤加成';names[element+'_resist_bps']='抗'+label
    for key in effect_caps:
        if key not in actor:continue
        rows.append({'id':key,'name':names[key],'icon':'defense' if 'resist' in key or key in ('block_bps','shield_bonus_bps') else 'attack','value':actor[key]/(100 if key.endswith('_bps') else 1000),'unit':'%' if key.endswith('_bps') else '', 'description':'增强功法技能伤害；真气为每场独立的技能消耗资源' if key=='spirit_milli' else names[key]})
    return rows
def validate(state,registry):
    growth.validate(partition(state),registry,state.save_id);items.validate(equipment(state),registry,state.save_id)
    used=set(state.domains['sect']['buildings'])|set(state.domains['disciples']['groups'])|{j['job_id'] for j in state.domains['production']['jobs'].values()}
    b=state.domains.get('combat',{}).get('battle')
    if b:used.add(b['battle_id'])
    for identity in equipment(state)['instances']:
        parts=identity.split(':')
        if len(parts)!=4 or parts[0]!=state.save_id or parts[2]!='i':raise ValidationError('equipment save identity invalid')
        try:g,n=int(parts[1]),int(parts[3])
        except ValueError as exc:raise ValidationError('equipment identity invalid') from exc
        if str(g)!=parts[1] or str(n)!=parts[3] or not 1<=g<=state.generation or not 1<=n<=state.identity['instance_counter'] or identity in used:raise ValidationError('equipment counter/collision invalid')
        used.add(identity)
    marker=equipment(state).get('latest_reward')
    if marker:
        for key in ('battle_id','instance_id'):
            parts=marker[key].split(':')
            if len(parts)!=4 or parts[0]!=state.save_id or parts[2]!='i':raise ValidationError('reward marker outside save namespace')
            try:g,n=int(parts[1]),int(parts[3])
            except ValueError as exc:raise ValidationError('reward marker identity invalid') from exc
            if str(g)!=parts[1] or str(n)!=parts[3] or not 1<=g<=state.generation or not 1<=n<=state.identity['instance_counter']:raise ValidationError('reward marker outside allocated counter')
    if b and b.get('player_snapshot'):
        # Historical Battle snapshot is not coupled to current equipment ownership.
        valid=False;p=partition(state)
        bases=[]
        if b.get('growth_snapshot') is not None:
            bases.append(growth.projection(b['growth_snapshot'],registry,state.save_id))
        else:
            bases.append(growth.projection(p,registry,state.save_id))
        from src.data.economy.sect_rules import settings
        cfg=settings(registry)
        for realm_id in ('realm_0','realm_1'):
            stage_cfg=cfg['cultivation'] if cfg and realm_id==growth.START else cfg.get('foundation_cultivation') if cfg else None
            progresses=[r['minimum_progress'] for r in stage_cfg['stages']] if stage_cfg else [0]
            for progress in progresses:
                legacy={'player_id':p['player_id'],'current_realm':realm_id,'progress':progress,'growth_revision':max(1,p['growth_revision'])}
                # Reproduce saved historical stats without reapplying level migration.
                if growth.leveling.config(registry):
                    actor=dict(growth.projection(legacy,registry,state.save_id));actor.update(growth.leveling.legacy_stats(legacy,registry));actor.pop('speed_bps',None);actor.pop('evasion_bps',None);bases.append(actor)
                else:bases.append(growth.projection(legacy,registry,state.save_id))
        if b.get('artifact_snapshot'):
            from src.systems.artifacts.artifacts import project
            bases=[project(base,registry,b['artifact_snapshot']) for base in bases]
        for base in bases:
            # A known equipped set is an exact witness; avoid a six-slot search.
            equipped=[equipment(state)['instances'][i] for i in equipment(state)['slots'].values()]
            if all(items.known_stats(row,items.definition(registry,row['definition_id'])) and items.known_affixes(row,items.definition(registry,row['definition_id'])) for row in equipped):
                projected=items.projection(equipment(state),base)
                if all(projected.get(k,0)==b['player_snapshot'].get(k,0) for k in items.STATS):valid=True;break
            bonuses=tuple(b['player_snapshot'].get(key,0)-base.get(key,0) for key in items.STATS)
            if matches_random_projection(bonuses,registry,base):valid=True;break
        if not valid:raise ValidationError('battle snapshot outside registered equipment/growth projections')
    return state
class EconomyPersistence(GamePersistence):
    def _validate(self,state):return validate(super()._validate(state),self.registry)

def acquire(state,registry,definition_id,provenance,*,roll_version=None):
    n=state.identity['instance_counter']+1;identity=f'{state.save_id}:{state.generation}:i:{n}';p=state.domains['automation']
    e=items.add(equipment(state),registry,identity,definition_id,provenance,p['epoch'],p['equipment']['mode']!='OFF',roll_version=roll_version,combat_affix=True)
    candidate=replace(state,identity={**state.identity,'instance_counter':n},domains={**state.domains,'equipment':e})
    return reports.observe_equipment(candidate,identity,items.definition(registry,definition_id).quality,'GAIN'),identity

def process(state,registry,identity,mode):
    row=items.get(equipment(state),identity);d=items.definition(registry,row['definition_id'])
    amounts={'coins':items.sale_price(registry,d.machine_id)} if mode=='SELL' else dict(d.salvage)
    e=items.remove(equipment(state),registry,identity)
    capacity=sect.capacity_source(state,registry)['effective']
    needed=sum(n for k,n in amounts.items() if holdings.definition(registry,k).warehouse_counted)
    if holdings.stock_size(state.domains['inventory'],registry)+needed>capacity:raise ValidationError('仓库空间不足，装备已保留')
    stock,r=operations.grant(state.domains['inventory'],registry,amounts,capacity=capacity)
    if any(r['discarded'].values()):raise ValidationError('不能丢弃交易或分解产物')
    return reports.observe_equipment(replace(state,domains={**state.domains,'inventory':stock,'equipment':e}),identity,d.quality,mode,amounts=amounts)

def bulk_preview(state,registry):
    """Stable selection across unrelated world updates; never trusts client eligibility."""
    selected=[];sell={};salvage={}
    for identity,row in sorted(equipment(state)['instances'].items()):
        if items.protected(row) or row.get('enhancement',{}).get('level',0) or items.unknown(row,registry):continue
        d=items.definition(registry,row['definition_id']);selected.append((identity,d.machine_id))
        sell['coins']=sell.get('coins',0)+items.sale_price(registry,d.machine_id)
        for key,n in d.salvage:salvage[key]=salvage.get(key,0)+n
    digest=hashlib.sha256(json.dumps(selected,separators=(',',':')).encode()).hexdigest()
    return {'count':len(selected),'protected_count':count(state)-len(selected),'selection_digest':digest,'sell':sell,'salvage':salvage}

def process_all(state,registry,name,p):
    if set(p)!={'selection_digest'} or type(p['selection_digest']) is not str:raise ValidationError('请先确认装备处理预览')
    preview=bulk_preview(state,registry)
    if p['selection_digest']!=preview['selection_digest']:raise ConflictError('装备列表已变化，请重新确认一键处理')
    if not preview['count']:raise ValidationError('没有可处理的装备；穿戴、锁定、收藏和强化装备已保留')
    amounts=preview['sell' if name=='equipment_sell_all' else 'salvage']
    e=thaw_json(equipment(state))
    for identity,row in tuple(e['instances'].items()):
        if items.protected(row) or row.get('enhancement',{}).get('level',0) or items.unknown(row,registry):continue
        del e['instances'][identity]
    capacity=sect.capacity_source(state,registry)['effective']
    needed=sum(n for key,n in amounts.items() if holdings.definition(registry,key).warehouse_counted)
    if holdings.stock_size(state.domains['inventory'],registry)+needed>capacity:raise ValidationError('仓库空间不足，全部装备已保留')
    stock,result=operations.grant(state.domains['inventory'],registry,amounts,capacity=capacity)
    if any(result['discarded'].values()):raise ValidationError('不能丢弃交易或分解产物')
    return replace(state,domains={**state.domains,'equipment':e,'inventory':stock})

def command(state,registry,name,p):
    if name in ('equipment_sell_all','equipment_salvage_all'):return process_all(state,registry,name,p)
    if name in ('equipment_sell','equipment_salvage') and set(p)=={'instance_ids'}:
        identities=p['instance_ids']
        if not isinstance(identities,(list,tuple)) or not identities or any(type(i) is not str for i in identities) or len(set(identities))!=len(identities):raise ValidationError('请选择不重复的装备实例')
        candidate=state
        for identity in identities:candidate=process(candidate,registry,identity,'SELL' if name=='equipment_sell' else 'SALVAGE')
        return candidate
    if name in ('equipment_lock','equipment_favorite'):
        if set(p)!={'instance_id','value'}:raise ValidationError('请选择装备保护状态')
        e=items.flag(equipment(state),p['instance_id'],'locked' if name=='equipment_lock' else 'favorite',p['value'])
    else:
        if set(p)!={'instance_id'}:raise ValidationError('请选择装备实例')
        identity=p['instance_id']
        if name=='equipment_equip':
            if not can_equip_realm(state,registry,items.get(equipment(state),identity)['definition_id']):raise ValidationError('此灵品Boss装备需要筑基境界（第501级）才能穿戴。')
            # Change the loadout only; the ongoing battle owns its immutable snapshot.
            e=items.equip(equipment(state),registry,identity,False)
        elif name=='equipment_unequip':e=items.unequip(equipment(state),registry,identity,False)
        else:return process(state,registry,identity,'SELL' if name=='equipment_sell' else 'SALVAGE')
    return replace(state,domains={**state.domains,'equipment':e})

def automate(state,registry):
    # At most16 new arrivals; policy edits do not retroactively select old inventory.
    processed=0
    for identity in sorted(equipment(state)['instances']):
        row=equipment(state)['instances'].get(identity)
        if row['evaluation']!='PENDING':continue
        result='REVIEW' if row['policy_epoch']!=state.domains['automation']['epoch'] else items.evaluate(equipment(state),registry,identity,state.domains['automation']['equipment'])
        if result in ('SELL','SALVAGE') and len(equipment(state)['audit'])>=items.AUDIT_LIMIT:result='REVIEW'
        if result in ('SELL','SALVAGE'):
            try:
                state=process(state,registry,identity,result)
                d=items.definition(registry,row['definition_id']);e=thaw_json(equipment(state))
                e['audit'].append({'instance_id':identity,'definition_id':d.machine_id,'provenance':row['provenance'],'action':result,'amounts':{'coins':items.sale_price(registry,d.machine_id)} if result=='SELL' else dict(d.salvage),'policy_epoch':row['policy_epoch']})
                state=replace(state,domains={**state.domains,'equipment':e})
            except ValidationError:result='REVIEW'
        if identity in equipment(state)['instances']:
            e=thaw_json(equipment(state));e['instances'][identity]['evaluation']=result;state=replace(state,domains={**state.domains,'equipment':e})
        p=policy.record(state.domains['automation'],result,identity,{'KEEP':'装备已保留','SELL':'装备已出售','SALVAGE':'装备已分解','REVIEW':'装备等待人工确认'}[result]);state=replace(state,domains={**state.domains,'automation':p})
        processed+=1
        if processed>=16:break
    return state

def view(state,registry):
    p=equipment(state);rules=state.domains['automation']['equipment'];running=state.time['pending'] is None
    rows=[]
    for identity,row in sorted(p['instances'].items()):
        d=items.definition(registry,row['definition_id']);current=p['instances'].get(p['slots'].get(d.slot));safe=not items.protected(row) and not items.unknown(row,registry)
        rows.append({'instance_id':identity,'definition_id':d.machine_id,'name':d.display_name,'quality':d.quality,'slot':d.slot,'slot_name':dict(EQUIPMENT_SLOTS)[d.slot],'asset_id':d.asset_id,'stats':growth.stats({'max_hp_milli':row['stats'].get('max_hp_milli',0),'attack_milli':row['stats'].get('attack_milli',0),'armor_milli':row['stats'].get('armor_milli',0)}),'comparison':{k:(row['stats'].get(k,0)-(current['stats'].get(k,0) if current else 0))/1000 for k in items.STATS},'equipped':row['equipped'],'locked':row['locked'],'favorite':row['favorite'],'sell_coins':items.sale_price(registry,d.machine_id),'salvage':[{'resource_id':k,'name':holdings.definition(registry,k).display_name,'quantity':n} for k,n in d.salvage],'evaluation':items.evaluate(p,registry,identity,rules),'can_equip':can_equip_realm(state,registry,d.machine_id) and running and not row['equipped'] and not items.unknown(row,registry),'can_unequip':running and row['equipped'],'can_sell':running and safe,'can_salvage':running and safe,'can_flag':running})
    from src.application.combat_effect_views import equipment as effects_view
    for row in rows:
        row.update(effects_view(registry,row['definition_id']))
        actual=items.effective_stats(p['instances'][row['instance_id']])
        row['stats']={key.removesuffix('_milli').removesuffix('_bps'):n/(100 if key.endswith('_bps') else 1000) for key,n in actual.items()}
        ranges=items.equipment_ranges(row['definition_id'],craft=p['instances'][row['instance_id']].get('roll_version')==items.CRAFT_ROLL_VERSION) if p['instances'][row['instance_id']].get('roll_version') in (items.ROLL_VERSION,items.CRAFT_ROLL_VERSION) else items.definition(registry,row['definition_id']).stat_ranges
        row['stat_ranges']={k.removesuffix('_milli').removesuffix('_bps'):[a/(100 if k.endswith('_bps') else 1000),b/(100 if k.endswith('_bps') else 1000)] for k,a,b,step in ranges}
        row['rolled']=bool(p['instances'][row['instance_id']].get('roll_version') or p['instances'][row['instance_id']]['affixes'])
        row['quality_name']={'white':'凡品','green':'灵品','blue':'玄品','rare':'稀有'}[row['quality']]
        saved=p['instances'][row['instance_id']]
        if saved['affixes'] and items.known_affixes(saved,items.definition(registry,row['definition_id'])):
            key,low,high,step=COMBAT_AFFIX_RANGES[items.definition(registry,row['definition_id']).slot]
            row['stat_ranges'][key.removesuffix('_bps')]=[low/100,high/100]
        row['comparison']={k:(actual.get(k,0)-(items.effective_stats(p['instances'][p['slots'][row['slot']]]).get(k,0) if row['slot'] in p['slots'] else 0))/(100 if k.endswith('_bps') else 1000) for k in items.STATS if k in actual or (row['slot'] in p['slots'] and k in p['instances'][p['slots'][row['slot']]]['stats'])}
    return {'instances':rows,'slots':[{'id':slot,'name':name,'instance_id':p['slots'].get(slot)} for slot,name in EQUIPMENT_SLOTS],'policy':rules,'history':state.domains['automation']['log'],'count':len(rows),'bulk':{**bulk_preview(state,registry),'can_process':running}}


def can_equip_realm(state,registry,definition_id):
    c=growth.leveling.config(registry)
    return not c or definition_id not in c['restricted_equipment'] or (partition(state)['current_realm']=='realm_1' and growth.leveling.level(partition(state),c)>=501)

"""Read-only Chinese effect explanations from the same committed definitions."""
from src.core.state.envelope import thaw_json
from src.data.combat.mechanics import settings

TRIGGERS={'battle_start':'开战','turn_start':'回合开始','turn_end':'回合结束','before_attack':'攻击前',
 'on_hit':'普通攻击命中','on_crit':'普通攻击暴击','on_evade':'成功闪避','on_block':'成功格挡',
 'on_hurt':'受到伤害','before_hurt':'直接伤害结算前','lethal':'受到致命伤害','shield_break':'护盾击破',
 'status_applied':'获得状态','status_removed':'状态移除','on_heal':'获得治疗','on_shield':'获得护盾',
 'skill_cast':'施放技能','kill':'击杀','battle_end':'战斗结束','on_support':'获得治疗或护盾','status_resisted':'抵抗异常状态'}
OPERATIONS={'damage':'伤害','heal':'回复生命','shield':'获得护盾','status':'施加状态','consume':'消耗状态',
 'cleanse':'净化','dispel':'驱散','cooldown':'缩短技能冷却','resource':'回复真气','revive':'免死并保留生命',
 'reduce':'降低本次直接伤害','convert':'转为延迟伤害','extend':'延长状态','shorten':'缩短状态','remove_shield':'削除护盾'}
VALUES={'own.attack_milli':'自身攻击','target.attack_milli':'目标攻击','own.max_hp':'自身最大生命',
 'own.hp_bps':'自身生命比例','target.hp_bps':'目标生命比例','own.shield':'自身护盾','target.shield':'目标护盾',
 'target.armor_milli':'目标防御','own.speed_bps':'自身速度','target.speed_bps':'目标速度','event.amount':'本次伤害/回复量',
 'event.kind':'直接攻击标记','event.melee':'本次为近战直接攻击','event.critical':'暴击标记','event.tier':'精英/Boss标记','event.negative':'负面状态标记',
 'event.cleansed':'净化数量','event.category':'技能类型','target.dead':'目标已被击败','own.dot':'自身持续伤害层数',
 'own.negatives':'自身负面状态数','target.negatives':'目标负面状态数','own.clean_turns':'未受伤回合数',
 'turn':'当前回合','level':'功法等级','types':'已触发效果类型数','own.unique_negatives':'本场承受过的不同负面状态数','own.unique_elements':'本场承受过的不同元素数','event.new_element':'首次承受此元素','event.new_negative':'首次承受此负面状态','event.new_kind':'首次承受此伤害类型','event.shield_hit':'攻击接触护盾','event.removed_shield':'本次削除护盾量','event.gap_turns':'距上次施法回合数'}

def expression(value,config):
    if value is True:return '满足条件'
    if value is False:return '不满足条件'
    if isinstance(value,(int,float)):return str(value)
    if isinstance(value,str):
        if value.startswith('event.is_'):
            return '本次为'+{'wood':'木','earth':'土','metal':'金','water':'水','fire':'火','ice':'冰','poison':'毒','yin':'阴','lightning':'雷','neutral':'无'}[value[9:]]+'属性'
        if '.stack:' in value:
            who,key=value.split('.stack:');return ('自身' if who=='own' else '目标')+config['statuses'][key]['name']+'层数'
        if '.history:' in value:
            who,key=value.split('.history:')
            if key in ('last_hurt_turn','last_skill_turn','last_movement_turn'):return {'last_hurt_turn':'最近受伤回合','last_skill_turn':'最近施法回合','last_movement_turn':'最近身法触发回合'}[key]
            return ('自身' if who=='own' else '目标')+'累计'+{'hit':'命中','evade':'闪避','block':'格挡','skill':'施法'}.get(key,'触发')+'次数'
        return VALUES.get(value,'战斗条件')
    op,*args=value;parts=[expression(v,config) for v in args]
    if op=='if':return '('+parts[0]+'时 '+parts[1]+'，否则 '+parts[2]+')'
    if op in ('gt','ge','lt','le','eq') and len(args)==2 and isinstance(args[0],str) and args[0].endswith('hp_bps') and type(args[1]) is int:
        parts[1]=str(args[1]/100).removesuffix('.0')+'%'
    if op=='eq' and args[0]=='event.category':parts[1]={1:'绝技',2:'终极'}.get(args[1],parts[1])
    if op=='eq' and isinstance(args[0],str) and args[0].startswith('event.') and args[0]!='event.category' and args[1] in (0,1):parts[1]='是' if args[1] else '否'
    if op=='mul' and type(args[1]) is int:return parts[0]+'的'+str(args[1]/100).removesuffix('.0')+'%'
    signs={'gt':' > ','ge':' ≥ ','lt':' < ','le':' ≤ ','eq':' = ','add':' + ','sub':' − ','and':' 且 ','or':' 或 ','div':' ÷ ','mul':' × '}
    if op in signs:return '('+signs[op].join(parts)+')'
    if op in ('min','max'):return ('较小值' if op=='min' else '较大值')+'('+ '、'.join(parts)+')'
    return '不满足('+parts[0]+')'

def describe(row,config):
    out=[]
    for rule in row['rules']:
        parts=[TRIGGERS[rule['trigger']]]
        if rule.get('category'):parts.append('自动施放'+('绝技' if rule['category']=='special' else '终极'))
        if rule.get('every',1)>1:parts.append('每'+str(rule['every'])+'回合')
        if 'condition' in rule:parts.append('条件：'+expression(rule['condition'],config))
        if rule.get('chance',10000)<10000:parts.append('概率'+str(rule['chance']/100).removesuffix('.0')+'%')
        effects=[]
        for effect in rule['effects']:
            label=OPERATIONS[effect['op']]
            if effect.get('target')=='other':label='对目标'+label
            if 'status' in effect:label+='「'+config['statuses'][effect['status']]['name']+'」'
            if effect.get('amount'):
                amount=effect['amount']
                label+=' '+(str(amount/100).removesuffix('.0')+'%' if effect['op'] in ('reduce','convert') and type(amount) is int else expression(amount,config))
            if effect['op']=='damage' and 'count' in effect:label+=' ×'+expression(effect['count'],config)+'段'
            if 'stacks' in effect:label+=' '+expression(effect['stacks'],config)+'层'
            if effect['op']=='status':label+='，持续'+expression(effect.get('duration',config['statuses'][effect['status']]['duration']),config)+'回合'
            if effect['op']=='status':
                spec=config['statuses'][effect['status']]
                for flag,text in (('consume_on_skill','施法后消耗'),('consume_on_heal','治疗后消耗'),('consume_on_hit','命中后消耗'),('consume_on_support','治疗或护盾后消耗')):
                    if spec.get(flag):label+='，'+text
            if effect['op']=='shield':label+='，持续'+str(effect.get('duration',3))+'回合'
            if 'condition' in effect:label+='（'+expression(effect['condition'],config)+'）'
            effects.append(label)
        parts.append('；'.join(effects))
        if rule.get('cost'):parts.append('消耗真气'+str(rule['cost']))
        if rule.get('cooldown'):parts.append('冷却'+str(rule['cooldown'])+'回合')
        parts.append('每回合最多'+str(rule.get('per_turn',1))+'次')
        if rule.get('per_battle',10000)<10000:parts.append('每场最多'+str(rule['per_battle'])+'次')
        out.append(' · '.join(parts))
    return out

def technique(registry,key):
    config=settings(registry)
    if not config or key not in config['techniques']:return {}
    row=config['techniques'][key]
    return {'effect_description':row['description'],'effect_rules':describe(row,config),'effects_version':config['version']}

def equipment(registry,key):
    config=settings(registry)
    if not config or key not in config['equipment']:return {}
    row=config['equipment'][key]
    return {'effect_description':row['description'],'effect_direction':row['direction'],'effect_rules':describe(row,config),'effects_version':config['version']}

def battle(registry,b):
    config=settings(registry)
    if not config or 'mechanics' not in b:return {}
    part=b['mechanics'];statuses={}
    for actor in ('player','enemy'):
        statuses[actor]=[{**thaw_json(row),'name':config['statuses'][row['status_id']]['name']} for row in part['statuses'][actor]]
    sources={s['group']+':'+s['id']:config[s['group']][s['id']]['name'] for s in part['sources']}
    if part['enemy_source']:sources['enemies:'+part['enemy_source']]=config['enemies'][part['enemy_source']]['name']
    skills=[]
    for source in part['sources']:
        row=config[source['group']][source['id']]
        for rule in row['rules']:
            if not rule.get('category'):continue
            key=source['group']+':'+source['id']+':'+rule['id']
            skills.append({'source_id':source['id'],'name':row['name'],'category':rule['category'],
                'cooldown_remaining':max(0,part['ready'].get(key,0)-b['step']),
                'used':part['counts'].get(key,0),'max_uses':rule.get('per_battle',10000),'cost':rule.get('cost',0)})
    return {'effects':{'statuses':statuses,'shields':thaw_json(part['shields']),'resources':thaw_json(part['resources']),
                       'sources':sources,'skills':skills,'death_prevention_used':part['death_prevention']}}

def event_source(registry,event):
    config=settings(registry);source=event.get('source_id','')
    if not config or ':' not in source:return ''
    group,key=source.split(':',1)
    return config.get(group,{}).get(key,{}).get('name','')

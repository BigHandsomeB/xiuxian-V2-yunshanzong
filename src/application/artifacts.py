"""Artifact intents and read models; caller owns the existing SQLite receipt transaction."""
from dataclasses import replace
from src.core.state.envelope import thaw_json
from src.core.time.world import paused
from src.core.validation import ValidationError, integer
from src.data.artifacts.definitions import settings, definition
from src.data.registry import DefinitionKey
from src.systems.artifacts import artifacts as domain
from src.systems.dungeons.progress import cleared
from src.systems.inventory import operations


def blocked(state):
    battle=state.domains.get('combat',{}).get('battle') or {}
    return paused(state.time) or bool(state.time['pending']) or state.domains['dungeon']['auto']['enabled'] or battle.get('status') in ('ACTIVE','PLAYER_WIN')


def forge_level(state):
    return max((row['level'] for row in state.domains['sect']['buildings'].values() if row['definition_id']=='forge'), default=0)


def craft_reasons(state,registry,identity):
    row=definition(registry,identity);part=domain.partition(state);reasons=[]
    if identity in part['owned']:reasons.append('已拥有此法宝，每种仅炼制一件')
    if part['job']:reasons.append('已有法宝正在炼制')
    if forge_level(state)<row['min_forge_level']:reasons.append('炼器阁等级不足')
    if cleared(state.domains['dungeon'],row['source_dungeon_id'])<row['unlock_floor']:reasons.append('请先击败来源副本100层Boss')
    return reasons


def enhance_cost(registry,identity,n):
    cfg=settings(registry)['enhancement'];row=definition(registry,identity)
    cost={key:v*n for key,v in cfg['cost'].items()}
    if n>=cfg['core_from_level']:cost[row['core_material_id']]=n-cfg['core_from_level']+1
    return cost


def spend(state,registry,cost):
    reserves=state.domains['sect_management']['material_reserves']
    stock=state.domains['inventory']['holdings']
    for rid,n in cost.items():
        if stock.get(rid,0)-n<reserves.get(rid,0):raise ValidationError('材料不足或已被保留，请先调整材料保留量')
    # In-flight recipes have already paid their inputs. Never consume those twice.
    inventory,_=operations.consume(state.domains['inventory'],registry,cost)
    return inventory


def transition(state,registry,name,payload):
    cfg=settings(registry)
    if not cfg:raise ValidationError('法宝尚未开放')
    part=thaw_json(domain.partition(state));cost={};counters=dict(state.identity)
    if name=='artifact_unequip':
        if payload:raise ValidationError('卸下法宝不需要额外参数')
        if blocked(state):raise ValidationError('请先停止挂机、结束并领取当前战斗后再培养或更换法宝')
        part['equipped']=None
    else:
        expected={'artifact_id','resource_id','quantity'} if name=='artifact_feed' else {'artifact_id'}
        if set(payload)!=expected:raise ValidationError('请选择法宝及正确操作参数')
        key=payload['artifact_id'];row=definition(registry,key)
        if name=='artifact_craft':
            reasons=craft_reasons(state,registry,key)
            if reasons:raise ValidationError('；'.join(reasons))
            cost=thaw_json(row['inputs']);counters['event_counter']+=1
            now=state.time['sim_time_ms'];part['job']={'artifact_id':key,'event_id':f'{state.save_id}:{state.generation}:e:{counters["event_counter"]}','started_ms':now,'due_ms':now+row['duration_ms']}
        else:
            if blocked(state):raise ValidationError('请先停止挂机、结束并领取当前战斗后再培养或更换法宝')
            if key not in part['owned']:raise ValidationError('尚未拥有此法宝')
            owned=part['owned'][key]
            if name=='artifact_equip':part['equipped']=key
            elif name=='artifact_feed':
                rid=payload['resource_id'];quantity=payload['quantity'];integer(quantity,'投喂数量',1)
                if not isinstance(rid,str) or rid not in cfg['feed'] or quantity>10000:raise ValidationError('请选择可投喂材料，单次最多10000个')
                maximum=domain.threshold(registry,cfg['growth']['max_level']);remaining=maximum-owned['xp']
                if not remaining:raise ValidationError('法宝已满级，不消耗材料')
                # Cap consumption to the smallest whole count that reaches max level.
                quantity=min(quantity,(remaining+cfg['feed'][rid]-1)//cfg['feed'][rid])
                cost={rid:quantity};owned['xp']=min(maximum,owned['xp']+quantity*cfg['feed'][rid])
            elif name=='artifact_enhance':
                n=owned['enhancement']+1
                if n>cfg['enhancement']['max_level']:raise ValidationError('法宝强化已满级')
                cost=enhance_cost(registry,key,n);owned['enhancement']=n
            else:raise ValidationError('未知法宝操作')
    inventory=spend(state,registry,cost) if cost else state.domains['inventory']
    domain.validate(part,registry)
    return replace(state,identity=counters,domains={**state.domains,'inventory':inventory,domain.DOMAIN:part}),{'operation':name,'cost':cost,**payload}


def view(state,registry):
    cfg=settings(registry)
    if not cfg:return None
    part=domain.partition(state);stock=state.domains['inventory']['holdings'];reserves=state.domains['sect_management']['material_reserves'];rows=[]
    def costs(amounts):
        return [{'resource_id':k,'name':registry.lookup(DefinitionKey('resources',k)).display_name,'quantity':n,'current':stock.get(k,0),'reserved':reserves.get(k,0)} for k,n in amounts.items()]
    def affordable(amounts):return all(stock.get(k,0)-reserves.get(k,0)>=n for k,n in amounts.items())
    for key,row in cfg['artifacts'].items():
        owned=part['owned'].get(key);L=domain.level(registry,owned['xp']) if owned else 1
        reasons=craft_reasons(state,registry,key)
        enhancement=owned['enhancement'] if owned else 0;n=enhancement+1
        cost=enhance_cost(registry,key,n) if n<=cfg['enhancement']['max_level'] else {}
        rows.append({**thaw_json(row),'id':key,'owned':bool(owned),'level':L,'xp':owned['xp'] if owned else 0,'next_xp':domain.threshold(registry,L+1) if L<cfg['growth']['max_level'] else None,'max_level':cfg['growth']['max_level'],'max_enhancement':cfg['enhancement']['max_level'],'enhancement':enhancement,'equipped':part['equipped']==key,'effect_description':cfg['effects'][row['effect_id']]['description'],'source_name':registry.lookup(DefinitionKey('dungeons',row['source_dungeon_id'])).display_name,'requirements':costs(row['inputs']),'craft_reasons':reasons,'can_craft':not paused(state.time) and not state.time['pending'] and not reasons and affordable(row['inputs']),'stats':domain.stats(registry,key,enhancement),'enhance_cost':costs(cost),'can_enhance':bool(owned) and n<=cfg['enhancement']['max_level'] and not blocked(state) and affordable(cost)})
    job=thaw_json(part['job'])
    if job:job.update(remaining_ms=max(0,job['due_ms']-state.time['sim_time_ms']),name=definition(registry,job['artifact_id'])['name'])
    return {'catalog':rows,'equipped':part['equipped'],'job':job,'can_change':not blocked(state),'feed':[{'resource_id':rid,'name':registry.lookup(DefinitionKey('resources',rid)).display_name,'xp':n,'available':max(0,stock.get(rid,0)-reserves.get(rid,0))} for rid,n in cfg['feed'].items()],'route':'#building/forge'}


def validate_state(state,registry):
    if domain.DOMAIN not in state.domains:raise ValidationError('法宝存档需要显式升级')
    part=domain.validate(domain.partition(state),registry)
    job=part['job']
    if job:
        pieces=job['event_id'].split(':')
        try:g,n=int(pieces[1]),int(pieces[3])
        except (ValueError,IndexError) as exc:raise ValidationError('invalid artifact event identity') from exc
        if len(pieces)!=4 or pieces[0]!=state.save_id or pieces[2]!='e' or str(g)!=pieces[1] or str(n)!=pieces[3] or not 1<=g<=state.generation or not 1<=n<=state.identity['event_counter'] or job['started_ms']>state.time['sim_time_ms']:
            raise ValidationError('artifact event outside allocated namespace/time')
        occupied={row['event_id'] for row in state.domains['production']['jobs'].values()}
        for wake in [state.domains.get('automation',{}).get('wake'),state.domains.get('dungeon',{}).get('auto',{}).get('wake'),state.domains.get('ecology',{}).get('wake'),state.domains.get('sect_management',{}).get('supply',{}).get('wake')]:
            if wake:occupied|={wake[k] for k in ('event_id','next_event_id') if wake.get(k)}
        recruit=state.domains['sect_management']['recruit']
        if recruit:occupied.add(recruit['event_id'])
        if job['event_id'] in occupied:raise ValidationError('duplicate artifact event identity')
    return state

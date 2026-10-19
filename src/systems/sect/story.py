"""Pure story facts and reading order; never changes time, combat or rewards."""
from collections.abc import Mapping
from dataclasses import replace
from src.core.state.envelope import thaw_json
from src.core.validation import ValidationError
from src.data.story.definitions import catalog, ID
from src.data.dungeons import expeditions
from src.systems.dungeons import progress
from src.systems.cultivation import growth


def initial():return {'unlocked': [], 'read': []}


def ledger(state):return state.domains.get('sect_management',{}).get('story',initial())


def validate(part):
    if not isinstance(part,Mapping) or set(part)!={'unlocked','read'}:
        raise ValidationError('invalid story ledger')
    for field in ('unlocked','read'):
        values=part[field]
        if not isinstance(values,(list,tuple)) or len(values)>4096 or any(type(x) is not str or not ID.fullmatch(x) for x in values) or len(set(values))!=len(values):
            raise ValidationError('invalid story identities')
    if not set(part['read'])<=set(part['unlocked']):raise ValidationError('read story must be unlocked')
    return part


def _entered(state,registry,condition,events):
    did=condition['dungeon_id'];p=state.domains.get('dungeon',{})
    if progress.cleared(p,did)>0:return True
    b=state.domains.get('combat',{}).get('battle')
    return bool(b and expeditions.owner(registry,b['encounter_id'])==did)


CONDITION_HANDLERS = {
    'always': lambda s,r,c,e: True,
    'floor': lambda s,r,c,e: progress.cleared(s.domains.get('dungeon',{}),c['dungeon_id'])>=c['minimum'],
    'entered': _entered,
    'selected': lambda s,r,c,e: progress.selected(s.domains.get('dungeon',{}))==c['dungeon_id'] or _entered(s,r,c,e),
    'building_level': lambda s,r,c,e: any(b['definition_id']==c['building_kind'] and b['level']>=c['minimum'] for b in s.domains['sect']['buildings'].values()),
    'realm': lambda s,r,c,e: growth.realm(r,s.domains['cultivation']['current_realm']).index>=c['minimum'],
    'event': lambda s,r,c,e: c['event_id'] in e,
}


def unlocked(state,registry,events=()):
    result=set(ledger(state)['unlocked'])
    for node in catalog()['nodes']:
        c=node['condition']
        if CONDITION_HANDLERS[c['kind']](state,registry,c,events):result.add(node['id'])
    return result


def observe(state,registry,events=()):
    if 'sect_management' not in state.domains:return state
    existing=ledger(state);available=unlocked(state,registry,events)
    if available==set(existing['unlocked']):return state
    part=thaw_json(state.domains['sect_management'])
    part['story']={'unlocked':sorted(available),'read':list(existing['read'])}
    return replace(state,domains={**state.domains,'sect_management':part})


def projection(state,registry):
    data=catalog();part=ledger(state);available=unlocked(state,registry);read=set(part['read'])
    next_main=next((n['id'] for n in data['nodes'] if n['track']=='main' and n['id'] not in read),None)
    rows=[]
    for node in data['nodes']:
        nid=node['id'];opened=nid in available;seen=nid in read
        can_read=seen or (opened and (node['track']!='main' or nid==next_main))
        rows.append({'id':nid,'chapter':node['chapter'],'title':node['title'],'track':node['track'],
                     'unlocked':opened,'read':seen,'can_read':can_read,
                     'lines':thaw_json(node['lines']) if can_read else [],
                     'reason':'已阅读，可回看' if seen else '待阅读' if can_read else '先阅读前面的主线' if opened else '随探索与经营进度解锁'})
    return {'chapters':thaw_json(data['chapters']),'nodes':rows,
            'unread_count':sum(n['unlocked'] and not n['read'] for n in rows),
            'read_count':sum(n['read'] for n in rows),'total':len(rows)}


def mark_read(state,registry,payload):
    if not isinstance(payload,Mapping) or set(payload)!={'node_id'} or type(payload['node_id']) is not str:
        raise ValidationError('请选择剧情节点')
    row=next((n for n in projection(state,registry)['nodes'] if n['id']==payload['node_id']),None)
    if row is None or not row['can_read']:raise ValidationError('剧情尚未解锁或请先阅读前面的主线')
    state=observe(state,registry);part=thaw_json(state.domains['sect_management'])
    if row['id'] not in part['story']['read']:part['story']['read'].append(row['id'])
    validate(part['story'])
    return replace(state,domains={**state.domains,'sect_management':part})

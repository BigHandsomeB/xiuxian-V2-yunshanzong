"""Committed settlement observations; never awards rewards or advances the clock."""
from collections.abc import Mapping
from dataclasses import replace
from src.core.state.envelope import thaw_json
from src.core.time.model import plan_window
from src.core.validation import ValidationError, ConflictError, integer

DOMAIN = 'offline_reports'
LIMIT = 5
THRESHOLD_MS = 60000


def empty():
    return {'version': 1, 'active': None, 'unread': [], 'acknowledged_through': -1, 'latest_battle_report': None}


def put(state, data):
    return replace(state, domains={**state.domains, DOMAIN: data})


def snapshot(state,registry=None):
    from src.application.cultivation import partition
    dungeon = state.domains.get('dungeon', {})
    growth = partition(state)
    from src.systems.cultivation import leveling
    c=leveling.config(registry) if registry else None
    total=leveling.xp(growth,c) if c else growth.get('total_xp',growth.get('progress',0))
    current_level=leveling.level(growth,c) if c else None
    return {'inventory': dict(state.domains['inventory']['holdings']),
            'equipment_ids': list(state.domains.get('equipment', {}).get('instances', {})),
            'disciples': sum(g['count'] for g in state.domains['disciples']['groups'].values()),
            'realm': growth.get('current_realm'), 'cultivation': total, 'level':current_level,
            'floors': {'thorn_path': dungeon.get('cleared_floor', 0), **dungeon.get('progress', {})}}


def begin(state, now_ms,registry=None):
    # Existing pending has no baseline: finish it without inventing a report.
    if state.time['pending'] is not None:
        return state
    window = plan_window(state.time, now_ms)
    if window.accepted_ms <= THRESHOLD_MS:
        return state
    data = thaw_json(state.domains.get(DOMAIN, empty()))
    sequence = max(state.revision, data['acknowledged_through']+1, data['unread'][-1]['sequence']+1 if data['unread'] else 0, data['active']['sequence']+1 if data['active'] else 0)
    data['active'] = {'report_id': f'{state.save_id}:{state.generation}:r:{sequence}',
                      'sequence': sequence, 'first_revision': state.revision,
                      'from_sim_ms': window.from_sim_ms, 'target_sim_ms': window.target_sim_ms,
                      'duration': {'actual_ms': window.accepted_ms + window.discarded_ms,
                                   'settled_ms': window.accepted_ms, 'discarded_ms': window.discarded_ms,
                                   'capped': window.discarded_ms > 0},
                      'baseline': snapshot(state,registry), 'production': {},
                      'equipment': {'added_ids': [], 'removed_ids': [], 'sold_ids': [],
                                    'salvaged_ids': [], 'quality_counts': {}},
                      'combat': {'wins': 0, 'losses': 0}, 'recruitment_count': 0,
                      'battle_summary': {'coins':0,'materials':{},'converted_materials':{},'equipment_count':0,'overflow_coins':0,'stop_reason':'NORMAL','stop_sim_ms':None}}
    return put(state, data)


def active(state):
    a = state.domains.get(DOMAIN, {}).get('active')
    # Explicit recovery keeps domains unchanged but cancels the pending cursor.
    return a if a and a['report_id'].startswith(f'{state.save_id}:{state.generation}:r:') else None


def observe_battle_reward(state, amounts, converted, equipment_count, conversion_coins):
    a=active(state)
    if not a or 'battle_summary' not in a:return state
    data=thaw_json(state.domains[DOMAIN]);row=data['active']['battle_summary']
    row['coins']+=amounts.get('coins',0);row['equipment_count']+=equipment_count;row['overflow_coins']+=conversion_coins
    for key,n in amounts.items():
        if key!='coins' and n:row['materials'][key]=row['materials'].get(key,0)+n
    for key,n in converted.items():row['converted_materials'][key]=row['converted_materials'].get(key,0)+n
    return put(state,data)


def observe_stop(state, reason):
    a=active(state)
    if not a or 'battle_summary' not in a:return state
    data=thaw_json(state.domains[DOMAIN]);row=data['active']['battle_summary']
    row['stop_reason']=reason;row['stop_sim_ms']=state.time['sim_time_ms']
    return put(state,data)


def latest_battle(state):
    row=state.domains.get(DOMAIN,{}).get('latest_battle_report')
    return row if row and row['report_id'].startswith(f'{state.save_id}:{state.generation}:r:') else None


def observe_pause(state):
    row=latest_battle(state)
    if not row or row['end_sim_ms']!=state.time['sim_time_ms'] or row['stop_reason']!='NORMAL':return state
    data=thaw_json(state.domains[DOMAIN]);row=data['latest_battle_report']
    row.update(stop_reason='WORLD_PAUSED',stop_sim_ms=state.time['sim_time_ms'])
    return put(state,data)


def observe_equipment(state, identity, quality, action, amounts=None):
    if not active(state):
        return state
    data = thaw_json(state.domains[DOMAIN]); e = data['active']['equipment']
    field = {'GAIN': 'added_ids', 'SELL': 'sold_ids', 'SALVAGE': 'salvaged_ids'}[action]
    if identity in e[field]:
        raise ValidationError('equipment observation repeated')
    e[field].append(identity)
    if amounts is not None and 'battle_summary' in data['active']:
        summary=data['active']['battle_summary'];summary['coins']+=amounts.get('coins',0)
        for rid,n in amounts.items():
            if rid!='coins':summary['materials'][rid]=summary['materials'].get(rid,0)+n
    counts = e['quality_counts'].setdefault(quality, {'gained': 0, 'removed': 0, 'sold': 0, 'salvaged': 0})
    counts[{'GAIN': 'gained', 'SELL': 'sold', 'SALVAGE': 'salvaged'}[action]] += 1
    if action != 'GAIN':
        e['removed_ids'].append(identity); counts['removed'] += 1
    return put(state, data)


def observe_production(state, job, outputs, equipment_quantity):
    if not active(state):
        return state
    data = thaw_json(state.domains[DOMAIN])
    row = data['active']['production'].setdefault(job['recipe_id'], {'completed_count': 0, 'outputs': {}, 'equipment_count': 0})
    row['completed_count'] += 1; row['equipment_count'] += equipment_quantity
    if 'battle_summary' in data['active']:
        summary=data['active']['battle_summary'];summary['coins']+=outputs.get('coins',0)
        for rid,n in outputs.items():
            if rid!='coins':summary['materials'][rid]=summary['materials'].get(rid,0)+n
    for key, count in outputs.items():
        row['outputs'][key] = row['outputs'].get(key, 0) + count
    return put(state, data)


def observe_combat(state, outcome):
    if not active(state):
        return state
    data = thaw_json(state.domains[DOMAIN]); data['active']['combat'][outcome] += 1
    return put(state, data)


def observe_recruitment(state):
    if not active(state):
        return state
    data = thaw_json(state.domains[DOMAIN]); data['active']['recruitment_count'] += 1
    return put(state, data)


def commerce_results(state, start, registry):
    from src.data.economy.market import settings
    ledger = state.domains.get('sect_management', {}).get('commerce', {})
    end = state.time['sim_time_ms']; out = []
    for kind, key in (('auction', 'bids'), ('consignment', 'consignments')):
        for identity, row in ledger.get(key, {}).items():
            if not start < row['end_ms'] <= end:
                continue
            won = row['bid'] > row['npc_bid'] if kind == 'auction' else row['npc_bid'] >= row['reserve']
            coins = (0 if won else row['bid']) if kind == 'auction' else (row['npc_bid'] * (1000-settings(registry)['auction_commission_permille']) // 1000 if won else 0)
            out.append({'kind': kind, 'id': identity, 'resource_id': row['resource_id'],
                        'success': won, 'coins': coins, 'status': 'pending_claim'})
    return out


def add_counts(left, right):
    result = dict(left)
    for key, count in right.items():
        result[key] = result.get(key, 0) + count
    return result


def merge(left, right):
    """Oldest adjacent reports become one summary; preserve all amounts and IDs."""
    out = thaw_json(left)
    out.update(report_id=right['report_id'], sequence=right['sequence'], completed_revision=right['completed_revision'],
               target_sim_ms=right['target_sim_ms'], summary_count=left['summary_count']+right['summary_count'])
    for key in ('actual_ms', 'settled_ms', 'discarded_ms'):
        out['duration'][key] += right['duration'][key]
    out['duration']['capped'] = left['duration']['capped'] or right['duration']['capped']
    out['items'] = {k: n for k, n in add_counts(left['items'], right['items']).items() if n}
    for field in ('added_ids', 'removed_ids', 'sold_ids', 'salvaged_ids'):
        out['equipment'][field] = list(dict.fromkeys([*left['equipment'][field], *right['equipment'][field]]))
    for quality, counts in right['equipment']['quality_counts'].items():
        out['equipment']['quality_counts'][quality] = add_counts(out['equipment']['quality_counts'].get(quality, {}), counts)
    for recipe, row in right['production'].items():
        current = out['production'].setdefault(recipe, {'completed_count': 0, 'outputs': {}, 'equipment_count': 0})
        current['completed_count'] += row['completed_count']; current['equipment_count'] += row['equipment_count']
        current['outputs'] = add_counts(current['outputs'], row['outputs'])
    out['combat']['wins'] += right['combat']['wins']; out['combat']['losses'] += right['combat']['losses']
    for did, row in right['combat']['floors'].items():
        current = out['combat']['floors'].setdefault(did, dict(row)); current['after'] = row['after']
    out['recruitment']['completed_count'] += right['recruitment']['completed_count']
    out['recruitment']['after'] = right['recruitment']['after']
    out['cultivation']['realm_after'] = right['cultivation']['realm_after']
    out['cultivation']['after'] = right['cultivation']['after']
    out['cultivation']['level_after']=right['cultivation'].get('level_after')
    out['cultivation']['levels_gained']=left['cultivation'].get('levels_gained',0)+right['cultivation'].get('levels_gained',0)
    out['commerce'].extend(thaw_json(right['commerce']))
    return out


def finish(state, result, registry):
    a = active(state)
    if not a:
        return state, None
    if result.status == 'PENDING':
        time = thaw_json(state.time); time['pending']['report_id'] = a['report_id']
        return replace(state, time=time), None
    data = thaw_json(state.domains[DOMAIN]); report = data['active']; before = report.pop('baseline'); after = snapshot(state,registry)
    if before.get('level') is None:
        from src.systems.cultivation import leveling
        c=leveling.config(registry)
        if c and before.get('realm') in ('realm_0','realm_1'):
            legacy={'player_id':state.save_id+':hero','current_realm':before['realm'],'progress':before['cultivation'],'growth_revision':1}
            before['level']=leveling.level(legacy,c);before['cultivation']=leveling.xp(legacy,c)
    battle_summary=report.pop('battle_summary',None)
    if battle_summary is not None:
        battle_summary=thaw_json(battle_summary)
        wins=report['combat']['wins'];count=wins+report['combat']['losses']
        battle_summary['equipment_count']=sum(row['gained'] for row in report['equipment']['quality_counts'].values())
        battle_summary.update(report_id=report['report_id'],duration_ms=report['duration']['actual_ms'],from_sim_ms=report['from_sim_ms'],end_sim_ms=state.time['sim_time_ms'],battles=count,wins=wins,win_rate_bps=10000*wins//count if count else 0)
        if battle_summary['stop_sim_ms'] is None:battle_summary['stop_sim_ms']=state.time['sim_time_ms']
        data['latest_battle_report']=battle_summary
    report.update(version=1, completed_revision=state.revision, summary_count=1,
                  items={key: after['inventory'].get(key, 0)-before['inventory'].get(key, 0)
                         for key in before['inventory'].keys() | after['inventory'].keys()
                         if after['inventory'].get(key, 0) != before['inventory'].get(key, 0)},
                  recruitment={'completed_count': report.pop('recruitment_count'), 'before': before['disciples'], 'after': after['disciples']},
                  cultivation={'realm_before': before['realm'], 'realm_after': after['realm'], 'before': before['cultivation'], 'after': after['cultivation'], 'level_before':before.get('level'), 'level_after':after.get('level'), 'levels_gained':max(0,(after.get('level') or 0)-(before.get('level') or 0))},
                  commerce=commerce_results(state, report['from_sim_ms'], registry))
    report['combat']['floors'] = {did: {'before': before['floors'].get(did, 0), 'after': after['floors'].get(did, 0)}
                                 for did in before['floors'].keys() | after['floors'].keys()}
    data['active'] = None; data['unread'].append(report)
    while len(data['unread']) > LIMIT:
        data['unread'][:2] = [merge(data['unread'][0], data['unread'][1])]
    return put(state, data), thaw_json(report)


def acknowledge(state, report_id):
    data = thaw_json(state.domains.get(DOMAIN, empty()))
    parts = report_id.split(':') if type(report_id) is str else []
    if len(parts) != 4 or parts[0] != state.save_id or parts[2] != 'r' or not parts[1].isdigit() or not 1 <= int(parts[1]) <= state.generation or not parts[3].isdigit():
        raise ValidationError('invalid report identity')
    sequence = int(parts[3])
    if sequence <= data['acknowledged_through']:
        return state
    if not data['unread'] or data['unread'][0]['report_id'] != report_id:
        raise ConflictError('report changed; refresh before acknowledging')
    data['unread'].pop(0); data['acknowledged_through'] = sequence
    return put(state, data)


def validate(state):
    try:
        _validate(state)
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValidationError('invalid offline report partition') from exc


def _validate(state):
    data = state.domains.get(DOMAIN)
    if data is None:
        return
    if not isinstance(data, Mapping) or not (set(empty())-{'latest_battle_report'}<=set(data)) or set(data)-set(empty()) or type(data['version']) is not int or data['version'] != 1:
        raise ValidationError('invalid offline report partition')
    if data.get('latest_battle_report') is not None:validate_battle_summary(data['latest_battle_report'],complete=True)
    integer(data['acknowledged_through'], 'report read watermark', -1)
    if not isinstance(data['unread'], (list, tuple)) or len(data['unread']) > LIMIT:
        raise ValidationError('invalid report queue')
    previous = data['acknowledged_through']
    for report in data['unread']:
        validate_report(state, report)
        if report['sequence'] <= previous:
            raise ValidationError('report queue must be ordered')
        previous = report['sequence']
    a = data['active']
    pending = state.time['pending']
    if a is not None:
        validate_common(state, a)
        if 'battle_summary' in a:validate_battle_summary(a['battle_summary'])
        if not isinstance(a.get('baseline'), Mapping):raise ValidationError('report baseline missing')
        inherited = not a['report_id'].startswith(f'{state.save_id}:{state.generation}:r:')
        integer(a['recruitment_count'], 'report recruitment count')
        base = a['baseline']
        if set(base)-{'level'} != {'inventory','equipment_ids','disciples','realm','cultivation','floors'}:raise ValidationError('invalid baseline fields')
        for n in base['inventory'].values():integer(n,'baseline inventory')
        integer(base['disciples'],'baseline disciples');integer(base['cultivation'],'baseline cultivation')
        for n in base['floors'].values():integer(n,'baseline floor')
        if not isinstance(base['equipment_ids'],(list,tuple)) or any(type(i) is not str for i in base['equipment_ids']):raise ValidationError('invalid baseline equipment')
        if a['sequence'] <= previous:raise ValidationError('active report sequence precedes unread queue')
        if inherited and pending is None:return  # Canceled by the existing explicit recovery contract.
        if not pending or pending.get('report_id') != a['report_id']:raise ValidationError('report baseline/pending mismatch')
        if (a['from_sim_ms'], a['target_sim_ms'], a['duration']['settled_ms']) != (pending['from_sim_ms'], pending['target_sim_ms'], pending['accepted_ms']):
            raise ValidationError('report window mismatch')
    elif pending and 'report_id' in pending:
        raise ValidationError('pending report missing')


def validate_battle_summary(row, *, complete=False):
    fields={'coins','materials','converted_materials','equipment_count','overflow_coins','stop_reason','stop_sim_ms'}
    if complete:fields|={'report_id','duration_ms','from_sim_ms','end_sim_ms','battles','wins','win_rate_bps'}
    if not isinstance(row,Mapping) or set(row)!=fields:raise ValidationError('invalid battle summary fields')
    for key in ('coins','equipment_count','overflow_coins'):integer(row[key],'battle summary '+key)
    if row['overflow_coins']>row['coins']:raise ValidationError('invalid conversion summary')
    for key in ('materials','converted_materials'):
        if not isinstance(row[key],Mapping):raise ValidationError('invalid battle materials')
        for rid,n in row[key].items():
            if type(rid) is not str or not rid:raise ValidationError('invalid battle material id')
            integer(n,'battle material count')
    if row['stop_reason'] not in ('NORMAL','DEFEATED','STORAGE_FULL','WORLD_PAUSED','COMPLETED','LEGACY_BATTLE'):raise ValidationError('invalid battle stop reason')
    if row['stop_sim_ms'] is not None:integer(row['stop_sim_ms'],'battle stop time')
    if complete:
        if type(row['report_id']) is not str or not row['report_id']:raise ValidationError('invalid battle report id')
        for key in ('duration_ms','from_sim_ms','end_sim_ms','battles','wins','win_rate_bps'):integer(row[key],'battle '+key)
        if row['wins']>row['battles'] or row['win_rate_bps']!=(10000*row['wins']//row['battles'] if row['battles'] else 0):raise ValidationError('invalid battle win rate')
        if not row['from_sim_ms']<=row['stop_sim_ms']<=row['end_sim_ms']:raise ValidationError('invalid battle report time')


def validate_common(state, report):
    if not isinstance(report, Mapping):
        raise ValidationError('report must be an object')
    integer(report['sequence'], 'report sequence'); integer(report['first_revision'], 'report first revision')
    parts = report['report_id'].split(':') if type(report['report_id']) is str else []
    if len(parts) != 4 or parts[0] != state.save_id or parts[2] != 'r' or not parts[1].isdigit() or not 1 <= int(parts[1]) <= state.generation or parts[3] != str(report['sequence']):
        raise ValidationError('report identity mismatch')
    integer(report['from_sim_ms'], 'report from time'); integer(report['target_sim_ms'], 'report target time')
    if report['target_sim_ms'] < report['from_sim_ms']:raise ValidationError('invalid report simulation window')
    d = report['duration']
    if not isinstance(d, Mapping) or set(d) != {'actual_ms','settled_ms','discarded_ms','capped'}:raise ValidationError('invalid duration fields')
    for key in ('actual_ms', 'settled_ms', 'discarded_ms'):
        integer(d[key], 'report '+key)
    if d['actual_ms'] != d['settled_ms'] + d['discarded_ms'] or type(d['capped']) is not bool or d['capped'] != (d['discarded_ms'] > 0) or d['settled_ms'] <= THRESHOLD_MS:
        raise ValidationError('invalid report duration')
    e = report['equipment']
    for field in ('added_ids', 'removed_ids', 'sold_ids', 'salvaged_ids'):
        ids = e[field]
        if not isinstance(ids, (list, tuple)) or any(type(i) is not str or not i.startswith(state.save_id+':') for i in ids) or len(set(ids)) != len(ids):
            raise ValidationError('invalid report equipment IDs')
    for quality, counts in e['quality_counts'].items():
        if quality not in ('white', 'green', 'blue', 'rare') or set(counts) != {'gained', 'removed', 'sold', 'salvaged'}:
            raise ValidationError('invalid report quality counts')
        for value in counts.values(): integer(value, 'report equipment count')
        if counts['removed'] != counts['sold'] + counts['salvaged']: raise ValidationError('invalid removed equipment count')
    for field,count_key in (('added_ids','gained'),('removed_ids','removed'),('sold_ids','sold'),('salvaged_ids','salvaged')):
        if len(e[field]) != sum(row[count_key] for row in e['quality_counts'].values()):raise ValidationError('equipment summary/IDs mismatch')
    if set(e['removed_ids']) != set(e['sold_ids']) | set(e['salvaged_ids']):raise ValidationError('equipment disposition mismatch')
    for key in ('wins', 'losses'): integer(report['combat'][key], 'report '+key)
    for row in report['production'].values():
        integer(row['completed_count'], 'production count'); integer(row['equipment_count'], 'equipment output count')
        for count in row['outputs'].values(): integer(count, 'production output')


def validate_report(state, report):
    try:
        validate_common(state, report)
        integer(report['summary_count'], 'summary count', 1); integer(report['completed_revision'], 'report completion')
        for value in report['items'].values(): integer(value, 'item delta', -(2**63))
        for row in report['combat']['floors'].values():
            integer(row['before'], 'floor before'); integer(row['after'], 'floor after')
        for key in ('before', 'after', 'completed_count'): integer(report['recruitment'][key], 'recruitment '+key)
        for key in ('before', 'after'): integer(report['cultivation'][key], 'cultivation '+key)
        if not isinstance(report['commerce'], (list, tuple)): raise ValidationError('invalid commerce report')
        for row in report['commerce']:
            if set(row) != {'kind','id','resource_id','success','coins','status'} or row['kind'] not in ('auction','consignment') or row['status'] != 'pending_claim' or type(row['success']) is not bool or type(row['id']) is not str or type(row['resource_id']) is not str:raise ValidationError('invalid commerce result')
            integer(row['coins'],'commerce result coins')
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValidationError('invalid offline report') from exc


def names(state, registry):
    """Names remain read projections, including resources no longer in Inventory."""
    from src.data.registry import DefinitionKey
    ids={'items': set(), 'recipes': set(), 'dungeons': set(), 'realms': set()}
    for report in state.domains.get(DOMAIN, empty())['unread']:
        ids['items'].update(report['items'])
        for recipe, row in report['production'].items():
            ids['recipes'].add(recipe); ids['items'].update(row['outputs'])
        ids['items'].update(row['resource_id'] for row in report['commerce'])
        ids['dungeons'].update(report['combat']['floors'])
        ids['realms'].update(r for r in (report['cultivation']['realm_before'],report['cultivation']['realm_after']) if r)
    latest=latest_battle(state)
    if latest:ids['items'].update(latest['materials']);ids['items'].update(latest['converted_materials'])
    domains={'items':'resources','recipes':'production','dungeons':'dungeons','realms':'realms'}
    return {kind: {key: registry.lookup(DefinitionKey(domains[kind],key)).display_name for key in keys} for kind,keys in ids.items()}

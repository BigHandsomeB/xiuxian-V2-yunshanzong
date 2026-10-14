"""Bounded read projections; full history remains in the committed save/receipt."""
from src.core.state.envelope import thaw_json
from src.core.validation import ValidationError, NotFoundError, integer, uuid4_id

HISTORY_LIMIT=20
REPORT_ID_LIMIT=50


def compact_report(report):
    report=thaw_json(report)
    for key in ('added_ids','removed_ids','sold_ids','salvaged_ids'):
        rows=report['equipment'][key]
        if len(rows)>REPORT_ID_LIMIT:
            report['equipment']['ids_truncated']=True
            report['equipment'][key]=rows[:REPORT_ID_LIMIT]
    if len(report.get('commerce',[]))>HISTORY_LIMIT:
        report['commerce_total']=len(report['commerce']);report['commerce']=report['commerce'][-HISTORY_LIMIT:]
    return report


def compact_view(view):
    # Caller owns the detached wire projection; never change a StateEnvelope.
    view=thaw_json(view)
    for parent,key in ((view.get('equipment',{}),'history'),(view.get('economy',{}).get('automation',{}),'log'),(view.get('economy',{}).get('automation',{}),'overflow_log'),(view.get('sect_services',{}),'log'),(view.get('market',{}),'history')):
        rows=parent.get(key)
        if rows is not None and len(rows)>HISTORY_LIMIT:
            parent[key+'_total']=len(rows);parent[key]=rows[-HISTORY_LIMIT:]
    if 'offline_reports' in view:view['offline_reports']=[compact_report(r) for r in view['offline_reports']]
    return view


def details(game,save_id,kind,*,offset=0,limit=50,report_id=None,request_id=None):
    integer(offset,'history offset');integer(limit,'history limit',1)
    if limit>100:raise ValidationError('history page too large')
    state=game.query(save_id)
    if kind=='report':
        for report in state.domains.get('offline_reports',{}).get('unread',()):
            if report['report_id']==report_id:return thaw_json(report)
        raise NotFoundError('report not found')
    if kind=='settlement':
        uuid4_id(request_id,'request id');record=game.store.receipt(save_id,state.generation,request_id)
        if record is None or record.kind!='settlement':raise NotFoundError('settlement not found')
        from dataclasses import asdict
        return asdict(game.foundation._decode_receipt(record))
    sources={'equipment':state.domains.get('equipment',{}).get('audit',()),'automation':state.domains.get('automation',{}).get('log',()),'overflow':state.domains.get('automation',{}).get('overflow_log',()),'sect':state.domains.get('sect_management',{}).get('log',()),'commerce':state.domains.get('sect_management',{}).get('commerce',{}).get('history',())}
    if kind not in sources:raise ValidationError('unknown history kind')
    rows=sources[kind]
    return {'kind':kind,'offset':offset,'limit':limit,'total':len(rows),'rows':thaw_json(rows[offset:offset+limit])}

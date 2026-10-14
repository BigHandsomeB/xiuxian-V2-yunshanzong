"""Asset-only lifecycle: impact preview, explicit confirmation, references and controlled files.
No caller paths; no Gameplay imports. Historical snapshots survive detach/purge via tombstones.
"""
import copy,hashlib,json,os,re
from datetime import datetime,timedelta,timezone
from .catalog import now,uid
from .model import require,identifier,AssetError

OPS={'asset':{'detach_asset','deprecate_asset','restore_asset','purge_asset','clean_runtime'},
     'set':{'deprecate_set','restore_set','dissolve_set','deprecate_set_members','purge_set','purge_set_members'},
     'source':{'delete_source'}}
PURGE_CONFIRMATION = '永久删除'
PHYSICAL={'purge_asset','purge_set','purge_set_members','delete_source','clean_runtime'}

def asset_status(a):
    return a.get('lifecycle_status', 'deprecated' if a['versions'] and all(v['art_status']=='deprecated' for v in a['versions']) else 'active')

def records(c,conn):
    data={}
    for kind in ('asset','set','source','prompt','preview'):
        data[kind]={}
        for key,body in conn.execute('SELECT id,body FROM metadata WHERE kind=?',(kind,)):
            value=json.loads(body)
            # Only reference/file facts are needed here, not frozen production specs.
            # Hash the complete record so edits to omitted facts still invalidate consent.
            fingerprint=hashlib.sha256(body.encode()).hexdigest()
            if kind=='asset':
                value={k:v for k,v in value.items() if k in ('asset_id','name_zh','set_id','lifecycle_status','versions')}
                value['versions']=[{k:v for k,v in version.items() if k in ('version','art_status','source_id','files','runtime','runtime_build_history','master_asset')} for version in value['versions']]
            elif kind=='source':
                value={k:v for k,v in value.items() if k in ('source_id','original_name','file','sha256','set_id','frozen_spec','status')}
                value['frozen_spec']={'asset_ids':value.get('frozen_spec',{}).get('asset_ids',[])}
            elif kind=='prompt':
                value={'set_id':value.get('set_id'),'options':{'master_reference':value.get('options',{}).get('master_reference')}}
            elif kind=='preview':
                value={k:v for k,v in value.items() if k in ('source_id','lifecycle_status','expires_at','result','items')}
                value['items']=[dict(asset_id=item['asset_id'],plan={'source_id':item['plan']['source_id']},preview_files=item['preview_files']) for item in value['items']]
            value['_lifecycle_record_sha256']=fingerprint
            data[kind][key]=value
    return data

def members(group,data):
    # Static explicit order; scene slots are derived from membership, never just an old prefix.
    if group.get('kind') in ('static_collection','effect_collection'):return list(group['asset_ids'])
    return [a['asset_id'] for a in data['asset'].values() if a.get('set_id')==group['set_id']]

def digest(data,manifest):
    return hashlib.sha256(json.dumps([data,manifest],sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def asset_files(asset,runtime_only=False,deprecated_only=False):
    files=[]
    for v in asset['versions']:
        if deprecated_only and v['art_status']!='deprecated':continue
        if not runtime_only:files+=v['files']
        builds=list(v.get('runtime_build_history',[]))+([v['runtime']] if v.get('runtime') else [])
        for build in builds:files+=build['files']
    return {f['file']:f for f in files}

def safe_file(c,record):
    name=record['file'];parts=name.split('/')
    require((len(parts)>=3 and parts[0] in ('source','components','master') and parts[1]=='files') or (len(parts)>=4 and parts[0]=='runtime'),'Only Registry-managed image files may be deleted')
    require(name.lower().endswith(('.png','.webp','.jpg','.jpeg')),'Only managed image files may be deleted')
    p=c.path(name)
    if p.exists():
        require(p.is_file() and p.stat().st_nlink==1,'Unsafe linked/non-file delete target')
        require(hashlib.sha256(p.read_bytes()).hexdigest()==record['sha256'],'Managed file changed; deletion rejected')
    return p

def preview_files(preview):
    files={}
    for item in preview['items']:
        for f in item['preview_files']:
            files[f['file']]=f
            if f.get('runtime_preview'):
                r=f['runtime_preview'];files[r['file']]=r
    return files

def preview_retirement_reason(preview,data):
    if preview.get('lifecycle_status')=='retired':return 'already_retired'
    if preview.get('result'):return 'confirmed_history'
    if any(i['asset_id'] not in data['asset'] for i in preview['items']):return 'target_deleted'
    try:
        if datetime.fromisoformat(preview['expires_at'])<=datetime.now(timezone.utc):return 'expired'
    except (KeyError,TypeError,ValueError):
        return 'invalid_expiry'  # Such a preview cannot be confirmed; retain its audit body.
    return 'pending_cancelled'

def inspect(c,kind,key,operation,conn):
    require(kind in OPS and operation in OPS[kind],'Invalid lifecycle operation')
    if kind=='source':require(isinstance(key,str) and re.fullmatch(r'[a-z0-9][a-z0-9_.-]{0,119}',key),'Invalid Source ID')
    else:identifier(key)
    data=records(c,conn);require(key in data[kind],'Unknown lifecycle target')
    target=data[kind][key];ids=[key] if kind=='asset' else members(target,data) if kind=='set' else []
    require(all(a in data['asset'] for a in ids),'Invalid Asset Set member reference')
    affected=[data['asset'][a] for a in ids];manifest=json.loads(c.path('manifest.json').read_text())
    files={};blockers=[];force_blockers=[];referencing_assets=[];retired_previews=[];active_preview_ids=[]
    def block(a,text,external=False):
        value=dict(asset_id=a,reason=text);blockers.append(value)
        if external:force_blockers.append(value)
    if operation.startswith('purge'):
        for aid in ids:
            a=data['asset'][aid]
            for g in data['set'].values():
                if aid in members(g,data) and not (kind=='set' and g['set_id']==key):block(aid,'仍属于素材组：'+g['name_zh'],True)
            for other in data['asset'].values():
                if other['asset_id'] not in ids and any(v.get('master_asset')==aid for v in other['versions']):block(aid,'被素材视觉基准引用：'+other['name_zh'],True)
            for source in data['source'].values():
                if aid in source.get('frozen_spec',{}).get('asset_ids',[]):block(aid,'存在历史 Source Snapshot')
            for p in data['prompt'].values():
                if p.get('options',{}).get('master_reference')==aid:block(aid,'被提示词视觉基准引用：'+p['prompt_id'],True)
                if p.get('asset_id')==aid or aid in p.get('frozen_spec',{}).get('asset_ids',[]):block(aid,'存在历史 Prompt Snapshot')
            if any(v['art_status']=='approved' for v in a['versions']):block(aid,'存在 Approved 版本')
            if a['versions']:block(aid,'存在素材历史版本')
            if asset_files(a,True):block(aid,'存在 Runtime / 构建历史')
            if aid in manifest['assets']:block(aid,'已发布到 Manifest')
            for v in a['versions']:files.update({f['file']:f for f in v['files']})
            files.update(asset_files(a,True))
        if kind=='set':
            if any(s.get('set_id')==key for s in data['source'].values()):block(key,'存在历史 Source 组引用')
            if any(p.get('set_id')==key for p in data['prompt'].values()):block(key,'存在历史 Prompt 组引用')
        # Container-only purge preserves members and all image files.
        if operation=='purge_set':files={}
        # Shared frames belong to surviving owners; never physically delete them.
        shared=set()
        for aid,a in data['asset'].items():
            if aid not in ids:shared.update(asset_files(a))
        for p in data['preview'].values():
            for item in p['items']:
                if item['asset_id'] not in ids:
                    for f in item['preview_files']:
                        shared.add(f['file'])
                        if f.get('runtime_preview'):shared.add(f['runtime_preview']['file'])
        shared.update(s["file"] for s in data["source"].values())
        files={path:f for path,f in files.items() if path not in shared}
    elif operation=='delete_source':
        for a in data['asset'].values():
            versions=[v for v in a['versions'] if v['source_id']==key or any(f.get('source_id')==key for f in v['files'])]
            file_reference=target['file'] in asset_files(a)
            if versions or file_reference:
                referencing_assets.append(dict(asset_id=a['asset_id'],name_zh=a['name_zh'],lifecycle_status=asset_status(a),set_id=a.get('set_id'),version_numbers=[v['version'] for v in versions],approved_version_numbers=[v['version'] for v in versions if v['art_status']=='approved']))
            if versions:block(a['asset_id'],'原图仍被素材历史版本引用；废弃不会解除历史引用',True)
        for pid,p in data['preview'].items():
            if p.get('source_id')==key or any(i['plan']['source_id']==key for i in p['items']):
                reason=preview_retirement_reason(p,data)
                retired_previews.append(dict(preview_id=pid,reason=reason))
                if reason=='pending_cancelled':active_preview_ids.append(pid)
        for a in data['asset'].values():
            if target['file'] in asset_files(a):block(a['asset_id'],'Source文件仍被其他受控资产引用',True)
        for sid,s in data['source'].items():
            if sid!=key and s['file']==target['file']:block(sid,'Source文件被另一Source记录引用',True)
        # Retire only previews linked to this explicitly deleted Source. Keep audit bodies.
        # Shared files remain owned by surviving assets, Sources, previews or Manifest.
        candidates={path:f for p in retired_previews for path,f in preview_files(data['preview'][p['preview_id']]).items()}
        shared=set()
        for a in data['asset'].values():shared.update(asset_files(a))
        shared.update(s['file'] for s in data['source'].values())
        retiring={p['preview_id'] for p in retired_previews}
        for pid,p in data['preview'].items():
            if pid not in retiring:shared.update(preview_files(p))
        for value in manifest['assets'].values():shared.update(f['file'] for f in value['files'])
        if target['file'] in {f['file'] for value in manifest['assets'].values() for f in value['files']}:block(key,'Manifest仍引用该原图文件',True)
        files={path:f for path,f in candidates.items() if path not in shared and safe_file(c,f).exists()}
        files[target['file']]=target
    elif operation=='clean_runtime':
        files=asset_files(target,True,True)
        if key in manifest['assets']:block(key,'Manifest仍引用该素材，请先废弃',True)
        shared=set()
        for a in data['asset'].values():
            if a['asset_id']!=key:shared.update(asset_files(a))
            else:
                for v in a['versions']:
                    if v['art_status']!='deprecated':
                        for b in v.get('runtime_build_history',[])+([v['runtime']] if v.get('runtime') else []):shared.update(f['file'] for f in b['files'])
        files={p:f for p,f in files.items() if p not in shared}
    if operation in PHYSICAL:
        for f in files.values():safe_file(c,f)
    published=[a for a in ids if a in manifest['assets']]
    sources={v['source_id'] for a in affected for v in a['versions']}
    result=dict(kind=kind,key=key,operation=operation,name_zh=target.get('name_zh',target.get('original_name',key)),
                confirmation_phrase=PURGE_CONFIRMATION if operation.startswith('purge') else None,
                previous_status=asset_status(target) if kind=='asset' else target.get('status','active'),
                art_status=(target['versions'][-1]['art_status'] if target['versions'] else 'missing_source') if kind=='asset' else None,
                member_ids=ids,asset_count=len(ids),approved=sum(any(v['art_status']=='approved' for v in a['versions']) for a in affected),
                runtime=sum(bool(asset_files(a,True)) for a in affected),source_count=len(sources) if kind!='source' else 1,
                manifest_count=len(published),manifest_ids=published,asset_set_name=data['set'].get(target.get('set_id'),{}).get('name_zh'),
                blockers=blockers,force_blockers=force_blockers,referencing_assets=referencing_assets,reference_asset_count=len(referencing_assets),retired_preview_ids=[p['preview_id'] for p in retired_previews],retirable_previews=retired_previews,pending_preview_count=len(active_preview_ids),physical=operation in PHYSICAL,affected_files=list(files.values()),
                file_count=len(files),fingerprint=digest(data,manifest))
    return result,data

def prepare(c,kind,key,operation):
    with c.transaction() as conn:
        p,_=inspect(c,kind,key,operation,conn)
        p.update(confirmation_id=uid(),created_at=now(),expires_at=(datetime.now(timezone.utc)+timedelta(minutes=30)).isoformat(),result=None)
        c.put('lifecycle',p['confirmation_id'],p,conn,new=True)
    return p

def unpublish(c,ids):
    doc=json.loads(c.path('manifest.json').read_text());removed=[a for a in ids if a in doc['assets']]
    for aid in removed:doc['assets'].pop(aid)
    if removed:c.atomic('manifest.json',(json.dumps(doc,ensure_ascii=False,indent=2)+'\n').encode())
    return removed

def audit(c,conn,operation,kind,key,previous,new,files=None,runtime=None,manifest=None,actor='authenticated_operator'):
    value=dict(audit_id=uid(),operation=operation,kind=kind,key=key,timestamp=now(),previous_status=previous,new_status=new,
               affected_files=files or [],affected_runtime=runtime or [],manifest_change=manifest or [],actor=actor)
    c.put('audit',value['audit_id'],value,conn,new=True);return value

def deprecate(c,aid,conn,actor='authenticated_operator'):
    a=c.get('asset',aid,conn);previous=asset_status(a)
    if previous=='deprecated':return a
    removed=unpublish(c,[aid]);a['lifecycle_status']='deprecated';a['current_approved_version']=None;a['updated_at']=now()
    for v in a['versions']:
        if v['art_status']!='deprecated':v.setdefault('review_history',[]).append(dict(from_status=v['art_status'],to_status='deprecated',source='asset_deprecate',at=now()))
        v['art_status']='deprecated'
    c.put('asset',aid,a,conn);audit(c,conn,'deprecate_asset','asset',aid,previous,'deprecated',runtime=list(asset_files(a,True)),manifest=removed,actor=actor);return a

def detach(c,aid,conn):
    a=c.get('asset',aid,conn);sid=a.get('set_id');require(sid,'Asset已是未分组素材')
    g=c.get('set',sid,conn)
    if g.get('kind') in ('static_collection','effect_collection'):g['asset_ids']=[id for id in g['asset_ids'] if id!=aid]
    if g.get('collection_id'):a['collection_id']=g['collection_id']
    a['set_id']=None;a['updated_at']=now();c.put('asset',aid,a,conn);c.put('set',sid,g,conn)
    return sid

def apply(c,confirmation_id,confirmed=False,force=False,force_confirmed=False,confirmation_text='',actor='authenticated_operator'):
    require(confirmed is True,'请查看影响摘要后明确确认操作');require(type(force) is bool and type(force_confirmed) is bool,'Invalid confirmation')
    staged=[];result=None
    try:
        with c.transaction() as conn:
            p=c.get('lifecycle',confirmation_id,conn);choices=dict(force=force,force_confirmed=force_confirmed,confirmation_text=confirmation_text)
            if p['result']:
                require(p['choices']==choices,'已确认操作不可改变参数');return p['result']
            require(datetime.now(timezone.utc)<datetime.fromisoformat(p['expires_at']),'确认已过期，请重新查看摘要')
            live,data=inspect(c,p['kind'],p['key'],p['operation'],conn)
            require(live['fingerprint']==p['fingerprint'],'素材或引用已变化，请重新查看影响摘要')
            require(not live['force_blockers'],'该素材仍被正式资产引用，请先废弃或解除引用：'+(';'.join(b['asset_id']+' '+b['reason'] for b in live['force_blockers'])))
            if live['operation'].startswith('purge'):
                require(confirmation_text==PURGE_CONFIRMATION,'请输入“永久删除”确认')
                if live['blockers']:require(force and force_confirmed is True,'存在历史/批准引用；强制永久删除需要二次确认')
                if force:require(force_confirmed is True,'强制永久删除需要二次确认')
            else:require(not live['blockers'],';'.join(b['reason'] for b in live['blockers']))
            key=live['key'];op=live['operation'];ids=live['member_ids'];previous=live['previous_status'];removed=[]
            if op=='deprecate_asset':deprecate(c,key,conn,actor);new='deprecated'
            elif op=='restore_asset':
                a=c.get('asset',key,conn);require(asset_status(a)=='deprecated','仅可恢复已废弃素材')
                a['lifecycle_status']='active';a['current_approved_version']=None;a['updated_at']=now()
                for v in a['versions']:
                    if v['art_status']=='deprecated':v['art_status']='needs_review' if v['files'] else 'draft';v.setdefault('review_history',[]).append(dict(from_status='deprecated',to_status=v['art_status'],source='asset_restore',at=now()))
                c.put('asset',key,a,conn);new='active'
            elif op=='detach_asset':detach(c,key,conn);new='unassigned'
            elif op in ('deprecate_set','restore_set','deprecate_set_members','dissolve_set'):
                g=c.get('set',key,conn)
                if op=='restore_set':require(g.get('status')=='deprecated','仅可恢复已废弃素材组');g['status']='active'
                elif op=='dissolve_set':
                    g['previous_member_ids']=ids
                    for aid in ids:
                        if c.get('asset',aid,conn).get('set_id')==key:detach(c,aid,conn)
                    g=c.get('set',key,conn);g.update(status='dissolved',asset_ids=[],previous_member_ids=ids)
                else:
                    require(g.get('status','active')!='dissolved','已拆组容器不可重新废弃或恢复')
                    g['status']='deprecated'
                    if op=='deprecate_set_members':
                        for aid in ids:deprecate(c,aid,conn,actor)
                g['updated_at']=now();c.put('set',key,g,conn);new=g['status']
            elif op in PHYSICAL:
                if op in ('purge_asset','purge_set_members'):removed=unpublish(c,ids)
                for f in live['affected_files']:
                    file=safe_file(c,f)
                    if file.exists():
                        relative='registry/.deletion/'+uid()+file.suffix;temporary=c.path(relative);temporary.parent.mkdir(parents=True,exist_ok=True)
                        os.replace(file,temporary);staged.append((file,temporary))
                if op=='clean_runtime':
                    a=c.get('asset',key,conn)
                    for v in a['versions']:
                        if v['art_status']=='deprecated':v['runtime']=None;v['runtime_build_history']=[];v['runtime_cleaned_at']=now()
                    c.put('asset',key,a,conn);new=previous
                else:
                    delete_ids=ids if op in ('purge_asset','purge_set_members') else []
                    if op=='purge_set':
                        for aid in ids:
                            if c.get('asset',aid,conn).get('set_id')==key:detach(c,aid,conn)
                    for aid in delete_ids:
                        c.put('deleted_asset',aid,dict(asset_id=aid,name_zh=data['asset'][aid]['name_zh'],deleted_at=now()),conn,new=True)
                        conn.execute("DELETE FROM metadata WHERE kind='asset' AND id=?",(aid,))
                    if live['kind']=='set':
                        c.put('deleted_set',key,dict(set_id=key,name_zh=live['name_zh'],deleted_at=now()),conn,new=True)
                        conn.execute("DELETE FROM metadata WHERE kind='set' AND id=?",(key,))
                    elif op=='delete_source':
                        for pid in live['retired_preview_ids']:
                            preview=c.get('preview',pid,conn)
                            preview.update(lifecycle_status='retired')
                            preview.setdefault('retired_at',now());preview.setdefault('retired_source_id',key);preview.setdefault('retirement_reason','source_deleted')
                            preview['removed_files']=sorted(set(preview.get('removed_files',[]))|{path for path in preview_files(preview) if path in {f['file'] for f in live['affected_files']}})
                            c.put('preview',pid,preview,conn)
                        conn.execute("DELETE FROM metadata WHERE kind='source' AND id=?",(key,))
                    new='purged'
            event=audit(c,conn,op,live['kind'],key,previous,new,files=[f['file'] for f in live['affected_files']],runtime=ids,manifest=removed or (live['manifest_ids'] if op in ('deprecate_asset','deprecate_set_members') else []),actor=actor)
            if op=='delete_source':
                event['retired_preview_ids']=live['retired_preview_ids'];c.put('audit',event['audit_id'],event,conn)
            result=dict(retired_preview_ids=live['retired_preview_ids'],ok=True,operation=op,key=key,new_status=new,audit_id=event['audit_id'],removed_manifest=event['manifest_change'],file_count=len(staged))
            p.update(result=result,choices=choices);c.put('lifecycle',confirmation_id,p,conn)
    except BaseException:
        for original,temp in reversed(staged):
            if temp.exists():require(not original.exists(),'Delete rollback target changed');os.replace(temp,original)
        raise
    pending=[]
    for _,temp in staged:
        try:temp.unlink()
        except OSError:pending.append(str(temp.relative_to(c.root)))
    if pending:
        result['cleanup_pending']=pending
        with c.transaction() as conn:
            p=c.get('lifecycle',confirmation_id,conn);p['result']=result;c.put('lifecycle',confirmation_id,p,conn)
    return result

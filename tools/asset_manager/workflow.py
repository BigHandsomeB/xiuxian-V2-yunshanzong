"""Preview -> one human confirmation -> existing review/build/select/publish lifecycle.
@depends Catalog/Pillow; @usedBy web; @see asset-pipeline.md
No Gameplay imports. Each failed item stays reviewable while healthy items complete.
"""
import copy,hashlib,io,json
from datetime import datetime,timedelta,timezone
from PIL import Image
from .catalog import now,uid
from .model import require,AssetError,REVIEW,INTERIOR_REVIEW,rectangle,grid,mapping
from .images import crop,png,profiled_runtime
from .selection import validate as validate_selection, intersect as selections_intersect, crop_region
from .specs import export_spec, default_export_policy
from .sheets import canonical_spec, cell_key, grid_options


def fingerprint(asset):
    return hashlib.sha256(json.dumps(asset,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def _runtime_bytes(image,spec,mode,ack=False):
    return profiled_runtime(image,spec,'png',ack,subject_region=mode in ('auto','manual'))


def _check(c,item):
    """Check actual crops and exact final-runtime previews. Never decides art quality."""
    template=c.templates[item['frozen_spec']['template_id']]
    policy='frozen' if item['master'] else default_export_policy(template,item['frozen_spec'])
    spec,origin=export_spec(template,item['frozen_spec'],policy)
    item['runtime_spec']=spec;item['export_origin']=origin
    issues=item.setdefault('issues',[]);files=item['preview_files']
    if not files:issues.append('没有有效切块，请调整裁切框。')
    for file in files:
        data=c.path(file['file']).read_bytes()
        require(hashlib.sha256(data).hexdigest()==file['sha256'],'Preview file checksum mismatch')
        with Image.open(io.BytesIO(data)) as im:
            image=im.convert('RGBA')
            if image.getchannel('A').getbbox() is None:
                issues.append(file['action']+'：空白切块。');continue
            if item['master']:continue
            try:
                try:output=_runtime_bytes(image,spec,item['plan']['mode'])
                except AssetError as exc:
                    if 'Non-integer resizing' not in str(exc):raise
                    output=_runtime_bytes(image,spec,item['plan']['mode'],True);item['non_integer_ack_required']=True
                with Image.open(io.BytesIO(output)) as runtime:
                    require(list(runtime.size)==spec['runtime_profile']['frame_size'],'Runtime target mismatch')
                    require(runtime.getchannel('A').getbbox() is not None,'Runtime为空白，请调整主体或规格。')
                path='components/files/'+uid()+'.png';c.atomic(path,output)
                file['runtime_preview']=dict(file=path,sha256=hashlib.sha256(output).hexdigest())
            except (AssetError,OSError) as exc:issues.append(file['action']+'：'+str(exc))
    item['valid']=not issues


def prepare(c,source_id=None,regions=None,mode='manual',options=None,counts=None,asset_id=None,targets=None,detection=None):
    """Persist a preview snapshot, not a version/approval. Default selection is all valid items."""
    require(bool(source_id)!=bool(targets),'Choose one source plan or existing versions')
    preview=dict(preview_id=uid(),created_at=now(),expires_at=(datetime.now(timezone.utc)+timedelta(hours=2)).isoformat(),items=[],result=None)
    with c.transaction() as conn:
        if targets:
            require(isinstance(targets,list) and 0<len(targets)<=128 and len({t['asset_id'] for t in targets})==len(targets),'Invalid preview targets')
            require(sum(f.get('width',0)*f.get('height',0) for t in targets for f in c.version(c.get('asset',t['asset_id'],conn),t['version'])['files'])<=16*1024*1024,'Batch preview area exceeds limit')
            for target in targets:
                a=c.get('asset',target['asset_id'],conn);v=c.version(a,target['version'])
                require(v['art_status']!='deprecated','Deprecated version cannot be quick-confirmed')
                source=c.get('source',v['source_id'],conn);spec=v.get('frozen_spec') or c.source_spec(source)
                require(not spec.get('legacy'),'Historical specifications require advanced review')
                item=dict(asset_id=a['asset_id'],name_zh=a['name_zh'],fingerprint=fingerprint(a),version=v['version'],master=a['state']=='master',frozen_spec=spec,plan=copy.deepcopy(v['plan']),preview_files=copy.deepcopy(v['files']),issues=[])
                try:
                    if not source.get("file_deleted_at"):c.source_image(source)
                    require(spec['template_id']==a['template_id'],'Version Template reference mismatch')
                    if item['master']:require(len(v['files'])==1 and v['files'][0]['action']=='master','Invalid Master Components')
                    else:mapping(spec['template_snapshot'],v['files'],v['plan']['counts'])
                    require(all(action in spec['frame_counts'] and n==spec['frame_counts'][action] for action,n in v['plan']['counts'].items()),'Version action counts differ from frozen specification')
                    if spec.get('asset_list'):require(a['asset_id'] in spec['asset_ids'] and len(v['files'])==1,'Version Asset reference mismatch')
                    _check(c,item)
                except (AssetError,OSError) as exc:item['issues'].append(str(exc));item['valid']=False
                preview['items'].append(item)
        else:
            source=c.get('source',source_id,conn);spec=c.source_spec(source)
            require(not spec.get('legacy') and spec.get('template_version') and spec.get('runtime_profile'),'完整冻结规格缺失，请使用高级导入补充规格。')
            if source.get('prompt_id'):
                prompt=c.get('prompt',source['prompt_id'],conn)
                require(prompt.get('frozen_spec')==spec,'Source / Prompt Snapshot mismatch')
            spec=canonical_spec(spec)
            image=c.source_image(source)
            require(mode in ('grid','manual','auto','independent'),'Unknown slice mode')
            if spec.get('asset_list') or spec.get('asset_ids') and regions:
                require(isinstance(regions,list) and len(regions)==len(spec['cell_mapping']),'映射必须覆盖全部冻结Cell（异常项可在预览中排除）。')
                require(len({cell_key(r) for r in regions})==len(regions) and {cell_key(r) for r in regions}=={cell_key(r) for r in spec['cell_mapping']},'Incomplete or duplicate Cell Mapping')
                ids=list(dict.fromkeys(r['asset_id'] for r in spec['cell_mapping']))
                pairs=[]
                for aid in ids:
                    rs=[r for r in regions if r['asset_id']==aid]
                    ns={a:max(r['frame'] for r in rs if r['action']==a) for a in dict.fromkeys(r['action'] for r in rs)}
                    pairs.append((c.get('asset',aid,conn),rs,ns))
            else:
                a=c.get('asset',asset_id,conn)
                plan=c.master_plan(source_id,regions[0]['rect'] if regions else None) if a['state']=='master' else c.plan(source_id,counts,mode,options,regions)
                pairs=[(a,plan['regions'],plan['counts'])]
            require(sum(r['rect'][2]*r['rect'][3] for _,rs,_ in pairs for r in rs if isinstance(r.get('rect'),list) and len(r['rect'])==4 and all(type(v)is int for v in r['rect']))<=16*1024*1024,'Total slice area exceeds limit')
            preview['source_id']=source_id;preview['source_sha256']=source['sha256']
            for a,rs,ns in pairs:
                require(a['template_id']==source['template_id'] and (not source['set_id'] or a['set_id']==source['set_id']),'Source / Asset mismatch')
                require(not a.get('family') or a['family']==spec['family'],'Source / Asset family mismatch')
                plan=dict(source_id=source_id,source_sha256=source['sha256'],counts=ns,mode=mode,regions=copy.deepcopy(rs),grid_spec=grid_options(spec,options))
                if detection:
                    require(detection.get('source_sha256')==source['sha256'],'Stale detection')
                    plan['detection']={k:detection.get(k) for k in ('algorithm','status','foreground_method','detected_count')}
                item=dict(asset_id=a['asset_id'],name_zh=a['name_zh'],fingerprint=fingerprint(a),version=None,master=a['state']=='master',frozen_spec=copy.deepcopy(spec),plan=plan,preview_files=[],issues=[])
                try:
                    if not item['master']:c.validate_source_mapping(source,rs,ns)
                    cells=grid(image.width,image.height,plan['grid_spec']) if mode=='grid' else None
                    for r in rs:
                        validate_selection(r,image.width,image.height)
                        require(not r.get('polygon') or mode in ('manual','auto'),'多边形只能用于人工或自动定位裁切')
                        if cells is not None:require(r['rect'] in cells,'Region is not a frozen grid cell')
                        if spec.get('asset_list') or spec.get('frame_asset_list'):
                            require(not any(selections_intersect(r,other,image.width,image.height) for other in regions if cell_key(other)!=cell_key(r)),'裁切框与邻近素材重叠，请调整。')
                        part=crop_region(image,r);data=png(part);path='components/files/'+uid()+'.png';c.atomic(path,data)
                        item['preview_files'].append(dict(file=path,sha256=hashlib.sha256(data).hexdigest(),action=r['action'],frame=r['frame']))
                    _check(c,item)
                except (AssetError,OSError) as exc:item['issues'].append(str(exc));item['valid']=False
                preview['items'].append(item)
        c.put('preview',preview['preview_id'],preview,conn,new=True)
    return preview


def _invalid_version(c,item,conn,preview_id):
    """Keep a failed import diagnostic reviewable without inventing valid Components."""
    a=c.get('asset',item['asset_id'],conn);source=c.get('source',item['plan']['source_id'],conn)
    v=dict(version=len(a['versions'])+1,source_id=source['source_id'],prompt_id=source.get('prompt_id'),frozen_spec=item['frozen_spec'],source_native_size=[source['width'],source['height']],art_status='needs_review',files=[],plan=item['plan'],review=dict(preview_id=preview_id,issues=item['issues']),runtime=None,created_at=now(),review_history=[dict(from_status='draft',to_status='needs_review',source='quick_confirm',at=now())])
    a['versions'].append(v);c.put('asset',a['asset_id'],a,conn);return v


def _validate_runtime(c,value,spec):
    require(value['runtime'] and value['runtime']['files'],'Missing Runtime output')
    for f in value['runtime']['files']:
        require(f['file'].startswith('runtime/') and hashlib.sha256(c.path(f['file']).read_bytes()).hexdigest()==f['sha256'],'Runtime validation failed')
        with Image.open(c.path(f['file'])) as im:require(list(im.size)==spec['runtime_profile']['frame_size'],'Runtime dimensions failed validation')


def confirm(c,preview_id,confirmed=False,excluded=None,excluded_actions=None,actor='authenticated_operator'):
    require(confirmed is True,'必须查看切块预览并明确点击确认。')
    excluded=excluded or [];excluded_actions=excluded_actions or {}
    require(isinstance(excluded,list) and len(excluded)==len(set(excluded)) and isinstance(excluded_actions,dict),'Invalid exclusions')
    choices=dict(excluded=sorted(excluded),excluded_actions=excluded_actions)
    with c.transaction() as conn:
        preview=c.get('preview',preview_id,conn)
        require(preview.get('lifecycle_status')!='retired','原图已删除，此预览仅保留为历史记录，不能再次确认。')
        ids={i['asset_id'] for i in preview['items']}
        require(set(excluded)<=ids and set(excluded_actions)<=ids,'Unknown excluded Asset')
        for item in preview['items']:
            require(all(action in item['plan']['counts'] for action in excluded_actions.get(item['asset_id'],[])),'Unknown excluded action')
        if preview['result']:
            require(preview['choices']==choices,'This preview was already confirmed with different choices')
            result=preview['result']
        else:
            require(datetime.now(timezone.utc)<datetime.fromisoformat(preview['expires_at']),'预览已过期，请重新预览。')
            for item in preview['items']:
                require(item['master'] or not item['valid'] or ('export_origin' in item and 'runtime_spec' in item),'导出规格已升级，请刷新并重新预览。')
                require(fingerprint(c.get('asset',item['asset_id'],conn))==item['fingerprint'],'素材已变化，请刷新并重新预览。')
            if preview.get('source_id'):
                source=c.get('source',preview['source_id'],conn);require(source['sha256']==preview['source_sha256'],'Source changed after preview');c.source_image(source)
            result=dict(preview_id=preview_id,confirmed_at=now(),approved_by=actor,assets=[],manifest_updated=False)
            # Master must be selected before dependent scene states, but only if actually previewed.
            for item in sorted(preview['items'],key=lambda i:not i['master']):
                aid=item['asset_id'];skip=aid in excluded or bool(excluded_actions.get(aid));issues=list(item['issues']);v=None
                if item['version'] is None:
                    try:v=c._import_version(aid,item['plan'],item['master'],conn)
                    except (AssetError,OSError) as exc:
                        item['issues'].append(str(exc));v=_invalid_version(c,item,conn,preview_id);issues=list(item['issues'])
                else:v=c.version(c.get('asset',aid,conn),item['version'])
                history_start=len(v.get('review_history',[]))
                if v['art_status']=='draft':v=c._review(aid,v['version'],'needs_review',None,conn)
                entry=dict(asset_id=aid,name_zh=item['name_zh'],version=v['version'],status='needs_review',issues=issues,excluded=skip,master=item['master'])
                if not skip and item['valid'] and not issues:
                    conn.execute('SAVEPOINT quick_item')
                    try:
                        source=c.get('source',v['source_id'],conn)
                        if not source.get('file_deleted_at'):c.source_image(source)
                        for f in item['preview_files']:
                            require(hashlib.sha256(c.path(f['file']).read_bytes()).hexdigest()==f['sha256'],'Preview changed after confirmation')
                        checks=REVIEW+(INTERIOR_REVIEW if item['frozen_spec']['template_snapshot']['master_required'] and not item['master'] else [])
                        if v['art_status']=='needs_review':c._review(aid,v['version'],'approved',dict.fromkeys(checks,True),conn)
                        if not item['master']:
                            _,origin=export_spec(c.templates[item['frozen_spec']['template_id']],item['frozen_spec'],item['export_origin']['policy'])
                            require(origin==item['export_origin'],'Runtime export profile changed; refresh previews before confirmation')
                            c._build(aid,v['version'],None,None,'png',bool(item.get('non_integer_ack_required')),conn,item['export_origin']['policy'])
                            _validate_runtime(c,c.version(c.get('asset',aid,conn),v['version']),item['runtime_spec'])
                        c._select(aid,v['version'],conn);entry['status']='approved';entry['runtime_validation']='NOT_REQUIRED_MASTER' if item['master'] else 'PASS'
                    except (AssetError,OSError) as exc:
                        conn.execute('ROLLBACK TO quick_item');entry['issues'].append(str(exc))
                    finally:conn.execute('RELEASE quick_item')
                a=c.get('asset',aid,conn);value=c.version(a,v['version'])
                audit=dict(preview_id=preview_id,approval_source='quick_confirm_preview',approved_by=actor,confirmed_at=result['confirmed_at'],prompt_id=value['prompt_id'],source_id=value['source_id'],slice_mapping=value['plan']['regions'],excluded=skip,excluded_actions=excluded_actions.get(aid,[]),issues=entry['issues'],runtime_result='built' if entry['status']=='approved' and not item['master'] else 'not_built',runtime_validation=entry.get('runtime_validation','NOT_BUILT'))
                for transition in value.get('review_history',[])[history_start:]:transition.update(source='quick_confirm_preview',preview_id=preview_id,approved_by=actor)
                value.setdefault('quick_confirm_history',[]).append(audit)
                if entry['status']=='approved':value['approved_by']=actor;value['review'].update(audit)
                entry['art_status']=value['art_status']
                c.put('asset',aid,a,conn);result['assets'].append(entry)
            if preview.get('source_id'):
                source=c.get('source',preview['source_id'],conn)
                source.setdefault('source_region_mappings',[]).append(dict(import_id=uid(),preview_id=preview_id,source_sha256=source['sha256'],mode=preview['items'][0]['plan']['mode'],regions=[r for item in preview['items'] for r in item['plan']['regions']],confirmed_at=result['confirmed_at'],expected_layout=dict(rows=preview['items'][0]['frozen_spec']['row_count'],columns=preview['items'][0]['frozen_spec']['column_count'])))
                c.put('source',source['source_id'],source,conn)
            preview['result']=result;preview['choices']=choices;c.put('preview',preview_id,preview,conn)
    # Publish after the metadata commit; failed publication is safely retryable, no duplicate import.
    if not result['manifest_updated']:
        try:
            manifest=c.publish();result['manifest_updated']=True;result['manifest_asset_ids']=list(manifest['assets']);result.pop('manifest_error',None)
        except (AssetError,OSError) as exc:result['manifest_error']=str(exc)
        with c.transaction() as conn:
            preview=c.get('preview',preview_id,conn);preview['result']=result;c.put('preview',preview_id,preview,conn)
    return result

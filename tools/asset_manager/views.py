"""Read-only list projections and lossless on-demand asset provenance.
No cache or alternate metadata owner; historical records remain in Catalog.
"""
from .specs import export_spec, default_export_policy

def asset_summary(asset):
    value={k:v for k,v in asset.items() if k not in ('versions','size_provenance','runtime_export_spec','runtime_export_origin')}
    value['versions']=[{k:v for k,v in version.items() if k in ('version','art_status','created_at','source_id','prompt_id','files')} for version in asset['versions']]
    value['summary_only']=True
    return value

def source_summary(source):
    return {**{k:v for k,v in source.items() if k in ('source_id','original_name','template_id','set_id','prompt_id','width','height','created_at','file_deleted_at')},'summary_only':True}

def prompt_summary(prompt):
    return {k:v for k,v in prompt.items() if k in ('prompt_id','template_id','asset_id','set_id','created_at','template_version','options')}

def asset_detail(catalog,asset):
    if 'art_status' not in asset:
        from .lifecycle import asset_status
        status=asset_status(asset);asset['lifecycle_status']=status
        latest=asset['versions'][-1] if asset['versions'] else None
        asset['art_status']='deprecated' if status=='deprecated' else latest['art_status'] if latest else 'missing_source'
        approved=catalog.version(asset,asset['current_approved_version']) if asset['current_approved_version'] else None
        asset['runtime_ready']=bool(approved and approved['runtime'] and all(catalog.path(f['file']).is_file() for f in approved['runtime']['files']))
    if asset['versions']:
        v=asset['versions'][-1];source=catalog.get('source',v['source_id'])
        asset['size_provenance']=dict(spec=v.get('frozen_spec') or source.get('frozen_spec'),source_native_size=[source['width'],source['height']],master_size=[v['files'][0]['width'],v['files'][0]['height']] if asset['state']=='master' and v['files'] else None,prompt_id=v['prompt_id'],current_runtime_export=catalog.templates[asset['template_id']].get('runtime_export_policy')=='current_item_profile',runtime=v.get('runtime'))
    else:
        asset['size_provenance']=dict(spec=catalog.specification(asset['template_id'],{'family':asset.get('family') or 'default'},asset_id=asset['asset_id']),source_native_size=None,prompt_id=None)
    frozen=asset['size_provenance']['spec'];template=catalog.templates[asset['template_id']]
    policy='frozen' if asset['state']=='master' else default_export_policy(template,frozen)
    if frozen and not frozen.get('legacy'):
        asset['runtime_export_spec'],asset['runtime_export_origin']=export_spec(template,frozen,policy)
    return asset

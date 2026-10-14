"""Source organization authority and read-only adapter for historical frozen specifications.
Sheet is a container, never a gameplay type or Runtime package. No image recognition.
"""
import copy, math
from .model import require, integer, identifier

CONTAINERS = ('single_image', 'sheet', 'image_set')
SEMANTICS = ('independent_assets', 'action_frames', 'state_sequence', 'scene_states',
             'environment_variants', 'effect_frames', 'ui_states', 'tiles', 'nine_slice')
FRAME_SEMANTICS = ('action_frames', 'effect_frames')
NINE = ('top_left','top','top_right','left','center','right','bottom_left','bottom','bottom_right')
LEGACY = {'static_asset_sheet':('sheet','independent_assets'), 'static_sheet':('sheet','independent_assets'),
          'sprite_sheet':('sheet','action_frames'), 'effect_sprite_sheet':('sheet','effect_frames'),
          'scene_state_sheet':('sheet','scene_states'), 'scene_sheet':('sheet','scene_states'),
          'ui_state_sheet':('sheet','ui_states')}


def scope(value):
    value={'single':'single_asset','set':'asset_set'}.get(value,value)
    require(value in ('single_asset','asset_set'), 'Invalid generation scope')
    return value


def grid_shape(count, limit=5):
    integer(count,1,256)
    require(limit is None or count<=limit*limit,'一张素材表最多5行、5列（25个素材），请拆分素材组或选择多张独立图片')
    if count<=3:return 1,count
    shapes=[(r,math.ceil(count/r)) for r in range(2,math.ceil(math.sqrt(count))+1)]
    if limit is not None:shapes=[(r,c) for r,c in shapes if r<=limit and c<=limit]
    return min(shapes,key=lambda rc:(rc[0]*rc[1]-count,abs(rc[0]-rc[1])))


def source_rules(template):
    """Old snapshots infer only from their own recorded fields, never today's Template."""
    mode=template.get('output_mode','icon')
    semantics=('effect_frames' if template.get('category')=='effect' else 'action_frames') if mode=='sprite_sheet' else 'independent_assets' if mode=='icon' else 'scene_states'
    allowed=['sheet','image_set'] if mode=='sprite_sheet' else list(CONTAINERS)
    default='single_image' if mode=='icon' or template.get('category')=='environment' else 'sheet'
    return dict(default_source_container=template.get('default_source_container',default),
                allowed_source_containers=template.get('allowed_source_containers',allowed),
                default_sheet_semantics=template.get('default_sheet_semantics',semantics),
                allowed_sheet_semantics=template.get('allowed_sheet_semantics',[semantics]))


def validate_rules(template):
    r=source_rules(template)
    require(isinstance(r['allowed_source_containers'],list) and r['allowed_source_containers'] and
            len(set(r['allowed_source_containers']))==len(r['allowed_source_containers']) and
            set(r['allowed_source_containers'])<=set(CONTAINERS) and r['default_source_container'] in r['allowed_source_containers'], 'Invalid source container policy')
    require(isinstance(r['allowed_sheet_semantics'],list) and r['allowed_sheet_semantics'] and
            len(set(r['allowed_sheet_semantics']))==len(r['allowed_sheet_semantics']) and
            set(r['allowed_sheet_semantics'])<=set(SEMANTICS) and r['default_sheet_semantics'] in r['allowed_sheet_semantics'], 'Invalid sheet semantics policy')
    return r


def choices(template, options=None, generation_scope=None):
    o=options or {};rules=validate_rules(template)
    selected_scope=scope(generation_scope or o.get('generation_scope') or template.get('default_generation_scope','single_asset'))
    legacy=o.get('generation_mode');container=o.get('source_container')
    require(legacy is None or legacy in ('independent','sheet',*LEGACY),'Invalid generation mode')
    if container is None and legacy:
        container='sheet' if legacy=='sheet' or legacy in LEGACY else ('image_set' if selected_scope=='asset_set' else 'single_image')
        if container=='single_image' and container not in rules['allowed_source_containers']:container='image_set'
    if container is None:
        container=rules['default_source_container']
        if rules['default_sheet_semantics'] in ('independent_assets','tiles'):
            container='sheet' if selected_scope=='asset_set' else 'single_image'
    require(container in rules['allowed_source_containers'],'当前模板不支持所选生成方式')
    semantics=o.get('sheet_semantics') or (LEGACY[legacy][1] if legacy in LEGACY else rules['default_sheet_semantics'])
    require(semantics in rules['allowed_sheet_semantics'],'当前模板不支持所选素材表内容')
    return selected_scope,container,semantics if container=='sheet' else None


def _layout(spec, cells, rows, columns):
    g=spec['grid_spec']
    return dict(rows=rows,columns=columns,cell_width=g['frame_width'],cell_height=g['frame_height'],
                horizontal_gap=g.get('horizontal_gap',0),vertical_gap=g.get('vertical_gap',0),
                outer_margin={k:g.get('margin_'+k,0) for k in ('top','bottom','left','right')},
                safe_padding=spec['inner_safe_padding'],cell_aspect_ratio=[g['frame_width'],g['frame_height']],
                cell_mapping=copy.deepcopy(cells),ordering='row_major')


def freeze_container(spec, options=None, items=None, set_id=None, asset_id=None):
    """Freeze the common layout once; mapping semantics change, grid geometry does not."""
    s=copy.deepcopy(spec);t=s['template_snapshot'];o=options or {}
    if s['output_mode']=='master':sc,container,semantics='single_asset','single_image',None
    else:sc,container,semantics=choices(t,o)
    s.update(schema_version=2,generation_scope=sc,source_container=container,sheet_semantics=semantics,
             generation_mode='sheet' if container=='sheet' else 'independent')
    inferred_semantics=semantics or source_rules(t)['default_sheet_semantics']
    counts=s['frame_counts'];actions=list(s.get('row_order',counts))
    if inferred_semantics not in FRAME_SEMANTICS:require(all(n==1 for n in counts.values()),'状态 / 变体 / 图块每项只能是一张图片，不能当成动画帧')
    cells=[];rows,columns=len(actions),max(counts.values())
    if items is not None:
        require(items and len({i['asset_id'] for i in items})==len(items),'Invalid mapped asset list')
        ids=[identifier(i['asset_id']) for i in items]
        s.update(asset_ids=ids,asset_order=ids,asset_count=len(items),asset_set_id=set_id)
        if inferred_semantics=='effect_frames':
            require(container=='sheet','批量特效请使用素材表')
            s['frame_asset_list']=copy.deepcopy(items)
            rows=len(items)*len(actions)
            require(rows*columns<=256,'特效素材表最多256个切块，请拆分素材组')
            for i,item in enumerate(items):
                for j,a in enumerate(actions):
                    for f in range(1,counts[a]+1):
                        cells.append(dict(row=i*len(actions)+j,column=f-1,asset_id=item['asset_id'],name_zh=item['name_zh'],action=a,frame=f))
        # Keep asset_list for independent records only, never for a character's frame sequence.
        if inferred_semantics not in FRAME_SEMANTICS:
            s['asset_list']=copy.deepcopy(items)
            rows,columns=grid_shape(len(items),limit=5 if container=='sheet' else None)
            if inferred_semantics=='nine_slice':
                require(len(items)==9 and [i.get('action') for i in items]==list(NINE),'Nine slice requires its nine ordered parts')
                rows,columns=3,3
            for n,i in enumerate(items):
                a=i.get('action','icon')
                cells.append(dict(row=n//columns,column=n%columns,asset_id=i['asset_id'],name_zh=i['name_zh'],action=a,frame=1,**({'state':a} if inferred_semantics not in ('independent_assets','tiles') else {})))
    else:s.update(asset_count=1,asset_ids=[asset_id] if asset_id else [],asset_order=[asset_id] if asset_id else [],asset_set_id=set_id)
    if not cells:
        if inferred_semantics in FRAME_SEMANTICS:
            for row,a in enumerate(actions):
                for f in range(1,counts[a]+1):cells.append(dict(row=row,column=f-1,action=a,frame=f,**({'asset_id':asset_id} if asset_id else {})))
        else:
            rows,columns=grid_shape(sum(counts.values()),limit=5 if container=='sheet' else None)
            for n,a in enumerate(actions):cells.append(dict(row=n//columns,column=n%columns,action=a,frame=1,**({'asset_id':asset_id} if asset_id else {})))
    if inferred_semantics in FRAME_SEMANTICS and o.get('extra_columns') is not None:
        columns=integer(o['extra_columns'],columns,64)
    if container=='single_image':
        require(len(cells)==1,'单张图片仅能包含一个已选状态；多个动作或状态请选择素材表 / 多张独立图片')
        rows,columns=1,1
    # image_set records each intended image but upload must select one image/subset first.
    s.update(row_count=rows,column_count=columns,grid_rows=rows,grid_columns=columns,
             cell_mapping=cells,state_order=actions if inferred_semantics not in FRAME_SEMANTICS else [],
             action_count=len(actions) if inferred_semantics in FRAME_SEMANTICS else 0,
             frame_count=sum(counts.values()) if inferred_semantics in FRAME_SEMANTICS else 1)
    s['grid_spec'].update(rows=rows,columns=columns)
    s['layout_spec']=_layout(s,cells,rows,columns)
    width=columns*s['source_cell_size'][0]+(columns-1)*s['spacing']
    height=rows*s['source_cell_size'][1]+(rows-1)*s['spacing']
    if container=='sheet':require(width<=8192 and height<=8192 and width*height<=16*1024*1024,'Planned sheet exceeds upload limits')
    return s


def canonical_spec(spec):
    """Compatibility projection only: preserve historical counts, cells, geometry and text."""
    s=copy.deepcopy(spec)
    if s.get('legacy'):return s
    if 'source_container' in s:return s
    mode=s.get('output_mode');t=s.get('template_snapshot',{})
    alias=s.get('generation_mode') if s.get('generation_mode') in LEGACY else mode
    semantics=LEGACY.get(alias,('sheet',source_rules(t)['default_sheet_semantics']))[1]
    if s.get('asset_list'):
        semantics='independent_assets';container='sheet' if s.get('generation_mode')=='sheet' or s.get('generation_mode') in LEGACY else ('single_image' if s.get('asset_count')==1 else 'image_set')
    else:container='sheet' if alias in LEGACY else 'single_image' if mode in ('master','icon') or len(s.get('frame_counts',{}))==1 else 'image_set'
    s.update(generation_scope=scope(s.get('generation_scope','set' if s.get('asset_set_id') else 'single')),source_container=container,sheet_semantics=semantics if container=='sheet' else None)
    cells=copy.deepcopy(s.get('cell_mapping',[]))
    if not cells:
        cells=[dict(row=row,column=f-1,action=a,frame=f) for row,a in enumerate(s.get('row_order',s['frame_counts'])) for f in range(1,s['frame_counts'][a]+1)]
    s['cell_mapping']=cells;s['layout_spec']=_layout(s,cells,s['row_count'],s['column_count'])
    s.setdefault('asset_count',1);s.setdefault('asset_ids',[]);s.setdefault('asset_order',s['asset_ids'])
    s['compatibility_origin']=mode
    return s


def cell_key(cell):
    return cell.get('asset_id'),cell['action'],cell['frame']


def grid_options(spec, override=None):
    """Translate the one Layout Spec into the historical crop validator's arguments."""
    if override is not None:
        if 'cell_width' not in override:return copy.deepcopy(override)
        layout=override
    else:layout=canonical_spec(spec)['layout_spec']
    margins=layout.get('outer_margin',{})
    require(isinstance(margins,dict),'Invalid outer margins')
    return dict(rows=layout['rows'],columns=layout['columns'],frame_width=layout['cell_width'],frame_height=layout['cell_height'],
                horizontal_gap=layout.get('horizontal_gap',0),vertical_gap=layout.get('vertical_gap',0),
                **{'margin_'+side:margins.get(side,0) for side in ('top','bottom','left','right')})


def regions(spec, geometry=None):
    s=canonical_spec(spec);g=grid_options(s,geometry)
    require(g['rows']==s['row_count'] and g['columns']>=s['column_count'],'Grid must preserve frozen cell layout')
    return [dict(c,rect=[g.get('margin_left',0)+c['column']*(g['frame_width']+g.get('horizontal_gap',0)),
                        g.get('margin_top',0)+c['row']*(g['frame_height']+g.get('vertical_gap',0)),g['frame_width'],g['frame_height']]) for c in s['cell_mapping']]

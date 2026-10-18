"""Geometry-only sheet localization. Names/order are exclusively frozen metadata.
@depends Pillow/stdlib; @usedBy catalog; @see asset-pipeline.md
"""
import math, statistics
from PIL import Image
from .model import require, integer


def overlaps(a, b):
    return a[0] < b[0]+b[2] and b[0] < a[0]+a[2] and a[1] < b[1]+b[3] and b[1] < a[1]+a[3]


def _distance(a, b):
    return math.hypot(max(0,a[0]-b[2],b[0]-a[2]),max(0,a[1]-b[3],b[1]-a[3]))


def _components(mask, width, height, track_pixels=False):
    # Iterative flood fill on a bounded thumbnail, never the full source raster.
    found=[]
    for seed in range(len(mask)):
        if not mask[seed]: continue
        mask[seed]=0; stack=[seed]; count=0
        positions=[] if track_pixels else None
        x0=x1=seed%width; y0=y1=seed//width
        while stack:
            pos=stack.pop();
            if positions is not None:positions.append(pos)
            x=pos%width; y=pos//width; count+=1
            x0=min(x0,x);x1=max(x1,x);y0=min(y0,y);y1=max(y1,y)
            for ny in range(max(0,y-1),min(height,y+2)):
                for nx in range(max(0,x-1),min(width,x+2)):
                    nxt=ny*width+nx
                    if mask[nxt]: mask[nxt]=0;stack.append(nxt)
        found.append(dict(box=[x0,y0,x1+1,y1+1],area=count,**({'pixels':positions} if positions is not None else {})))
    return found


def _padded_boxes(boxes, width, height):
    output=[]
    for box in boxes:
        x0,y0,x1,y1=box; pad=max(2,math.ceil(min(x1-x0,y1-y0)*.04))
        left,top,right,bottom=max(0,x0-pad),max(0,y0-pad),min(width,x1+pad),min(height,y1+pad)
        for other in boxes:
            if other is box: continue
            a,b,c,d=other
            # Choose the axis with greater separation; clamp at the shared midpoint.
            dx=max(0,a-x1,x0-c);dy=max(0,b-y1,y0-d)
            if dx>=dy and dx>0:
                if a>=x1:right=min(right,(x1+a)//2)
                else:left=max(left,(c+x0+1)//2)
            elif dy>0:
                if b>=y1:bottom=min(bottom,(y1+b)//2)
                else:top=max(top,(d+y0+1)//2)
        output.append([left,top,right-left,bottom-top])
    return output


def _effect_frames(image, cells, pixels, mask, width, height, result):
    """Find low-coverage seams near frozen frame positions, not particle identities.

    Keep whole frame compartments: disconnected particles and thin touching halos
    belong to animation cells. Refuse absent frames and dense/ambiguous seams.
    """
    result.update(algorithm='layout_effect_frames_v1',
                  message='特效帧分界不明确或存在空帧，请人工调整。')
    rows=max(c['row'] for c in cells)+1;columns=max(c['column'] for c in cells)+1
    weights=[p[3] if visible else 0 for p,visible in zip(pixels,mask)] if result['foreground_method']=='alpha' else [255*v for v in mask]

    def seams(projection, count):
        boundaries=[0];size=len(projection);span=size/count
        if span<8:return None
        for i in range(1,count):
            center=size*i/count
            low=max(2,math.ceil(center-span*.18));high=min(size-3,math.floor(center+span*.18))
            if low>high:return None
            score=lambda k:sum(projection[k-1:k+2])
            cut=min(range(low,high+1),key=lambda k:(score(k),abs(k-center)))
            peak=max(projection[max(0,int(center-span*.65)):min(size,math.ceil(center+span*.65))])
            if not peak or score(cut)>peak*3*.18:return None
            boundaries.append(cut)
        return boundaries+[size]

    ys=seams([sum(weights[y*width:(y+1)*width]) for y in range(height)],rows)
    if ys is None:return result
    regions=[];areas=[]
    for row,(top,bottom) in enumerate(zip(ys,ys[1:])):
        xs=seams([sum(weights[y*width+x] for y in range(top,bottom)) for x in range(width)],columns)
        if xs is None:return result
        for c in sorted((c for c in cells if c['row']==row),key=lambda c:c['column']):
            left,right=xs[c['column']:c['column']+2]
            area=sum(mask[y*width+x] for y in range(top,bottom) for x in range(left,right))
            if area<max(4,math.ceil((right-left)*(bottom-top)*.003)):
                result['detected_count']=len(regions);return result
            areas.append(area)
            x0=left*image.width//width;y0=top*image.height//height
            x1=right*image.width//width;y1=bottom*image.height//height
            regions.append(dict(c,rect=[x0,y0,x1-x0,y1-y0]))
    if min(areas)<max(areas)*.003:return result
    result.update(status='NEEDS_REVIEW',detected_count=len(regions),regions=regions,
                  candidate_boxes=[r['rect'] for r in regions],
                  message='已按透明度低谷定位特效帧，保留帧内粒子与光晕。请核对名称、帧序及相邻帧边缘；分界处的微弱光晕可能被切开。')
    return result


def locate(image, spec, thumbnail_limit=512):
    """Return suggested regions only; does not mutate Source, Snapshot or image."""
    integer(thumbnail_limit,64,512)
    from .sheets import canonical_spec, cell_key
    spec=canonical_spec(spec);cells=spec.get('cell_mapping',[])
    expected=len(cells);integer(expected,1,256)
    require(len({cell_key(c) for c in cells})==expected,'Frozen cell mapping required')
    thumb=image.convert('RGBA');thumb.thumbnail((thumbnail_limit,thumbnail_limit),Image.Resampling.BOX)
    width,height=thumb.size;pixels=list(thumb.get_flattened_data()); alpha=thumb.getchannel('A')
    method='alpha' if alpha.getextrema()[0]<250 else 'edge_color'
    result=dict(status='FAILED',foreground_method=method,expected_count=expected,detected_count=0,
                thumbnail_size=[width,height],source_native_size=list(image.size),regions=[],candidate_boxes=[],
                algorithm='geometry_components_v1',message='自动定位置信度不足，请使用人工框选。')
    if method=='alpha': mask=bytearray(p[3]>16 for p in pixels)
    else:
        edge=[pixels[x] for x in range(0,width,max(1,width//64))]+[pixels[(height-1)*width+x] for x in range(0,width,max(1,width//64))]
        edge += [pixels[y*width] for y in range(0,height,max(1,height//64))]+[pixels[y*width+width-1] for y in range(0,height,max(1,height//64))]
        bg=[statistics.median(p[k] for p in edge) for k in range(3)]
        if sum(max(abs(p[k]-bg[k]) for k in range(3))>36 for p in edge)>len(edge)*.2:return result
        mask=bytearray(max(abs(p[k]-bg[k]) for k in range(3))>36 for p in pixels)
        result['background_estimate']=bg
    if sum(mask)>len(mask)*.75 or not any(mask):return result
    if spec.get('sheet_semantics')=='effect_frames':
        return _effect_frames(image,cells,pixels,mask,width,height,result)
    pieces=_components(mask,width,height)
    noise=max(2,math.ceil(width*height*.00004))
    pieces=sorted((p for p in pieces if p['area']>=noise),key=lambda p:(-p['area'],p['box'][1],p['box'][0]))
    result['component_count']=len(pieces)
    if len(pieces)<expected:
        result['detected_count']=len(pieces);return result
    mains=pieces[:expected];extras=pieces[expected:]
    if mains[-1]['area']<mains[0]['area']*.035:return result
    merged=0
    for part in extras:
        ranked=sorted((_distance(part['box'],p['box']),i) for i,p in enumerate(mains))
        distance,index=ranked[0]; main=mains[index]; a=main['box'];b=part['box']
        close=max(max(a[2]-a[0],a[3]-a[1])*.35,max(width,height)*.025)
        # A comparable seventh object is not a fragment. Equidistant debris is ambiguous.
        if part['area']>main['area']*.25 or distance>close or (len(ranked)>1 and ranked[1][0]-distance<2):
            result['detected_count']=len(pieces)-merged;return result
        main['box']=[min(a[0],b[0]),min(a[1],b[1]),max(a[2],b[2]),max(a[3],b[3])];main['area']+=part['area'];merged+=1
    result['merged_fragment_count']=merged;result['detected_count']=len(mains)
    ordered_cells=sorted(cells,key=lambda c:(c['row'],c['column']))
    rows=sorted({c['row'] for c in ordered_cells});counts=[sum(c['row']==r for c in ordered_cells) for r in rows]
    mains.sort(key=lambda p:((p['box'][1]+p['box'][3])/2,p['box'][0]))
    ordered=[];bands=[];offset=0;reasonable=True
    for count in counts:
        band=mains[offset:offset+count];offset+=count
        centers=[(p['box'][1]+p['box'][3])/2 for p in band];bands.append((min(centers),max(centers)))
        if max(centers)-min(centers)>max(p['box'][3]-p['box'][1] for p in band)*.65:reasonable=False
        ordered.extend(sorted(band,key=lambda p:(p['box'][0]+p['box'][2])/2))
    for a,b in zip(bands,bands[1:]):
        if b[0]-a[1]<max(8,height*.04):reasonable=False
    boxes=[[max(0,math.floor(p['box'][0]*image.width/width)),max(0,math.floor(p['box'][1]*image.height/height)),
            min(image.width,math.ceil(p['box'][2]*image.width/width)),min(image.height,math.ceil(p['box'][3]*image.height/height))] for p in ordered]
    rects=_padded_boxes(boxes,image.width,image.height)
    if any(overlaps(a,b) for i,a in enumerate(rects) for b in rects[i+1:]):return result
    result['candidate_boxes']=rects
    result['regions']=[dict(c,rect=r) for c,r in zip(ordered_cells,rects)]
    result['status']='PASS' if reasonable and method=='alpha' else 'NEEDS_REVIEW'
    result['message']='已定位主体，请核对中文名称与裁切边界后确认。' if result['status']=='PASS' else '已定位主体，但背景或排列需要人工核对；可拖动调整。'
    return result

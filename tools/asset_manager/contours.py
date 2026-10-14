"""Bounded, layout-guided contours. Suggestions only; no semantic image inference.
Complete connected pieces are grouped, never cut at the nominal cell boundary.
"""
import math,statistics
from PIL import Image
from .model import require
from .sheets import canonical_spec
from .geometry import _components,_distance
from .selection import intersect,validate


def locate_contours(image,spec,_minimum_bands=7,_padding=1,_edge_detail=False,_axis='y'):
    spec=canonical_spec(spec);cells=sorted(spec['cell_mapping'],key=lambda c:(c['row'],c['column']))
    rows=max(c['row'] for c in cells)+1;columns=max(c['column'] for c in cells)+1
    result=dict(status='FAILED',algorithm='layout_contours_v4',foreground_method='alpha',expected_count=len(cells),detected_count=0,regions=[],candidate_boxes=[],source_native_size=list(image.size),message='轮廓识别不确定，请人工调整；需要可区分的透明底及与提示词一致的排列。')
    thumb=image.convert('RGBA');thumb.thumbnail((512,512),Image.Resampling.BOX);w,h=thumb.size
    result['thumbnail_size']=[w,h]
    alpha=list(thumb.getchannel('A').get_flattened_data())
    opaque=min(alpha)>=250
    threshold=16;bands_count=7
    if opaque:
        pixels=list(thumb.get_flattened_data())
        edge=[pixels[x] for x in range(w)]+[pixels[(h-1)*w+x] for x in range(w)]+[pixels[y*w] for y in range(h)]+[pixels[y*w+w-1] for y in range(h)]
        background=[statistics.median(p[k] for p in edge) for k in range(3)]
        deviations=[max(abs(p[k]-background[k]) for k in range(3)) for p in edge]
        threshold=max(24,math.ceil(statistics.median(deviations)*3))
        if min(background)<180 or max(background)-min(background)>32 or threshold>64 or sum(v>threshold for v in deviations)>len(edge)*.2:
            result['message']='不透明背景过于复杂，无法可靠区分主体，请人工框选。';return result
        foreground=bytearray(max(abs(p[k]-background[k]) for k in range(3))>threshold for p in pixels);bands_count=24
        result.update(foreground_method='light_background',background_estimate=background,background_color_threshold=threshold)
    else:foreground=bytearray(v>threshold for v in alpha)
    if not opaque and sum(foreground)>w*h*.75:
        edge=[alpha[x] for x in range(w)]+[alpha[(h-1)*w+x] for x in range(w)]+[alpha[y*w] for y in range(h)]+[alpha[y*w+w-1] for y in range(h)]
        ordered=sorted(edge);baseline=statistics.median(edge);deviation=statistics.median(abs(v-baseline) for v in edge)
        threshold=math.ceil(max(16,ordered[int(len(edge)*.9)]+8,baseline+4*deviation))
        if threshold>96:
            result['message']='背景和主体透明度难以区分，请人工框选。';return result
        foreground=bytearray(v>threshold for v in alpha);bands_count=24
        result['foreground_method']='alpha_background';result['background_alpha_threshold']=threshold
    bands_count=max(bands_count,_minimum_bands)
    result['contour_band_count']=bands_count
    result['contour_padding']=_padding
    result['contour_edge_detail']=_edge_detail
    result['contour_axis']=_axis
    if not any(foreground) or sum(foreground)>w*h*.75:return result
    pieces=_components(foreground[:],w,h,track_pixels=True);noise=max(2,math.ceil(w*h*.00004));pieces=[p for p in pieces if p['area']>=noise]
    result['component_count']=len(pieces);groups={ (c['row'],c['column']):[] for c in cells }
    for p in pieces:
        x0,y0,x1,y1=p['box'];key=(min(rows-1,int((y0+y1)/2/h*rows)),min(columns-1,int((x0+x1)/2/w*columns)))
        if key not in groups:continue
        # Crossing half a neighbouring cell is too uncertain to assign as one object.
        if x1-x0>w/columns*1.5 or y1-y0>h/rows*1.5:return result
        groups[key].append(p)
    assigned={id(p) for ps in groups.values() for p in ps}
    for p in pieces:
        if id(p) in assigned:continue
        nearest=sorted(((_distance(p['box'],other['box']),key,other) for key,ps in groups.items() for other in ps),key=lambda v:(v[0],v[1]))
        if not nearest:return result
        distance,key,main=nearest[0];a=main['box']
        if p['area']>main['area']*.25 or distance>max(a[2]-a[0],a[3]-a[1])*.35:return result
        alternate=next((v for v in nearest if v[1]!=key),None)
        if alternate and alternate[0]-distance<2:return result
        groups[key].append(p)
    result['detected_count']=sum(bool(v) for v in groups.values())
    if result['detected_count']!=len(cells):return result
    for ps in groups.values():
        main=max(ps,key=lambda p:p['area']);a=main['box']
        for p in ps:
            b=p['box']
            separation=math.hypot(((b[0]+b[2])-(a[0]+a[2]))/2/max(1,a[2]-a[0]),((b[1]+b[3])-(a[1]+a[3]))/2/max(1,a[3]-a[1]))
            if p is not main and p['area']>main['area']*.25 and separation>.85:return result
    areas=[sum(p['area'] for p in ps) for ps in groups.values()]
    if min(areas)<max(areas)*.035:return result
    regions=[]
    for c in cells:
        ps=groups[c['row'],c['column']];points=[(i%w,i//w) for p in ps for i in p['pixels']]
        contour_width,contour_height=w,h
        if _axis=='x':
            points=[(y,x) for x,y in points]
            contour_width,contour_height=h,w
        y0=min(y for x,y in points);y1=max(y for x,y in points)+1
        # Start with7 or24 bands; overlapping envelopes retry up to32 bands (128 vertices).
        bands=[]
        if _edge_detail and bands_count==32 and y1-y0>32:
            # Eight single-pixel bands at each end resolve close sloping tips.
            # Sixteen central bands retain the existing 128-vertex ceiling.
            edges=sorted(set([y0+i for i in range(9)]+[y1-i for i in range(9)]+[y0+8+(y1-y0-16)*i//16 for i in range(17)]))
        else:
            edges=[y0+(y1-y0)*j//min(bands_count,y1-y0) for j in range(min(bands_count,y1-y0)+1)]
        for j,(top,bottom) in enumerate(zip(edges,edges[1:])):
            xs=[x for x,y in points if top<=y<bottom]
            if not xs:return result
            bands.append((max(0,min(xs)-_padding),max(0,top-_padding) if j==0 else top,min(contour_width,max(xs)+1+_padding),min(contour_height,bottom+_padding) if bottom==y1 else bottom))
        polygon=[]
        for left,top,right,bottom in bands:polygon.extend([[left,top],[left,bottom]])
        for left,top,right,bottom in reversed(bands):polygon.extend([[right,bottom],[right,top]])
        if _axis=='x':polygon=[[y,x] for x,y in polygon]
        polygon=[[max(0,min(image.width,math.floor(x*image.width/w))),max(0,min(image.height,math.floor(y*image.height/h)))] for x,y in polygon]
        # Consecutive equal/collinear corners are redundant; preserve concave turns.
        changed=True
        while changed and len(polygon)>3:
            changed=False
            for i,b in enumerate(polygon):
                a=polygon[i-1];d=polygon[(i+1)%len(polygon)]
                if b==a or (b[0]-a[0])*(d[1]-b[1])==(b[1]-a[1])*(d[0]-b[0]):polygon.pop(i);changed=True;break
        xs=[p[0] for p in polygon];ys=[p[1] for p in polygon];r=dict(c,polygon=polygon,rect=[min(xs),min(ys),max(xs)-min(xs),max(ys)-min(ys)])
        validate(r,image.width,image.height);regions.append(r)
    if any(intersect(a,b,image.width,image.height) for i,a in enumerate(regions) for b in regions[i+1:]):
        if bands_count<32:
            return locate_contours(image,spec,_minimum_bands=24 if bands_count<24 else 32,_padding=_padding,_axis=_axis)
        if _padding>.5:
            return locate_contours(image,spec,_minimum_bands=32,_padding=.5,_axis=_axis)
        # Extra margin can overlap even when the complete silhouettes are separate.
        # Retry the unpadded envelopes; retain the same pixel intersection guard.
        if _padding>0:
            return locate_contours(image,spec,_minimum_bands=32,_padding=0,_axis=_axis)
        if not _edge_detail:
            return locate_contours(image,spec,_minimum_bands=32,_padding=0,_edge_detail=True,_axis=_axis)
        if _axis=='y':
            # Concave silhouettes may interlock along one axis while remaining separate.
            # Retry vertical envelopes with unchanged pixel guards and vertex limits.
            return locate_contours(image,spec,_minimum_bands=32,_padding=0,_axis='x')
        result['message']='细化后的轮廓仍有交叠，无法可靠区分；请人工调整。';return result
    messages={
        'light_background':'已定位浅色背景上的轮廓建议；框内棋盘格或底色仍保留，请检查薄翼、光晕和碎片。',
        'alpha_background':'已区分低透明度背景并生成较细轮廓建议；框内原背景仍保留，请核对浅色边缘和碎片。',
        'alpha':'已按冻结排列归并碎片并生成轮廓建议。请核对名字、碎片归属与边缘；不代表已识别怪物身份。',
    }
    result.update(status='NEEDS_REVIEW',regions=regions,candidate_boxes=[r['rect'] for r in regions],merged_fragment_count=len(pieces)-len(cells),message=messages[result['foreground_method']])
    return result

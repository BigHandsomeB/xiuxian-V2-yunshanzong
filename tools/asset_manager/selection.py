"""Pixel-centre polygon selections; rectangular history stays compatible.
Polygons mask outside pixels to transparent without modifying Source or interpolating edges.
"""
import math
from PIL import Image,ImageDraw,ImageChops
from .model import rectangle,require,AssetError
from .geometry import overlaps

def validate(region,width,height):
    rect=rectangle(region['rect'],width,height);points=region.get('polygon')
    if points is None:return rect
    require(isinstance(points,list) and 3<=len(points)<=128,'多边形需要3—128个顶点')
    require(all(isinstance(p,list) and len(p)==2 and all(type(v)is int for v in p) and 0<=p[0]<=width and 0<=p[1]<=height for p in points),'多边形顶点必须是图内整数坐标')
    require(len({tuple(p) for p in points})==len(points),'多边形顶点不能重复')
    x0=min(p[0] for p in points);y0=min(p[1] for p in points);x1=max(p[0] for p in points);y1=max(p[1] for p in points)
    require(list(rect)==[x0,y0,x1-x0,y1-y0],'多边形外接框与顶点不一致')
    area=sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(points,points[1:]+points[:1]))
    require(area!=0,'多边形不能没有面积')
    def orient(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    def intersects(a,b,c,d):
        o1,o2,o3,o4=orient(a,b,c),orient(a,b,d),orient(c,d,a),orient(c,d,b)
        def on(a,b,p):return min(a[0],b[0])<=p[0]<=max(a[0],b[0]) and min(a[1],b[1])<=p[1]<=max(a[1],b[1])
        return o1*o2<0 and o3*o4<0 or o1==0 and on(a,b,c) or o2==0 and on(a,b,d) or o3==0 and on(c,d,a) or o4==0 and on(c,d,b)
    edges=list(zip(points,points[1:]+points[:1]))
    for i,(a,b) in enumerate(edges):
        for j,(c,d) in enumerate(edges):
            if j>i+1 and not(i==0 and j==len(edges)-1):require(not intersects(a,b,c,d),'多边形不能自交，请调整顶点顺序')
    return rect

def mask(region,rect):
    x,y,w,h=rect;result=Image.new('L',(w,h),0);points=region.get('polygon')
    if points is None:return Image.new('L',(w,h),255)
    draw=ImageDraw.Draw(result);edges=list(zip(points,points[1:]+points[:1]))
    for row in range(h):
        sy=y+row+.5;xs=sorted(a[0]+(sy-a[1])*(b[0]-a[0])/(b[1]-a[1]) for a,b in edges if min(a[1],b[1])<=sy<max(a[1],b[1]))
        for left,right in zip(xs[::2],xs[1::2]):
            start=max(0,math.ceil(left-.5)-x);end=min(w-1,math.ceil(right-.5)-1-x)
            if start<=end:draw.line((start,row,end,row),fill=255)
    return result

def intersect(a,b,width,height):
    ra=rectangle(a['rect'],width,height)
    try:rb=rectangle(b['rect'],width,height)
    except AssetError:return False # Invalid neighbours get their own per-item diagnostic.
    if not overlaps(ra,rb):return False
    validate(a,width,height)
    try:validate(b,width,height)
    except AssetError:return False
    if not a.get('polygon') and not b.get('polygon'):return True
    x=max(ra[0],rb[0]);y=max(ra[1],rb[1]);right=min(ra[0]+ra[2],rb[0]+rb[2]);bottom=min(ra[1]+ra[3],rb[1]+rb[3]);rect=[x,y,right-x,bottom-y]
    return ImageChops.multiply(mask(a,rect),mask(b,rect)).getbbox() is not None

def crop_region(image,region):
    x,y,w,h=validate(region,image.width,image.height);part=image.crop((x,y,x+w,y+h))
    if region.get('polygon'):
        part=part.convert('RGBA');part.putalpha(ImageChops.multiply(part.getchannel('A'),mask(region,[x,y,w,h])))
    return part

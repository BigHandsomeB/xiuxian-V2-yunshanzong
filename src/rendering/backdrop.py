"""Bounded render-only matte for opaque neutral rectangular backdrop; original Runtime stays intact."""
from collections import deque
from PIL import Image

def matte(image):
    image=image.convert('RGBA');w,h=image.size
    if w*h>512*512:return image,0
    box=image.getchannel('A').point(lambda a:255 if a>=200 else 0).getbbox()
    if not box:return image,0
    x0,y0,x1,y1=box;p=image.load()
    def neutral(x,y):
        r,g,b,a=p[x,y];return a>=200 and min(r,g,b)>=165 and max(r,g,b)-min(r,g,b)<=24
    rim=[(x,y) for x in range(x0,x1) for y in (y0,y1-1)]+[(x,y) for y in range(y0+1,y1-1) for x in (x0,x1-1)]
    seeds=[xy for xy in rim if neutral(*xy)]
    # Do not globally key white/gray: outlined white fur, teeth and stone stay intact.
    if len(seeds)<20 or len(seeds)<len(rim)*.55:return image,0
    queue=deque(seeds);seen=set(seeds);removed=0
    while queue:
        x,y=queue.popleft()
        if not neutral(x,y):continue
        r,g,b,a=p[x,y];p[x,y]=(r,g,b,0);removed+=1
        for nx,ny in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
            if x0<=nx<x1 and y0<=ny<y1 and (nx,ny) not in seen and neutral(nx,ny):seen.add((nx,ny));queue.append((nx,ny))
    return image,removed

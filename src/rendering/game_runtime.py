"""Battle Runtime metadata over existing Manifest, without any pipeline changes."""
import hashlib
import io
from src.rendering.backdrop import matte
from collections import defaultdict
from functools import lru_cache
from PIL import Image

@lru_cache(maxsize=128)
def foot_anchor(path,digest,width,height):
    # Read approved Runtime alpha only; source images and manager storage stay outside the game.
    try:
        with Image.open(path) as image:
            box=image.convert("RGBA").getchannel("A").getbbox()
            return (width/2,box[3]) if box else (width/2,height)
    except (OSError,ValueError):return (width/2,height)
@lru_cache(maxsize=16)
def scene_content_box(path,digest):
    with Image.open(path) as image:
        if image.width*image.height>2048*2048:return None
        return image.convert('RGBA').getchannel('A').getbbox()

@lru_cache(maxsize=64)
def enemy_render(path,digest):
    with Image.open(path) as original:
        if original.width*original.height>512*512:raise ValueError('Static actor dimensions exceed render budget')
        image,removed=matte(original)
    output=io.BytesIO();image.save(output,format='PNG');data=output.getvalue();box=image.getchannel('A').point(lambda a:255 if a>32 else 0).getbbox()
    return data,hashlib.sha256(data).hexdigest(),box[3] if box else image.height,removed

from src.rendering.assets import RuntimeAssets


# Only this verified functional icon has a neutral opaque rectangle inside its alpha padding.
UI_SKINS=frozenset({'ui.battle.a9a916abff07b','ui.battle.ac644c27ae6a0','ui.battle.ac3ab9b6b6154','ui.battle.a7a50f6594644','ui.battle.a7bbc6ee2a3e9','ui.battle.a095a2e3790a9','ui.battle.a65c4edacba23','ui.battle.aa3b873806bee','ui.battle.a6d4af6250529'})

@lru_cache(maxsize=16)
def ui_render(path,digest):
    with Image.open(path) as source:
        if source.width*source.height>512*512:raise ValueError('UI render budget exceeded')
        image=source.convert('RGBA');original=image.size
        if image.size==(192,64):image,_=matte(image)
        box=image.getchannel('A').getbbox() or (0,0,*image.size);image=image.crop(box)
    output=io.BytesIO();image.save(output,format='PNG');data=output.getvalue()
    base=[24]*4 if original==(96,96) else [16,24,16,24]
    insets=[max(1,base[0]-box[1]),max(1,base[1]-(original[0]-box[2])),max(1,base[2]-(original[1]-box[3])),max(1,base[3]-box[0])]
    return data,hashlib.sha256(data).hexdigest(),image.width,image.height,insets

# Audited bound icons with baked neutral backdrops. Never key arbitrary white artwork.
MATTE_ICONS=frozenset({
    'icon.resource.a061077002a22',
    'icon.resource.a0b10b9eeac72',
    'icon.resource.a0ba303304245',
    'icon.resource.a151dae2a2cda',
    'icon.resource.a17a6e50f50db',
    'icon.resource.a2f9fea1475e0',
    'icon.resource.a3ba29f2a3c29',
    'icon.resource.a507f3bde4f76',
    'icon.resource.a55f5c0b2b69d',
    'icon.resource.a8d6de25a0d26',
    'icon.resource.a9407d61ea317',
    'icon.resource.aa3953ec12c04',
    'icon.resource.ab38050cee20b',
    'icon.resource.ab943730a1776',
    'icon.resource.abfad7fe8028c',
    'icon.resource.ad00f2f4651f7',
    'icon.resource.ad6b962b8b916',
    'icon.resource.ae537306a8b99',
})

class GameRuntimeAssets(RuntimeAssets):
    def icon(self, asset_id, snapshot=None):
        row=self.resolve(asset_id,snapshot)
        if row and asset_id in UI_SKINS:
            try:
                if hashlib.sha256(row['path'].read_bytes()).hexdigest()!=row['digest']:return None
                _,key,w,h,insets=ui_render(str(row['path']),row['digest']);return {**row,'url':'/play/runtime/'+asset_id+'/'+key,'digest':key,'width':w,'height':h,'nine_slice_insets':insets}
            except (OSError,ValueError):return None
        if row and asset_id in MATTE_ICONS:
            try:
                if hashlib.sha256(row['path'].read_bytes()).hexdigest()!=row['digest']:return None
                _,key,_,removed=enemy_render(str(row['path']),row['digest'])
                if removed:row={**row,'url':'/play/runtime/'+asset_id+'/'+key,'digest':key}
            except (OSError,ValueError):return None
        if row and isinstance(asset_id,str) and asset_id.startswith('scene.environment.'):
            try:row={**row,'content_box':scene_content_box(str(row['path']),row['digest'])}
            except (OSError,ValueError):pass
        return row

    def frames(self, asset_id, snapshot=None):
        snapshot=self.snapshot() if snapshot is None else snapshot
        row=snapshot.get(asset_id,{})
        if not isinstance(row,dict):return []
        files=row.get('files',[])
        if not isinstance(files,list) or not 1<=len(files)<=512:return []
        resolved=[]
        for frame in files:
            current=self.resolve(asset_id,{asset_id:{**row,'files':[frame]}})
            if current is None:return []
            resolved.append((frame,current))
        return resolved

    def file(self, asset_id, digest):
        # Reuse the existing path/digest/symlink guards for each published frame.
        for frame,row in self.frames(asset_id):
            if row['digest']==digest:
                try:
                    if hashlib.sha256(row['path'].read_bytes()).hexdigest()==digest:return row['path']
                except OSError:return None
        if asset_id in UI_SKINS:
            row=self.resolve(asset_id)
            if row and hashlib.sha256(row['path'].read_bytes()).hexdigest()==row['digest']:
                try:
                    data,key,_,_,_=ui_render(str(row['path']),row['digest'])
                    if key==digest:return io.BytesIO(data)
                except (OSError,ValueError):pass
        if isinstance(asset_id,str) and (asset_id.startswith(('monster.static.','boss.static.')) or asset_id in MATTE_ICONS):
            frames=self.frames(asset_id)
            if len(frames)==1:
                row=frames[0][1]
                if hashlib.sha256(row['path'].read_bytes()).hexdigest()!=row['digest']:return None
                try:data,key,_,_=enemy_render(str(row['path']),row['digest'])
                except (OSError,ValueError):return None
                if key==digest:return io.BytesIO(data)
        return None

    def sprite(self, asset_id, snapshot=None, *, role=None):
        snapshot=self.snapshot() if snapshot is None else snapshot
        frames=self.frames(asset_id,snapshot)
        if not frames:return None
        row=snapshot[asset_id];width,height=frames[0][1]['width'],frames[0][1]['height']
        anchor=row.get('anchor',{})
        if not isinstance(anchor,dict):return None
        static=anchor.get('type')=='center' and role=='enemy' and len(frames)==1
        if anchor.get('type')=='bottom_center':
            baseline=anchor.get('baseline_from_bottom')
            if type(baseline) is not int or not 0<=baseline<=height:return None
            ax,ay=width/2,height-baseline
        elif anchor.get('type')=='center' and role in ('enemy','slash','effect'):
            ax,ay=foot_anchor(str(frames[0][1]['path']),frames[0][1]['digest'],width,height) if static else (width/2,height/2)
        else:return None
        grouped=defaultdict(list)
        for frame,public in frames:
            if public['width']!=width or public['height']!=height:return None
            if not isinstance(frame.get('action'),str) or type(frame.get('frame')) is not int:return None
            grouped[frame['action']].append((frame['frame'],public))
        actions={}
        for name,group in grouped.items():
            group.sort(key=lambda item:item[0])
            if [n for n,_ in group]!=list(range(1,len(group)+1)) or len(group)>256:return None
            # Visual playback defaults only. These never drive Simulation.
            timing=row.get('animation',{}).get(name,{}) if isinstance(row.get('animation',{}),dict) else {}
            if not isinstance(timing,dict):return None
            defaults={'player':{'idle':240,'walk':130,'run':130,'move':130,'attack':85,'attack_combo':85,'heavy_attack':95,'skill':90,'ultimate':85,'dodge':100,'hit':110,'death':140},
                      'enemy':{'idle':700,'attack':220,'hit':120,'death':270}}
            duration=timing.get('duration_ms',defaults.get(role,{}).get(name,90 if role in ('effect','slash') else 180))
            values=duration if isinstance(duration,list) else [duration]
            if (isinstance(duration,list) and len(duration)!=len(group)) or any(type(n) is not int or n<1 or n>10000 for n in values):return None
            loop=timing.get('loop',name in ('idle','walk','run','move'))
            triggers=timing.get('triggers',[])
            if type(loop) is not bool or type(triggers) is not list:return None
            for trigger in triggers:
                if (not isinstance(trigger,dict) or type(trigger.get('frame')) is not int or not 0<=trigger['frame']<len(group) or not isinstance(trigger.get('effect'),str) or not trigger['effect']):return None
                if any(type(trigger.get(axis,0)) not in (int,float) for axis in ('x','y')):return None
            actions[name]={'frameCount':len(group),'duration':duration,'loop':loop,
                'frames':[{'url':p['url'].replace('/play/runtime/','/game/runtime/'),'x':0,'y':0,
                           'sheetWidth':width,'sheetHeight':height} for _,p in group],'triggers':triggers}
        if static:
            try:data,key,ay,removed=enemy_render(str(frames[0][1]['path']),frames[0][1]['digest'])
            except (OSError,ValueError):return None
            for action in actions.values():
                for f in action['frames']:f['url']='/game/runtime/'+asset_id+'/'+key
            pose=next(iter(actions.values()))
            actions={name:{**pose,'duration':duration,'loop':name=='idle'} for name,duration in [('idle',700),('attack',220),('hit',240),('death',700)]}
        return {'width':width,'height':height,'anchor':{'x':ax,'y':ay},'actions':actions,'static':static,**({'authoredFacing':'left','backdropMask':True} if static else {})}

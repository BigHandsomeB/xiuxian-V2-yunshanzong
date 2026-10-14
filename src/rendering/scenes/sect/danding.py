"""@module rendering/scenes/sect/danding
@purpose Pure presentation over Danding snapshot + approved Runtime Manifest.
@depends rendering/assets and standard library; @usedBy injected transport renderer
@see ./INDEX.md
"""
import json
from pathlib import Path

BINDINGS=json.loads(Path(__file__).with_name('danding-assets.json').read_text())
LABELS={'prepare':'待开炉','measure':'取药称量','add_herbs':'投药入炉','stable':'文火炼制','high_fire':'旺火炼制','finish':'开炉收丹'}


def scene_state(view):
    current=view['alchemy']['current'];job=current['job']
    if job is None:return 'prepare'
    if current['status'] in ('OUTPUT_READY','COMPLETE'):return 'finish'
    if current['status']!='WORKING':return 'prepare'
    recipe=next(r for r in view['alchemy']['recipes'] if r['recipe_id']==job['recipe_id'])
    fraction=job['progress_milli']/(recipe['duration_ms']*1000)
    if fraction<.1:return 'measure'
    if fraction<.2:return 'add_herbs'
    if fraction<.65:return 'stable'
    return 'high_fire'


def public_asset(row):
    return {k:v for k,v in row.items() if k not in ('path','digest')} if row else None


def present(view,assets):
    manifest=assets.snapshot();state=scene_state(view)
    # Operator retired full-scene stage switching. One approved room stays static;
    # the committed stage remains a read-only text/status projection.
    desired=BINDINGS['scenes']['prepare'];resolved=assets.resolve(desired,manifest)
    if resolved is None:
        # Honest partial-set fallback. Remains a presentation choice, never a reward.
        for key in ('master','prepare','stable','finish','measure','add_herbs','high_fire'):
            resolved=assets.resolve(BINDINGS['scenes'][key],manifest)
            if resolved is not None:break
    return {'scene':{'mode':'static','state':state,'label':LABELS[state],'requested_asset_id':desired,
                     'asset':public_asset(resolved),'fallback':resolved is None or resolved['asset_id']!=desired},
            'icons':{key:public_asset(assets.resolve(asset_id,manifest)) for key,asset_id in BINDINGS['icons'].items()}}

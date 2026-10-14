"""Optional read-only names/order projection of the existing Asset Manager Registry.

Not an asset registry or gameplay definition source. Published Manifest remains
runtime authority; missing/corrupt metadata leaves gameplay icons operational.
No Manager imports, writes, Source paths or service/network dependencies.
"""
import json
import re
import sqlite3
from contextlib import closing
from src.data.public_asset_catalog import read_catalog

MINERALS = (
    ('asset_set.resource.a36585acf5b5d', '凡品'),
    ('asset_set.resource.a56f93b07105b', '灵品'),
    ('asset_set.resource.a86bfbd8c4ac4', '玄品'),
    ('asset_set.resource.af29741b38164', '地品'),
    ('asset_set.resource.a3e38f78160dc', '天品'),
    ('asset_set.resource.a2d44b37fb7aa', '仙品'),
)
PILLS = ('asset_set.pill.ae31afcd557cf', 'asset_set.pill.aeeb3ad9ecf5e')

def metadata(root, snapshot):
    path = root / 'registry' / 'catalog.sqlite3'
    empty = {'available': False, 'groups': []}
    try:
        if (not path.is_file() or path.is_symlink() or
            any(p.is_symlink() for p in path.parents if p.is_relative_to(root)) or
            not path.resolve().is_relative_to(root) or path.stat().st_size > 128*1024*1024):
            return read_catalog(root, snapshot)
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True, timeout=.2)) as db:
            db.execute('PRAGMA query_only=ON')
            # Project only small public fields; never load frozen plans/Source metadata.
            rows = db.execute("""SELECT json_extract(m.body,'$.asset_id'),
                json_extract(m.body,'$.name_zh'),json_extract(m.body,'$.category'),
                json_extract(m.body,'$.set_id'),json_extract(m.body,'$.current_approved_version'),json_extract(m.body,'$.template_id'),
                json_extract(v.value,'$.frozen_spec.template_id'),json_extract(v.value,'$.frozen_spec.template_version')
                FROM metadata AS m, json_each(m.body,'$.versions') AS v WHERE m.kind='asset'
                AND json_extract(m.body,'$.runtime_role') IN ('item_icon','cultivation_manual_icon')
                AND COALESCE(json_extract(m.body,'$.lifecycle_status'),'active')='active'
                AND json_extract(v.value,'$.version')=json_extract(m.body,'$.current_approved_version')
                AND json_extract(v.value,'$.art_status')='approved' LIMIT 10000""").fetchall()
            sets = db.execute("""SELECT id,json_extract(body,'$.name_zh'),
                json_extract(body,'$.asset_ids') FROM metadata WHERE kind='set'
                AND COALESCE(json_extract(body,'$.lifecycle_status'),'active')='active' LIMIT 2000""").fetchall()
        definitions = {sid:(name,json.loads(order or '[]')) for sid,name,order in sets}
        groups = {}
        grade_by_set = dict(MINERALS)
        for aid,name,category,sid,version,template,frozen_template,frozen_version in rows:
            if (not isinstance(aid,str) or not re.fullmatch('[a-z][a-z0-9_.]*',aid)
                or not isinstance(name,str) or not name or len(name)>128
                or category not in ('pill','resource','material','equipment','ui','icon') or aid not in snapshot
                or snapshot[aid].get('version')!=version or sid not in definitions):
                continue
            origin=snapshot[aid].get('export_origin',{})
            if ((frozen_template and frozen_template!=template) or
                (origin and origin.get('template_id')!=template) or
                (origin and frozen_version and origin.get('policy')!='current_item_profile' and origin.get('template_version')!=frozen_version)):continue
            title,order = definitions[sid]
            if not isinstance(title,str) or not isinstance(order,list):continue
            section = 'manual' if template=='cultivation_manual_icon_v1' else 'pill' if category=='pill' else 'mineral' if sid in grade_by_set else 'other'
            group = groups.setdefault(sid,{'set_id':sid,'name':title[:128],
                'category':section,'grade':grade_by_set.get(sid),'items':[]})
            group['items'].append({'asset_id':aid,'name':name,'category':category})
        preferred = list(PILLS)+[sid for sid,_ in MINERALS]
        result=[]
        for sid in sorted(groups,key=lambda key:(preferred.index(key) if key in preferred else len(preferred),key)):
            group=groups[sid];order=definitions[sid][1]
            positions={aid:index for index,aid in enumerate(order) if isinstance(aid,str)}
            group['items'].sort(key=lambda row:(positions.get(row['asset_id'],len(positions)),row['asset_id']))
            result.append(group)
        published = {group['set_id']: group for group in read_catalog(root, snapshot)['groups']}
        published.update({group['set_id']: group for group in result})
        return {'available':True,'groups':list(published.values())}
    except (OSError,sqlite3.Error,ValueError,TypeError,AttributeError):
        return read_catalog(root, snapshot)

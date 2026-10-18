"""Artifact appearance metadata; draft names may precede directions, prompts may not."""
from .model import require

TEMPLATE = 'artifact_static_v1'
MAX_DIRECTION = 1000


def direction(value):
    require(isinstance(value,str) and len(value)<=MAX_DIRECTION,'外观方向须为不超过1000字的文字')
    return value.strip()


def directions(template_id, names, values=None):
    if values is None:return {}
    require(template_id==TEMPLATE,'只有法宝素材支持外观方向')
    require(isinstance(values,dict) and len(values)<=128,'外观方向须按素材名称对应填写')
    require(all(isinstance(k,str) and k in names for k in values),'外观方向包含不存在的素材名称，请重新匹配')
    return {name:direction(text) for name,text in values.items()}


def frozen_items(catalog,items,conn):
    return [{**item,'appearance_direction':catalog.get('asset',item['asset_id'],conn).get('appearance_direction','')} for item in items]

"""Pure, bounded material contributions; existing base rolls are never rewritten."""
from collections.abc import Mapping
from src.core.validation import ValidationError
from src.core.state.envelope import freeze_json, thaw_json
from src.data.economy.refinement import VERSION, settings


def selection(materials, cfg):
    if not isinstance(materials, (list, tuple)) or len(materials) != 3:
        raise ValidationError('请选择三个材料位置，空位使用空值')
    if not any(materials):
        raise ValidationError('至少放入一种精炼材料')
    for rid in materials:
        if rid is not None and (type(rid) is not str or rid not in cfg['materials']):
            raise ValidationError('请选择已开放的矿石或怪物材料')
    return materials


def contribution(cfg, rid, index):
    return {k: n * cfg['slots'][index]['weight_bps'] // 10000
            for k, n in cfg['materials'][rid]['stats'].items()}


def result(materials, cfg):
    selection(materials, cfg)
    stats = {}
    for index, rid in enumerate(materials):
        if rid is None:
            continue
        for key, value in contribution(cfg, rid, index).items():
            stats[key] = stats.get(key, 0) + value
    first = next(rid for rid in materials if rid is not None)
    return freeze_json({'version': VERSION, 'materials': list(materials),
                        'stats': stats, 'element': cfg['materials'][first]['element']})


def cost(materials, cfg):
    selection(materials, cfg)
    amounts = {'coins': cfg['coin_cost']}
    for rid in materials:
        if rid is not None:
            amounts[rid] = amounts.get(rid, 0) + cfg['materials'][rid]['quantity']
    return amounts


def validate(record, registry):
    cfg = settings(registry)
    if not cfg or not isinstance(record, Mapping) or set(record) != {'version', 'materials', 'stats', 'element'}:
        raise ValidationError('invalid equipment refinement')
    if not isinstance(record['stats'], Mapping) or any(type(n) is not int for n in record['stats'].values()):
        raise ValidationError('integer refinement stats required')
    expected = result(record['materials'], cfg)
    if thaw_json(record) != thaw_json(expected):
        raise ValidationError('saved refinement does not match versioned materials')
    return record

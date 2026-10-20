"""Refinement composes equipment and inventory inside the caller's receipt transaction."""
from dataclasses import replace
from src.core.state.envelope import thaw_json
from src.core.validation import ValidationError
from src.core.time.world import paused
from src.data.registry import DefinitionKey
from src.data.economy.refinement import settings
from src.systems.equipment import items, refinement
from src.systems.inventory import operations


def reasons(state, registry, row=None):
    cfg = settings(registry)
    if not cfg:
        return ['精炼尚未开放']
    out = []
    battle = state.domains.get('combat', {}).get('battle') or {}
    if paused(state.time):
        out.append('请先恢复世界运行')
    if state.time['pending']:
        out.append('宗门进度正在续算')
    if state.domains['dungeon']['auto']['enabled'] or battle.get('status') in ('ACTIVE', 'PLAYER_WIN'):
        out.append('请先停止挂机并结束或领取当前战斗')
    forge = max((b['level'] for b in state.domains['sect']['buildings'].values() if b['definition_id'] == 'forge'), default=0)
    if forge < cfg['min_forge_level']:
        out.append('炼器阁等级不足')
    if row is not None:
        from src.application.item_retirement import RETIRED_ITEMS
        if items.unknown(row, registry) or row['definition_id'] in RETIRED_ITEMS:
            out.append('此装备属性尚不能安全精炼')
    return out


def transition(state, registry, payload):
    if set(payload) != {'instance_id', 'materials'} or type(payload['instance_id']) is not str:
        raise ValidationError('请选择装备与三个材料位置')
    cfg = settings(registry)
    if not cfg:
        raise ValidationError('精炼尚未开放')
    row = items.get(state.domains['equipment'], payload['instance_id'])
    blocked = reasons(state, registry, row)
    if blocked:
        raise ValidationError(blocked[0])
    record = refinement.result(payload['materials'], cfg)
    if row.get('refinement') == record:
        raise ValidationError('与当前精炼相同，请更换材料或位置')
    amounts = refinement.cost(payload['materials'], cfg)
    stock = state.domains['inventory']['holdings']
    reserves = state.domains['sect_management']['material_reserves']
    if any(stock.get(k, 0) - reserves.get(k, 0) < n for k, n in amounts.items()):
        raise ValidationError('精炼材料或灵钱不足，或触及库存保留量')
    inventory, _ = operations.consume(state.domains['inventory'], registry, amounts)
    equipment = thaw_json(state.domains['equipment'])
    target = equipment['instances'][payload['instance_id']]
    target['refinement'] = thaw_json(record)
    target['evaluation'] = 'KEEP'
    return replace(state, domains={**state.domains, 'inventory': inventory, 'equipment': equipment}), {
        'operation': 'equipment_refine', 'instance_id': payload['instance_id'],
        'amounts': amounts, 'refinement': thaw_json(record)}


def view(state, registry):
    cfg = settings(registry)
    if not cfg:
        return None
    stock = state.domains['inventory']['holdings']
    reserves = state.domains['sect_management']['material_reserves']
    materials = []
    for rid, row in cfg['materials'].items():
        materials.append({**thaw_json(row), 'resource_id': rid,
            'name': registry.lookup(DefinitionKey('resources', rid)).display_name,
            'current': stock.get(rid, 0), 'reserved': reserves.get(rid, 0),
            'available': max(0, stock.get(rid, 0) - reserves.get(rid, 0)),
            'contributions': [refinement.contribution(cfg, rid, i) for i in range(3)]})
    equipment = {}
    for identity, row in state.domains['equipment']['instances'].items():
        base = {k: v for k, v in row.items() if k != 'refinement'}
        equipment[identity] = {'base_stats': items.effective_stats(base),
            'blocking_reasons': reasons(state, registry, row)}
    return {'version': cfg['version'], 'slots': thaw_json(cfg['slots']),
        'coin_cost': cfg['coin_cost'], 'coins_available': max(0, stock.get('coins', 0) - reserves.get('coins', 0)),
        'materials': materials, 'equipment': equipment, 'blocking_reasons': reasons(state, registry)}

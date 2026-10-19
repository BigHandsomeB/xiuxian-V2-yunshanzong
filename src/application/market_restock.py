"""Compose paid stock targets with the existing workforce, stock and commerce ledger."""
from dataclasses import replace
from src.core.state.envelope import thaw_json
from src.core.time.world import paused
from src.core.validation import ValidationError
from src.data.registry import DefinitionKey
from src.data.economy.market import settings
from src.systems.sect import market, commerce, restock
from src.systems.disciples import work
from src.systems.inventory import operations, holdings
from src.application.sect import capacity_source
from src.application.sect_economy import reserved

COMMANDS = ('market_restock_set', 'market_restock_delete')


def policy(state):
    return state.domains['sect_management'].get('restock', restock.empty())


def workforce(state, registry):
    return sum(work.capability(state.domains['disciples'], registry, bid)['workers']
               for bid, row in state.domains['sect']['buildings'].items()
               if row['definition_id'] == 'trading' and row['level'] > 0)


def configure(state, registry, name, payload):
    fields = {'resource_id', 'target'} if name == 'market_restock_set' else {'resource_id'}
    if set(payload) != fields or type(payload['resource_id']) is not str:
        raise ValidationError('请选择材料及库存保有量')
    rid = payload['resource_id']
    part = thaw_json(state.domains['sect_management'])
    current = part.setdefault('restock', restock.empty())
    if name == 'market_restock_set':
        if rid not in market.eligible(state, registry):
            raise ValidationError('此材料尚未解锁')
        current['targets'][rid] = payload['target']
    else:
        current['targets'].pop(rid, None)
    if not current['targets']:
        current['wake'] = None
    restock.validate(current, registry)
    state = replace(state, domains={**state.domains, 'sect_management': part})
    # The existing market screen predates a persisted trading position. Register
    # that position only on the first explicit configuration, never on a read.
    if name == 'market_restock_set' and not any(row['definition_id'] == 'trading' for row in state.domains['sect']['buildings'].values()):
        sect = thaw_json(state.domains['sect']);counter = state.identity['instance_counter'] + 1
        sect['buildings'][f'{state.save_id}:{state.generation}:i:{counter}'] = {
            'definition_id': 'trading', 'level': 1, 'construction_target': None}
        state = replace(state, identity={**state.identity, 'instance_counter': counter},
                        domains={**state.domains, 'sect': sect})
    return state


def plan(state, registry, rid, target, eligible, offers, workers):
    stock = state.domains['inventory']
    missing = max(0, target - stock['holdings'].get(rid, 0))
    if not missing:
        return 0, '库存已达标'
    if paused(state.time):
        return 0, '世界已暂停'
    if not workers:
        return 0, '等待分配万宝楼弟子'
    if rid not in eligible:
        return 0, '材料尚未解锁'
    if rid not in offers:
        return 0, '等待材料上架'
    remaining = market.stock_remaining(state, registry, rid)
    if not remaining:
        return 0, '今日已售罄，等待补货'
    price = market.price(registry, state.save_id, market.day(state), rid)['buy_price_milli']
    funds = stock['holdings'].get('coins', 0) * 1000 // price
    if not funds:
        return 0, '灵钱不足'
    free = max(0, capacity_source(state, registry)['effective'] - reserved(state, registry)
               - holdings.stock_size(stock, registry))
    if not free:
        return 0, '仓库空间不足'
    return min(missing, remaining, funds, free, settings(registry)['max_purchase_quantity']), '等待自动购买'


def dispatch(state, registry):
    targets = policy(state)['targets']
    if not targets or paused(state.time):
        return state
    workers = workforce(state, registry)
    if not workers:
        return state
    eligible = market.eligible(state, registry)
    offers = market.current_offers(state, registry)
    capacity = capacity_source(state, registry)['effective'] - reserved(state, registry)
    # Same stable order for every request size and online/offline continuation.
    for rid, target in sorted(targets.items()):
        while True:
            quantity, _ = plan(state, registry, rid, target, eligible, offers, workers)
            if not quantity:
                break
            price = market.price(registry, state.save_id, market.day(state), rid)['buy_price_milli']
            coins = market.quote(state, registry, {'resource_id': rid, 'quantity': quantity,
                                 'market_day': market.day(state), 'price_milli': price}, buy=True)
            stock, _ = operations.consume(state.domains['inventory'], registry, {'coins': coins})
            stock, result = operations.grant(stock, registry, {rid: quantity}, capacity=capacity)
            if any(result['discarded'].values()):
                raise ValidationError('自动补货必须完整入库')
            part = thaw_json(state.domains['sect_management'])
            ledger = commerce.today(state)
            ledger['purchases'][rid] = ledger['purchases'].get(rid, 0) + quantity
            part['commerce'] = ledger
            part['restock']['log'] = (part['restock']['log'] + [{
                'resource_id': rid, 'quantity': quantity, 'coins': coins,
                'sim_ms': state.time['sim_time_ms']}])[-20:]
            state = replace(state, domains={**state.domains, 'inventory': stock, 'sect_management': part})
    return state


def view(state, registry):
    current = policy(state)
    eligible = market.eligible(state, registry)
    offers = market.current_offers(state, registry)
    workers = workforce(state, registry)
    name = lambda rid: registry.lookup(DefinitionKey('resources', rid)).display_name
    rows = []
    for rid, target in sorted(current['targets'].items()):
        _, reason = plan(state, registry, rid, target, eligible, offers, workers)
        rows.append({'resource_id': rid, 'name': name(rid), 'target': target,
                     'quantity': state.domains['inventory']['holdings'].get(rid, 0), 'reason': reason})
    return {'workers': workers, 'rows': rows,
            'eligible': [{'resource_id': rid, 'name': name(rid)} for rid in eligible],
            'log': [{**thaw_json(row), 'name': name(row['resource_id'])} for row in current['log']]}

"""Explicit material shop content, separate from generated production costs."""
import json
from dataclasses import dataclass
from pathlib import Path
from src.core.state.envelope import freeze_json
from src.core.validation import ValidationError, integer
from src.data.registry import Definition, DefinitionKey
from src.data.dungeons import catalog

@dataclass(frozen=True,slots=True)
class MarketRules(Definition):
    values:object=None

def register(registry,*,ecology=False):
    cfg=json.loads(Path(__file__).with_suffix('.json').read_text())
    if ecology:
        cfg['items']['meal_qingling_rice']=dict(cfg['items']['food'])
        cfg['retired_items']=['food']
        cfg['identity_aliases']={'meal_qingling_rice':'food'}
    if cfg['version']!='market-v2' or len(cfg['tier_weights'])!=6:raise ValidationError('invalid market rules')
    integer(cfg['offers_per_day'],'daily offers',1)
    integer(cfg['price_variation_permille'],'price variation',0)
    integer(cfg['max_purchase_quantity'],'purchase batch',1)
    if cfg['price_variation_permille']>200 or len(cfg['items'])<cfg['offers_per_day']:raise ValidationError('market pool/price bounds invalid')
    for weight in cfg['tier_weights']:integer(weight,'market weight',1)
    if any(a<=b for a,b in zip(cfg['tier_weights'],cfg['tier_weights'][1:])):raise ValidationError('market weights must decrease')
    dungeon_ids=set(catalog.all_ids())
    for rid,row in cfg['items'].items():
        DefinitionKey('resources',rid)
        integer(row['level'],'shop material level',1)
        integer(row['buy_coins'],'base purchase price',1);integer(row['sell_coins'],'base sale price',1)
        integer(row['value_coins'],'material value',1);integer(row['daily_quantity'],'daily stock',1);integer(row['sect_level'],'sect level',1)
        if type(row['boss_only']) is not bool or set(row['unlock'])-dungeon_ids:raise ValidationError('invalid material source')
        for n in row['unlock'].values():
            integer(n,'source floor',1)
            if n>100:raise ValidationError('source floor outside dungeon')
        if row['level']>6 or row['buy_coins']*800<=row['sell_coins']*1200:raise ValidationError('unsafe market spread')
        if rid=='coins' or 'pill' in rid:raise ValidationError('material shop cannot sell currency or pills')
    for key in ('orders_per_day','order_reward_permille','auction_period_days','auction_duration_days','auction_slots','consignment_limit'):integer(cfg[key],key,1)
    integer(cfg['auction_commission_permille'],'auction commission')
    if cfg['auction_duration_days']>=cfg['auction_period_days'] or cfg['auction_commission_permille']>=1000 or cfg['order_reward_permille']>1000:raise ValidationError('invalid commerce limits')
    registry.register(MarketRules('market_rules','shipping','万宝楼材料商店',tuple(DefinitionKey('resources',rid) for rid in cfg['items']),freeze_json(cfg)))

def settings(registry):return registry.lookup(DefinitionKey('market_rules','shipping')).values

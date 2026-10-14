"""Combat-only retention and conversion. Existing holdings are never reduced."""
from src.data.economy.sect_rules import settings
from src.data.registry import DefinitionKey
from src.data.economy.market import settings as market_settings

def conversion_coins(registry,amounts):
    cfg=settings(registry)
    values=market_settings(registry)['items'] if registry.contains(DefinitionKey('market_rules','shipping')) else {}
    return sum(n*values.get(rid,{}).get('sell_coins',cfg['overflow_coin_per_item']) for rid,n in amounts.items())

def rewards(partition,stock,registry,amounts,*,reserves=None):
    cfg=settings(registry)
    if not cfg or not partition.get('material_overflow',cfg['legacy_material_overflow']):return dict(amounts),{}
    kept=dict(amounts);converted={}
    for key,cap in cfg['material_caps'].items():
        if registry.contains(DefinitionKey('market_rules','shipping')) and market_settings(registry)['items'].get(key,{}).get('boss_only'):continue
        cap=max(cap,(reserves or {}).get(key,0))
        incoming=amounts.get(key,0)
        if not incoming:continue
        retain=min(incoming,max(0,cap-stock.get(key,0)))
        kept[key]=retain
        if incoming>retain:converted[key]=incoming-retain
    kept['coins']=kept.get('coins',0)+conversion_coins(registry,converted)
    return kept,converted

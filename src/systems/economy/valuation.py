"""Shared static input valuations, separated from saved equipment attributes."""
from src.data.registry import DefinitionKey
from src.data.economy.sect_rules import settings
from src.data.economy.market import settings as market_settings

def craft_inputs(registry,key):
    cfg=settings(registry)
    if not cfg:return None
    c=cfg['craft']
    if key in cfg.get('management',{}).get('craft_costs',{}):cost=dict(cfg['management']['craft_costs'][key])
    elif key in c['materials']:
        r=c['common'];cost={'ingot':r['ingot'],c['materials'][key]:r['material'],'coins':r['coins']}
    elif key in c['boss_equipment']:cost=dict(c['boss'])
    else:return None
    definition=registry.lookup(DefinitionKey('equipment',key))
    if definition.craft_fee_coins is not None:cost['coins']=definition.craft_fee_coins
    return cost

def equipment_sale(registry,definition):
    if not registry.contains(DefinitionKey('market_rules','shipping')):return definition.sell_coins
    cost=craft_inputs(registry,definition.machine_id)
    if not cost:return definition.sell_coins
    values=market_settings(registry)['items']
    # Crafting fees buy equipment utility; the merchant does not refund them.
    total=sum(n*values.get(rid,{}).get('value_coins',0) for rid,n in cost.items() if rid!='coins')
    return max(definition.sell_coins,total*6//10)

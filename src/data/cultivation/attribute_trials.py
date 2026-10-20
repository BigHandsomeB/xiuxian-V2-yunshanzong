"""Strict static attribute-trial configuration; no Domain imports."""
from src.core.validation import ValidationError,integer

STATS=('max_hp_milli','attack_milli','armor_milli')
NAMES={'max_hp_milli':'生命','attack_milli':'攻击','armor_milli':'护甲'}

def validate_config(c):
    required={'version','max_wave','max_level','xp_per_first_wave','xp_per_extra_wave','first_level_xp','level_cost_growth','hp_growth_bps','attack_growth_bps','armor_growth_milli','gains'}
    if set(c)!=required or c['version']!=1 or set(c['gains'])!=set(STATS):raise ValidationError('invalid attribute trial configuration')
    for k in required-{'gains'}:integer(c[k],k,1)
    if c['max_wave']>1000 or c['max_level']>1000:raise ValidationError('attribute trial configured bounds exceeded')
    for k,n in c['gains'].items():integer(n,k,1)


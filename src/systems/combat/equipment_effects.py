"""Read-only v1 stat rules. Stable battle/step rolls; no random/save/time authority."""
import hashlib
from src.core.validation import ValidationError,integer

from src.data.economy.definitions import NEW_STAT_CAPS
NEW_CAPS=NEW_STAT_CAPS
from src.data.combat.mechanics import CAPS as EFFECT_CAPS
CAPS={**EFFECT_CAPS,'crit_bps':3000,'accuracy_bps':10000,'evasion_bps':2500,'speed_bps':3000,'reflect_bps':3500,'poison_resist_bps':7500,'execute_bps':2000,'pierce_milli':100000,**NEW_CAPS}
def validate(p):
    for key,limit in CAPS.items():
        if key in p:
            integer(p[key],key)
            if p[key]>limit:raise ValidationError('battle stat exceeds supported cap')
def roll(b,salt):return int.from_bytes(hashlib.sha256((b['battle_id']+'|'+str(b['step'])+'|'+salt).encode()).digest()[:8],'big')%10000
def attack_value(p,b,enemy):
    attack=p['attack_milli']
    critical=roll(b,'critical')<p.get('crit_bps',0)
    if critical:attack=attack*(15000+p.get('crit_damage_bps',0))//10000
    if b['enemy_hp_milli']*100<enemy.base_hp_milli*30:attack=attack*(10000+p.get('execute_bps',0))//10000
    return attack,critical
def outgoing_damage(amount,p):return max(1000,amount*(10000+p.get('damage_bonus_bps',0))//10000)
def incoming_damage(amount,p):return max(1000,amount*(10000-p.get('damage_reduction_bps',0))//10000)
def enemy_attack_value(enemy,p,b):
    chance=max(0,enemy.crit_bps-p.get('crit_resist_bps',0))
    critical=roll(b,'enemy_critical')<chance
    return (enemy.attack_milli*15000//10000 if critical else enemy.attack_milli),critical
def interval(p):return max(1000,2000*10000//(10000+p.get('speed_bps',0)))

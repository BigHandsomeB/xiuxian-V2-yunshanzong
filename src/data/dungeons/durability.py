"""New-fight HP/reward settings; historical battles retain their saved snapshot."""
import json
from functools import lru_cache
from pathlib import Path
from src.core.validation import ValidationError, integer

@lru_cache(maxsize=1)
def settings():
    cfg=json.loads(Path(__file__).with_name('combat_tuning.json').read_text())
    for key in ('monster_hp_scale','reward_compensation_scale'):
        if set(cfg[key])!={'normal','elite','boss'}:raise ValidationError('three durability tiers required')
        for rows in cfg[key].values():
            if not rows or any(type(f) is not int or not 1<=f<=100 or not isinstance(v,(int,float)) or not 1<=v<=100 for f,v in rows):raise ValidationError('invalid durability knots')
            if [f for f,_ in rows]!=sorted(set(f for f,_ in rows)):raise ValidationError('ordered durability knots required')
    if type(cfg['reward_compensation_enabled']) is not bool:raise ValidationError('boolean compensation setting required')
    return cfg

def scale(rows,floor):
    if floor<=rows[0][0]:return rows[0][1]
    for (left,a),(right,b) in zip(rows,rows[1:]):
        if floor<=right:return a+(b-a)*(floor-left)/(right-left)
    return rows[-1][1]

def snapshot(registry,encounter_id):
    from src.systems.dungeons.progress import floor_of
    from src.data.dungeons.expeditions import owner
    from src.data.registry import DefinitionKey
    floor=floor_of(registry,encounter_id)
    if floor is None:return {}
    did=owner(registry,encounter_id) or 'thorn_path'
    d=registry.lookup(DefinitionKey('dungeons',did));tier=d.tiers[floor-1];cfg=settings()
    return {'enemy_hp_scale_bps':round(scale(cfg['monster_hp_scale'][tier],floor)*10000),
            'reward_compensation_bps':round(scale(cfg['reward_compensation_scale'][tier],floor)*10000) if cfg['reward_compensation_enabled'] else 10000}

def amount(quantity,b,resource_id):
    # Round fractional quantities deterministically without touching drop rolls/probabilities.
    from src.data.dungeons.loot import roll
    product=quantity*b.get('reward_compensation_bps',10000);whole,remainder=divmod(product,10000)
    return whole+int(roll(b['battle_id'],'quantity_compensation:'+resource_id)<remainder)

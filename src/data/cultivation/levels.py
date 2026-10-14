"""Integer threshold table; level is derived, never persisted."""
from math import isqrt
from functools import lru_cache
from src.core.validation import ValidationError, integer


def validate_config(c):
    for key in ('levels_per_realm','max_level','open_realms','X0','kills_per_hour','recommended_level_per_floor','pill_minutes','pill_period_ms','pill_full_count'):
        integer(c[key],key,1)
    if c['levels_per_realm']!=500 or c['max_level']!=3000 or c['open_realms']!=2:raise ValidationError('six 500-level realms, two open required')
    curve=c['xp_curve']
    integer(curve['A'],'XP A',1)
    integer(curve['exponent_numerator'],'exponent numerator',1);integer(curve['exponent_denominator'],'exponent denominator',1)
    if curve['rounding']!='floor':raise ValidationError('floor rounding required')
    if len(c['realms'])!=6 or [x['open'] for x in c['realms']]!=[True,True,False,False,False,False]:raise ValidationError('invalid realm opening configuration')
    if not 0<c['minimum_multiplier_percent']<=100 or c['penalty_start_percent']<100:raise ValidationError('invalid XP penalty')
    for key,n in c['tier_multipliers'].items():integer(n,key,1)
    for key in ('growth_coefficient_bps','pill_reduced_percent'):integer(c[key],key)
    if c['pill_reduced_percent']>100:raise ValidationError('invalid reduced pill effect')
    for row in c['pills'].values():
        integer(row['minimum_level'],'pill minimum',1);integer(row['maximum_level'],'pill maximum',1)
        if row['minimum_level']>row['maximum_level'] or row['maximum_level']>1000:raise ValidationError('invalid pill interval')
    return c


@lru_cache(maxsize=16)
def thresholds(A=160,maximum=3000,numerator=1,denominator=2):
    # T[L] starts level L; T[maximum+1] is the full bar at max level.
    out=[0,0]
    for level in range(1,maximum+1):
        value=A**denominator*level**numerator
        if denominator==2:cost=isqrt(value)
        else:
            low,high=0,value+1
            while high-low>1:
                middle=(low+high)//2
                if middle**denominator<=value:low=middle
                else:high=middle
            cost=low
        out.append(out[-1]+cost)
    return tuple(out)

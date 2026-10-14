"""Frozen balance version; decimal coefficients produce exact milli integers."""
import json
from decimal import Decimal,InvalidOperation,ROUND_HALF_UP
from pathlib import Path
from src.core.validation import ValidationError,integer

def content():
    p=json.loads(Path(__file__).with_name('balance.json').read_text())
    validate_content(p,'thorn-balance-v2')
    return p

def validate_content(p,version):
    if set(p)!={'version','curve','tiers','profiles'} or p['version']!=version or set(p['curve'])!={'hp','attack','armor'} or set(p['tiers'])!={'normal','elite','boss'}:raise ValidationError('invalid balance package')
    for section in ('curve','tiers','profiles'):
        for values in p[section].values():
            if not isinstance(values,(list,tuple)) or len(values)!=3:raise ValidationError('balance triple required')
            try:valid=all(isinstance(v,str) and Decimal(v).is_finite() for v in values)
            except InvalidOperation:valid=False
            if not valid:raise ValidationError('finite decimal balance coefficients required')
    return p

def stats(p,floor,tier,name):
    integer(floor,'floor',1)
    if floor>100 or tier not in p['tiers'] or name not in p['profiles']:raise ValidationError('invalid balance reference')
    x=Decimal(floor-1)
    values=[Decimal(p['curve'][key][0])+Decimal(p['curve'][key][1])*x+Decimal(p['curve'][key][2])*x*x for key in ('hp','attack','armor')]
    th,ta,td=map(Decimal,p['tiers'][tier]);sh,sa,sd=map(Decimal,p['profiles'][name])
    h=max(Decimal(1),values[0]*th*sh);a=max(Decimal('.1'),values[1]*ta*sa);d=max(Decimal(0),values[2]+td+sd)
    return tuple(int(n.quantize(step,rounding=ROUND_HALF_UP)*1000) for n,step in ((h,Decimal('1')),(a,Decimal('.1')),(d,Decimal('.1'))))

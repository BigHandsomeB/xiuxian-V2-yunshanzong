"""Two audited macro realms and one pill action, no general consumable framework."""
from dataclasses import dataclass
from pathlib import Path
import json
from src.data.registry import Definition,DefinitionKey,_fields
from src.data.combat.definitions import load_combat
from src.core.validation import ValidationError,DuplicateError,integer

@dataclass(frozen=True,slots=True)
class RealmDefinition(Definition):
    index:int=0
    threshold:int=0
    next_realm_id:str|None=None
    power:int=1
    cost:tuple=()
    def __post_init__(self):
        super(RealmDefinition,self).__post_init__()
        if self.domain!='realms':raise ValidationError('realm namespace required')
        integer(self.index,'realm index');integer(self.threshold,'threshold');integer(self.power,'power',1)
        if type(self.cost) is not tuple or any(type(x) is not tuple or len(x)!=2 for x in self.cost):raise ValidationError('immutable realm costs required')
        keys=[]
        for key,n in self.cost:DefinitionKey('resources',key);integer(n,'cost',1);keys.append(key)
        if len(set(keys))!=len(keys):raise DuplicateError('duplicate realm cost')
        refs=tuple(DefinitionKey('resources',k) for k in keys)
        if self.next_realm_id is not None:
            refs+=(DefinitionKey('realms',self.next_realm_id),)
            if self.threshold<1 or self.next_realm_id==self.machine_id:raise ValidationError('valid next realm required')
        elif self.threshold or self.cost:raise ValidationError('terminal realm has no next target/cost')
        if self.references!=refs:raise ValidationError('realm references mismatch')

@dataclass(frozen=True,slots=True)
class CultivationAction(Definition):
    required_item_id:str='pill'
    quantity:int=1
    gain:int=80
    def __post_init__(self):
        super(CultivationAction,self).__post_init__()
        if self.domain!='cultivation_actions' or self.required_item_id!='pill' or self.quantity!=1:raise ValidationError('single existing pill action required')
        integer(self.quantity,'quantity',1);integer(self.gain,'gain',1)
        if self.references!=(DefinitionKey('resources',self.required_item_id),):raise ValidationError('pill reference mismatch')

START='realm_0'
def load_cultivation(source=None, *, seal=True):
    def unique(pairs):
        d={}
        for k,v in pairs:
            if k in d:raise DuplicateError('duplicate cultivation key')
            d[k]=v
        return d
    def bad(v):raise ValidationError('nonfinite cultivation content')
    try:p=json.loads(source if source is not None else Path(__file__).with_name('content.json').read_text(),object_pairs_hook=unique,parse_constant=bad)
    except (TypeError,json.JSONDecodeError) as exc:raise ValidationError('invalid cultivation JSON') from exc
    _fields(p,('schema_version','content_version','starting_realm','realms','action'))
    if type(p['schema_version']) is not int or p['schema_version']!=1 or p['starting_realm']!=START or type(p['realms']) is not list or len(p['realms'])!=2:raise ValidationError('two-realm package required')
    combat=json.loads((Path(__file__).parents[1]/'combat/content.json').read_text());combat['content_version']=p['content_version'];r=load_combat(json.dumps(combat),seal=False)
    realms=[]
    for x in p['realms']:
        _fields(x,('machine_id','display_name','index','threshold','next_realm_id','power','cost'))
        if type(x['cost']) is not dict:raise ValidationError('realm cost object required')
        cost=tuple(sorted(x['cost'].items()));refs=tuple(DefinitionKey('resources',k) for k,_ in cost)
        if x['next_realm_id'] is not None:refs+=(DefinitionKey('realms',x['next_realm_id']),)
        d=RealmDefinition('realms',x['machine_id'],x['display_name'],refs,x['index'],x['threshold'],x['next_realm_id'],x['power'],cost);r.register(d);realms.append(d)
    start=next((d for d in realms if d.machine_id==START),None)
    if start is None or start.index!=0 or start.next_realm_id is None:raise ValidationError('starting realm invalid')
    end=next((d for d in realms if d.machine_id==start.next_realm_id),None)
    if end is None or end.index!=1 or end.next_realm_id is not None or end.power<=start.power:raise ValidationError('single increasing transition required')
    x=p['action'];_fields(x,('machine_id','display_name','required_item_id','quantity','gain'))
    if x['machine_id']!='pill_train':raise ValidationError('single cultivation action required')
    r.register(CultivationAction('cultivation_actions',x['machine_id'],x['display_name'],(DefinitionKey('resources',x['required_item_id']),),x['required_item_id'],x['quantity'],x['gain']));
    if type(seal) is not bool:raise ValidationError('seal must be boolean')
    if seal:r.seal()
    return r

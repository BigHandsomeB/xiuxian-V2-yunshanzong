"""Deterministic, bounded effect interpreter shared by manual and offline battles.

Owns battle-local statuses, skill cooldowns and resources only. No rewards, clock,
UI or mutable Growth/Equipment input. Chinese display names never select code.
"""
from collections.abc import Mapping
from src.core.state.envelope import thaw_json
from src.core.validation import ValidationError, integer
from src.data.combat import mechanics as definitions
from src.systems.combat.equipment_effects import roll, CAPS, interval
from src.data.combat.skill_timing import VERSION as TIMED_VERSION, CATEGORIES

EVENTS=('skill','status_apply','status_remove','dot','heal','shield','block','cleanse','revive','counter','extra_hit')

def initial(config,sources,enemy_source):
    return {**({'elapsed_ms':0,'ready_ms':{}} if config['version']==TIMED_VERSION else {}),
            'version':config['version'],'sources':sources,'enemy_source':enemy_source,
            'statuses':{'player':[],'enemy':[]},'shields':{'player':0,'enemy':0},
            'shield_until':{'player':0,'enemy':0},
            'resources':{'player':0,'enemy':0},'counts':{},'ready':{},'turn_counts':{},
            'used_types':[],'death_prevention':False,'control_ready':{'player':0,'enemy':0},
            'last_element':{'player':'neutral','enemy':'neutral'},'history':{'player':{},'enemy':{}}}

def validate(value,config,step):
    timed=config['version']==TIMED_VERSION
    fields={'version','sources','enemy_source','statuses','shields','shield_until','resources','counts','ready','turn_counts','used_types','death_prevention','control_ready','last_element','history'}
    if timed:fields|={'elapsed_ms','ready_ms'}
    if not isinstance(value,Mapping) or set(value)!=fields or value['version']!=config['version']:raise ValidationError('invalid combat effects state')
    if timed:
        integer(value['elapsed_ms'],'elapsed combat milliseconds')
        if not max(0,step-1)*1000<=value['elapsed_ms']<=max(0,step-1)*2000:raise ValidationError('combat elapsed time outside action bounds')
    if not isinstance(value['sources'],(tuple,list)) or len(value['sources'])>15:raise ValidationError('bounded battle effect sources required')
    for source in value['sources']:
        if set(source)!={'group','id','level'} or source['group'] not in ('techniques','equipment','artifacts') or source['id'] not in config.get(source['group'],{}):raise ValidationError('unknown battle effect source')
        integer(source['level'],'source level',1)
        if source['level']>(config[source['group']][source['id']]['max_level'] if source['group'] in ('techniques','artifacts') else 1):raise ValidationError('source level outside bound')
    categories={}
    for source in value['sources']:
        if source['group']=='techniques':
            category=config['techniques'][source['id']]['category'];categories[category]=categories.get(category,0)+1
    if any(n>(4 if category=='passive' else 1) for category,n in categories.items()) or sum(s['group']=='equipment' for s in value['sources'])>6 or sum(s['group']=='artifacts' for s in value['sources'])>1:raise ValidationError('effect sources exceed equipment/manual slots')
    if len({(s['group'],s['id']) for s in value['sources']})!=len(value['sources']):raise ValidationError('duplicate battle effect source')
    if value['enemy_source'] is not None and value['enemy_source'] not in config['enemies']:raise ValidationError('unknown enemy effect source')
    if type(value['death_prevention']) is not bool:raise ValidationError('boolean death prevention required')
    for group in ('statuses','shields','shield_until','resources','control_ready','last_element','history'):
        if not isinstance(value[group],Mapping) or set(value[group])!={'player','enemy'}:raise ValidationError('exact effect actors required')
    for actor,rows in value['statuses'].items():
        if not isinstance(rows,(list,tuple)) or len(rows)>64:raise ValidationError('bounded statuses required')
        seen=set()
        for row in rows:
            if not isinstance(row,Mapping) or set(row)!={'status_id','source_id','duration','stacks','magnitude','applied_at','element'} or row['status_id'] not in config['statuses']:raise ValidationError('invalid saved status')
            spec=config['statuses'][row['status_id']]
            for k in ('duration','stacks','magnitude','applied_at'):integer(row[k],k,1 if k in ('duration','stacks') else 0)
            if row['stacks']>spec['max_stacks'] or row['duration']>100 or row['applied_at']>step or row['element'] not in definitions.ELEMENTS or not isinstance(row['source_id'],str):raise ValidationError('status outside definition bounds')
            key=(row['status_id'],row['source_id'])
            if key in seen:raise ValidationError('duplicate saved status')
            seen.add(key)
    for group in ('shields','shield_until','resources','control_ready'):
        for n in value[group].values():integer(n,group)
    for n in value['resources'].values():
        if n>config['balance']['resource_cap']:raise ValidationError('resource cap exceeded')
    if any(e not in definitions.ELEMENTS for e in value['last_element'].values()):raise ValidationError('unknown incoming element')
    allowed={s['group']+':'+s['id']+':'+r['id'] for s in value['sources'] for r in config[s['group']][s['id']]['rules']}
    if value['enemy_source']:
        allowed|={'enemies:'+value['enemy_source']+':'+r['id'] for r in config['enemies'][value['enemy_source']]['rules']}
    for group in ('counts','ready','turn_counts'):
        if not isinstance(value[group],Mapping) or set(value[group])-allowed:raise ValidationError('unknown saved effect counter')
        for n in value[group].values():integer(n,group)
    if timed:
        timed_keys={s['group']+':'+s['id']+':'+r['id'] for s in value['sources'] for r in config[s['group']][s['id']]['rules'] if 'cooldown_ms' in r}
        if not isinstance(value['ready_ms'],Mapping) or set(value['ready_ms'])-timed_keys:raise ValidationError('unknown timed skill counter')
        for n in value['ready_ms'].values():
            integer(n,'skill ready milliseconds')
            if n>value['elapsed_ms']+60000:raise ValidationError('timed cooldown outside bound')
    if not isinstance(value['used_types'],(list,tuple)) or len(set(value['used_types']))!=len(value['used_types']) or any(t not in definitions.OPS for t in value['used_types']):raise ValidationError('invalid effect type history')
    history_keys={'hit','hurt','evade','block','heal','skill','negative','clean_turns','last_hurt_turn','last_movement_turn','last_skill_turn','category_special','category_ultimate',*(('category_'+c) for c in ('movement','defense') if timed),*(('element_'+e) for e in definitions.ELEMENTS),*(('dealt_'+e) for e in definitions.ELEMENTS),*(('negative_'+s) for s in config['statuses']),*(('kind_'+k) for k in ('direct','skill','ranged','dot','reflect','counter','extra_hit'))}
    for history in value['history'].values():
        if not isinstance(history,Mapping) or set(history)-history_keys:raise ValidationError('invalid effect history')
        for n in history.values():integer(n,'effect history')

class Round:
    def __init__(self,battle,enemy,player,config,emit=True):
        self.b=battle;self.e=enemy;self.p=player;self.c=config;self.s=battle['mechanics'];self.events=[]
        self.depth=0;self.budget=0;self.source=None;self.actor='player';self.context={};self.incoming=None
        self.emit=emit

    def event(self,kind,actor,target,amount=0,formula=None,*,status_id=None,element=None,damage_kind=None):
        if self.emit and len(self.events)<self.c['balance']['event_limit']:
            self.events.append({'kind':kind,'actor':actor,'target':target,'damage_milli':amount,
                'formula_damage_milli':amount if formula is None else formula,'target_hp_milli':self.b[target+'_hp_milli'],
                **({'source_id':self.source} if self.source else {}),
                **({'status_id':status_id} if status_id else {}),
                **({'element':element,'damage_kind':damage_kind} if element is not None else {})})

    def maximum(self,a):return self.p['max_hp_milli'] if a=='player' else self.e.base_hp_milli
    def other(self,a):return 'enemy' if a=='player' else 'player'
    def rows(self,a,status=None,source=False):
        return [r for r in self.s['statuses'][a] if (status is None or r['status_id']==status) and (not source or r['source_id']==self.source)]
    def stacks(self,a,status):return sum(r['stacks'] for r in self.rows(a,status,source=status.startswith('charge_')))
    def element(self,a):
        if a=='enemy':return self.c['enemies'].get(self.s['enemy_source'],{}).get('element','neutral')
        for source in self.s['sources']:
            if source['group']=='equipment':
                element=self.c['equipment'][source['id']].get('attack_element')
                if element:return element
        return 'neutral'
    def attack_kind(self,a):
        if a=='enemy':return self.c['enemies'].get(self.s['enemy_source'],{}).get('attack_kind','direct')
        return next((self.c['equipment'][s['id']]['attack_kind'] for s in self.s['sources'] if s['group']=='equipment' and 'attack_kind' in self.c['equipment'][s['id']]),'direct')
    def stat(self,a,key):
        n=self.p.get(key,0) if a=='player' else {'attack_milli':self.e.attack_milli,'armor_milli':self.e.armor_milli,'crit_bps':self.e.crit_bps}.get(key,0)
        for r in self.rows(a):
            spec=self.c['statuses'][r['status_id']]
            if spec.get('requires_shield') and not self.s['shields'][a]:continue
            modifier=spec.get('modifiers',{}).get(key,0)
            if r['status_id'] in ('chill','slow'):modifier=modifier*(10000+r['magnitude'])//10000
            n+=(modifier+spec.get('magnitude_modifiers',{}).get(key,0)*r['magnitude']//10000)*r['stacks']
        if key.endswith('_resist_bps'):
            n+=sum(self.c['statuses'][r['status_id']].get('modifiers',{}).get('adaptive_resist_bps',0) for r in self.rows(a) if r['element']==key.removesuffix('_resist_bps'))
        cap=CAPS.get(key,self.c['balance'].get(key.removesuffix('_bps')+'_cap_bps'))
        return min(cap,n) if cap is not None else n
    def value(self,x):
        if type(x) in (int,bool):return x
        if isinstance(x,str):
            if x=='turn':return self.b['step']
            if x=='level':return self.context.get('level',1)
            if x=='types':return len(self.s['used_types'])
            if x=='tier':return self.context.get('tier',0)
            if x.startswith('event.is_'):return int(self.context.get('element')==x[9:])
            if x.startswith('event.'):return self.context.get(x[6:],0)
            if x.startswith(('own.','target.')):
                a=self.actor if x.startswith('own.') else self.other(self.actor);k=x.split('.',1)[1]
                if k=='hp_bps':return self.b[a+'_hp_milli']*10000//self.maximum(a)
                if k=='max_hp':return self.maximum(a)
                if k=='shield':return self.s['shields'][a]
                if k=='resource':return self.s['resources'][a]
                if k=='negatives':return len({r['status_id'] for r in self.rows(a) if self.c['statuses'][r['status_id']].get('negative')})
                if k=='dead':return self.b[a+'_hp_milli']==0
                if k=='dot':return sum(r['stacks'] for r in self.rows(a) if self.c['statuses'][r['status_id']].get('tick')=='damage')
                if k=='clean_turns':return max(0,self.b['step']-self.s['history'][a].get('last_hurt_turn',0))
                if k=='unique_negatives':return sum(key.startswith('negative_') for key in self.s['history'][a])
                if k=='unique_elements':return sum(key.startswith('element_') for key in self.s['history'][a])
                if k.startswith('stack:'):return self.stacks(a,k[6:])
                if k.startswith('history:'):return self.s['history'][a].get(k[8:],0)
                return self.stat(a,k)
            raise ValidationError('unknown effect expression reference: '+x)
        op=x[0];v=[self.value(t) for t in x[1:]]
        if op=='add':return sum(v)
        if op=='sub':return v[0]-v[1]
        if op=='mul':return v[0]*v[1]//10000
        if op=='div':return v[0]//max(1,v[1])
        if op=='min':return min(v)
        if op=='max':return max(v)
        if op=='lt':return v[0]<v[1]
        if op=='le':return v[0]<=v[1]
        if op=='gt':return v[0]>v[1]
        if op=='ge':return v[0]>=v[1]
        if op=='eq':return v[0]==v[1]
        if op=='and':return all(v)
        if op=='or':return any(v)
        if op=='not':return not v[0]
        if op=='if':return v[1] if v[0] else v[2]
        raise ValidationError('unknown expression operator')

    def trigger(self,actor,event,*,phase=None,**context):
        if self.depth>=4 or self.budget>=self.c['balance']['effect_budget']:return
        old=(self.actor,self.source,self.context);self.actor=actor;self.depth+=1
        sources=self.s['sources'] if actor=='player' else ([{'group':'enemies','id':self.s['enemy_source'],'level':1}] if self.s['enemy_source'] else [])
        for source in sources:
            self.source=source['group']+':'+source['id'];self.context={**context,'level':source['level']}
            for rule in self.c[source['group']][source['id']]['rules']:
                if self.budget>=self.c['balance']['effect_budget']:break
                if phase=='passive' and rule.get('category') or phase=='active' and not rule.get('category'):continue
                if phase=='prepare' and rule.get('category') not in ('movement','defense'):continue
                key=self.source+':'+rule['id']
                if rule['trigger']!=event or self.s['ready'].get(key,0)>self.b['step']:continue
                if rule.get('requires_active') and not self.stacks(actor,rule['requires_active']):continue
                if rule.get('cooldown_ms') and self.s['ready_ms'].get(key,0)>self.s['elapsed_ms']:continue
                if self.s['turn_counts'].get(key,0)>=rule.get('per_turn',1) or self.s['counts'].get(key,0)>=rule.get('per_battle',10000):continue
                if rule.get('every',1) and self.b['step']%rule.get('every',1):continue
                if not self.value(rule.get('condition',True)):continue
                category=rule.get('category')
                if category and self.stacks(actor,'freeze'):continue
                if category and self.stacks(actor,'seal') and not self.stacks(actor,'unsealed'):
                    # A seal suppresses one eligible special trigger; it does not
                    # disable unrelated passives or permanently silence a Boss.
                    self.s['statuses'][actor]=[s for s in self.rows(actor) if s['status_id']!='seal']
                    self.event('status_remove',actor,actor)
                    continue
                if self.s['resources'][actor]<rule.get('cost',0):continue
                if roll(self.b,key+':'+event+':'+str(self.s['counts'].get(key,0)))>=rule.get('chance',10000):continue
                self.s['turn_counts'][key]=self.s['turn_counts'].get(key,0)+1;self.s['counts'][key]=self.s['counts'].get(key,0)+1
                self.s['ready'][key]=self.b['step']+rule.get('cooldown',0);self.budget+=1
                if rule.get('cooldown_ms'):self.s['ready_ms'][key]=self.s['elapsed_ms']+rule['cooldown_ms']
                if source['group']=='techniques' and self.c['techniques'][source['id']]['category']=='movement':
                    self.s['history'][actor]['last_movement_turn']=self.b['step']
                    self.s['statuses'][actor]=[s for s in self.rows(actor) if self.c['statuses'][s['status_id']].get('break_on_category')!='movement']
                self.s['resources'][actor]-=rule.get('cost',0)
                if category:
                    self.s['history'][actor]['skill']=self.s['history'][actor].get('skill',0)+1
                    gap=self.b['step']-self.s['history'][actor].get('last_skill_turn',0)
                    self.s['history'][actor]['last_skill_turn']=self.b['step']
                    element=next((e.get('element','neutral') for e in rule['effects'] if e['op']=='damage'),'neutral')
                    marker='category_'+category;new_category=marker not in self.s['history'][actor];self.s['history'][actor][marker]=1
                    accuracy=max(self.c['balance']['minimum_accuracy_bps'],min(10000,self.c['balance']['base_accuracy_bps']+self.stat(actor,'accuracy_bps')-self.stat(self.other(actor),'evasion_bps')))
                    self.context.update(skill_hit=roll(self.b,key+':skill_hit')<accuracy,critical=int(roll(self.b,key+':skill_crit')<max(0,self.stat(actor,'crit_bps'))))
                    self.event('skill',actor,self.other(actor))
                    # Trigger once the cooldown is committed, so refund effects
                    # operate on this cast's cooldown and cannot cast recursively.
                    if self.c['version']!=TIMED_VERSION or category in ('special','ultimate'):
                        self.trigger(actor,'skill_cast',category=CATEGORIES[category],element=element,new_category=int(new_category),gap_turns=gap)
                for effect in rule['effects']:
                    if self.value(effect.get('condition',True)):
                        self.apply(effect)
                        if effect['op'] not in self.s['used_types']:self.s['used_types'].append(effect['op'])
                if category in ('movement','defense') and self.c['version']==TIMED_VERSION:self.trigger(actor,'skill_cast',category=CATEGORIES[category],element=element,new_category=int(new_category),gap_turns=gap)
                if category:self.s['statuses'][actor]=[s for s in self.rows(actor) if not self.c['statuses'][s['status_id']].get('consume_on_skill')]
        self.actor,self.source,self.context=old;self.depth-=1

    def apply(self,effect):
        op=effect['op'];a=self.actor;targets=[a,self.other(a)] if effect.get('target')=='both' else [self.other(a) if effect.get('target')=='other' else a]
        n=max(0,self.value(effect.get('amount',0)))
        if self.context.get('skill_hit') is False and effect.get('target')=='other' and op in ('damage','status','consume','remove_shield','dispel'):
            self.event('miss',a,self.other(a));return
        for target in targets:
            if op=='damage':
                for _ in range(max(1,min(12,self.value(effect.get('count',1))))):
                    self.damage(a,target,n,effect.get('element','neutral'),effect.get('kind','skill'))
            elif op=='heal':
                if not self.b[target+'_hp_milli']:continue
                n=n*max(0,10000+self.stat(target,'heal_bonus_bps'))//10000
                n=min(n,self.maximum(target)-self.b[target+'_hp_milli']);self.b[target+'_hp_milli']+=n
                if n:
                    self.s['statuses'][target]=[s for s in self.rows(target) if not (self.c['statuses'][s['status_id']].get('consume_on_heal') or self.c['statuses'][s['status_id']].get('consume_on_support'))]
                    self.event('heal',a,target,n);self.s['history'][target]['heal']=self.s['history'][target].get('heal',0)+1;self.trigger(target,'on_heal',amount=n);self.trigger(target,'on_support',amount=n)
            elif op=='shield':
                if not self.b[target+'_hp_milli']:continue
                n=n*max(0,10000+self.stat(target,'shield_bonus_bps'))//10000
                self.s['shields'][target]=min(self.maximum(target),max(self.s['shields'][target],n))
                self.s['shield_until'][target]=self.b['step']+max(1,self.value(effect.get('duration',self.c['balance']['default_shield_duration'])))
                self.s['statuses'][target]=[s for s in self.rows(target) if not self.c['statuses'][s['status_id']].get('consume_on_support')]
                self.event('shield',a,target,n);self.trigger(target,'on_shield',amount=n)
                self.trigger(target,'on_support',amount=n)
            elif op=='status':self.status(target,effect['status'],n,max(1,self.value(effect.get('duration',self.c['statuses'][effect['status']]['duration']))),max(1,self.value(effect.get('stacks',1))),effect.get('element','neutral'))
            elif op=='consume':
                left=self.value(effect.get('stacks',20))
                for row in self.rows(target,effect['status'],source=not self.c['statuses'][effect['status']].get('negative',False)):
                    consumed=min(left,row['stacks']);row['stacks']-=consumed;left-=consumed
                    if row['stacks']==0:self.s['statuses'][target].remove(row);self.trigger(target,'status_removed')
            elif op in ('cleanse','dispel'):
                limit=self.value(effect.get('count',1));removed=0
                for row in list(self.rows(target)):
                    spec=self.c['statuses'][row['status_id']]
                    if bool(spec.get('negative'))!=(op=='cleanse'):continue
                    if effect.get('status') and row['status_id']!=effect['status']:continue
                    self.s['statuses'][target].remove(row);removed+=1;self.trigger(target,'status_removed')
                    if removed>=limit:break
                self.context['cleansed']=removed
                self.context['removed_count']=self.context.get('removed_count',0)+removed
                if removed:self.event('cleanse',a,target);self.trigger(target,'status_removed',cleansed=removed)
            elif op=='cooldown':
                prefix='techniques:' if target=='player' else 'enemies:'
                if 'ready_ms' in self.s:
                    for key in sorted(self.s['ready_ms']):
                        if key.startswith(prefix) and self.s['ready_ms'][key]>self.s['elapsed_ms']:
                            self.s['ready_ms'][key]=max(self.s['elapsed_ms']+interval(self.p),self.s['ready_ms'][key]-n*interval(self.p));break
                    else:key=None
                    if key is not None:continue
                for key in sorted(self.s['ready']):
                    if key.startswith(prefix) and self.s['ready'][key]>self.b['step']:
                        self.s['ready'][key]=max(self.b['step']+1,self.s['ready'][key]-n);break
            elif op=='resource':self.s['resources'][target]=min(self.c['balance']['resource_cap'],self.s['resources'][target]+n)
            elif op=='revive':
                if target=='player' and not self.s['death_prevention']:
                    self.s['death_prevention']=True;self.b['player_hp_milli']=max(1,n);self.event('revive',a,target,n)
            elif op=='reduce' and self.incoming is not None:self.incoming=max(0,self.incoming*(10000-min(10000,n))//10000)
            elif op=='convert' and self.incoming is not None:
                converted=self.incoming*min(10000,n)//10000;self.incoming-=converted
                ticks=self.c['balance']['delayed_ticks']
                self.status(target,effect.get('status','delayed'),converted//ticks,ticks,1,'neutral')
            elif op=='extend':
                for row in self.rows(target,effect.get('status')):
                    row['duration']=min(100,row['duration']+n);break
            elif op=='shorten':
                for row in list(self.rows(target,effect.get('status'))):
                    row['duration']-=n
                    if row['duration']<=0:self.s['statuses'][target].remove(row);self.trigger(target,'status_removed')
            elif op=='remove_shield':
                amount=min(self.s['shields'][target],n);self.s['shields'][target]-=amount;self.context['removed_shield']=amount
                if amount and not self.s['shields'][target]:self.trigger(target,'shield_break',amount=amount)

    def status(self,a,status,magnitude,duration,stacks,element):
        spec=self.c['statuses'][status]
        if spec.get('exclusive_group'):
            self.s['statuses'][a]=[s for s in self.rows(a) if s['source_id']!=self.source or self.c['statuses'][s['status_id']].get('exclusive_group')!=spec['exclusive_group'] or s['status_id']==status]
        if status=='burn':magnitude=magnitude*max(0,10000+self.stat(self.actor,'burn_bonus_bps'))//10000
        if status in ('chill','slow'):magnitude=max(0,self.stat(self.actor,'chill_bonus_bps'))
        if element=='incoming':element=self.s['last_element'][a]
        if element not in definitions.ELEMENTS:element='neutral'
        if spec.get('negative') and self.actor!=a and roll(self.b,(self.source or 'basic')+':resist:'+status+':'+str(self.budget))<max(0,min(self.c['balance']['resist_cap_bps'],self.stat(a,'status_resist_bps'))):
            self.trigger(a,'status_resisted');return
        if spec.get('control') and self.s['control_ready'][a]>self.b['step']:
            self.trigger(a,'status_resisted');return
        if spec.get('control'):
            duration=min(duration,self.c['balance']['boss_control_duration'] if a=='enemy' and self.c['enemies'].get(self.s['enemy_source'],{}).get('tier')==2 else duration)
            self.s['control_ready'][a]=self.b['step']+duration+self.c['balance']['control_immunity_turns']
        # Positive readiness/stance belongs to its source. Negative DOT/control
        # stacks are shared on the affected actor and retain their global cap.
        rows=self.rows(a,status,source=not spec.get('negative',False))
        row=rows[0] if rows else None
        if row:
            row.update(stacks=min(spec['max_stacks'],row['stacks']+stacks),duration=min(100,max(row['duration'],duration)),magnitude=max(magnitude,row['magnitude']),applied_at=self.b['step'],element=element)
        elif len(self.s['statuses'][a])<64:
            row={'status_id':status,'source_id':self.source or 'basic','duration':min(100,duration),'stacks':min(spec['max_stacks'],stacks),'magnitude':magnitude,'applied_at':self.b['step'],'element':element};self.s['statuses'][a].append(row)
        marker='negative_'+status;is_new=marker not in self.s['history'][a]
        if spec.get('negative'):self.s['history'][a][marker]=1
        self.event('status_apply',self.actor,a,status_id=status);self.trigger(a,'status_applied',negative=int(bool(spec.get('negative'))),new_negative=int(is_new and bool(spec.get('negative'))),status=status)
        if status=='chill' and self.stacks(a,'chill')>=self.c['balance']['freeze_stacks']:
            self.s['statuses'][a]=[r for r in self.rows(a) if r['status_id']!='chill'];self.status(a,'freeze',0,1,1,'ice')

    def damage(self,a,target,n,element='neutral',kind='direct',pierce=0):
        if not self.b[a+'_hp_milli'] or not self.b[target+'_hp_milli']:return 0
        if element=='weakest':element=min((e for e in definitions.ELEMENTS if e!='neutral'),key=lambda e:(self.stat(target,e+'_resist_bps'),e))
        if element=='incoming':element=self.s['last_element'][target]
        if kind not in ('dot','reflect'):
            if kind=='skill':
                n+=self.stat(a,'spirit_milli')*self.c['balance']['spirit_skill_bps']//10000
                if self.context.get('critical'):n=n*(self.c['balance']['critical_multiplier_bps']+self.stat(a,'crit_damage_bps'))//10000
            if kind=='skill' or kind=='extra_hit' and self.context.get('skill_hit'):
                n=n*max(0,10000+self.stat(a,'skill_bonus_bps'))//10000
            n=n*max(0,10000+self.stat(a,'attack_bonus_bps'))//10000
            n=max(self.c['balance']['minimum_damage_milli'],n-max(0,self.stat(target,'armor_milli')-pierce-self.stat(a,'pierce_milli')))
            n=n*max(0,10000+self.stat(a,'damage_bonus_bps'))//10000
        n=n*max(0,10000+self.stat(a,element+'_damage_bps'))//10000
        converted=n*max(0,min(self.c['balance']['convert_cap_bps'],self.stat(target,'convert_bps')))//10000 if element!='neutral' else 0
        n=converted+(n-converted)*max(0,10000-min(self.c['balance']['resist_cap_bps'],self.stat(target,element+'_resist_bps')))//10000
        reduction=self.stat(target,'damage_reduction_bps')+(self.stat(target,'dot_reduction_bps') if kind=='dot' else 0)
        n=n*max(0,10000-min(self.c['balance']['reduction_cap_bps'],reduction))//10000
        old=self.incoming;self.incoming=n
        if kind not in ('dot','reflect'):
            self.trigger(target,'before_hurt',amount=n,element=element,critical=self.context.get('critical',0),tier=self.context.get('tier',0))
            if roll(self.b,a+':block:'+str(self.budget))<max(0,min(self.c['balance']['resist_cap_bps'],self.stat(target,'block_bps'))):
                self.incoming=self.incoming*(10000-self.c['balance']['block_reduction_bps'])//10000;self.event('block',target,a)
                self.s['history'][target]['block']=self.s['history'][target].get('block',0)+1;self.trigger(target,'on_block',amount=n-self.incoming)
        n=self.incoming;self.incoming=old
        shield=self.s['shields'][target]
        penetration=n*max(0,min(self.c['balance']['shield_pierce_cap_bps'],self.stat(a,'shield_pierce_bps')))//10000 if kind not in ('dot','reflect') else 0
        absorbed=min(shield,n-penetration);self.s['shields'][target]-=absorbed;n-=absorbed
        if shield and not self.s['shields'][target]:self.trigger(target,'shield_break',amount=shield)
        actual=min(n,self.b[target+'_hp_milli']);self.b[target+'_hp_milli']-=actual
        self.s['last_element'][target]=element
        if not self.b[target+'_hp_milli'] and target=='player' and not self.s['death_prevention']:self.trigger(target,'lethal',amount=actual)
        self.event(kind if kind in ('dot','reflect','counter','extra_hit') else 'damage',a,target,actual,n,element=element,damage_kind=kind)
        if (kind=='skill' or kind=='ranged' and 'skill_hit' in self.context) and target==self.other(a):
            marker='dealt_'+element;is_new=marker not in self.s['history'][a];self.s['history'][a][marker]=1
            self.trigger(a,'on_hit',amount=actual,tier=self.c['enemies'].get(self.s['enemy_source'],{}).get('tier',0),element=element,new_element=int(is_new))
        if actual:
            self.s['history'][target]['hurt']=self.s['history'][target].get('hurt',0)+1;self.s['history'][target]['last_hurt_turn']=self.b['step']
        if actual or absorbed:
            marker='element_'+element;new_element=marker not in self.s['history'][target];self.s['history'][target][marker]=1
            marker='kind_'+kind;new_kind=marker not in self.s['history'][target];self.s['history'][target][marker]=1
            self.trigger(target,'on_hurt',amount=actual,kind=int(kind in ('direct','skill','ranged')),melee=int(kind in ('direct','skill')),element=element,new_element=int(new_element),new_kind=int(new_kind),shield_hit=int(bool(shield)))
        if kind in ('direct','skill','ranged'):self.s['statuses'][a]=[s for s in self.rows(a) if not self.c['statuses'][s['status_id']].get('consume_on_hit')]
        if kind in ('direct','skill') and self.b[target+'_hp_milli']:
            reflected=actual*max(0,min(self.c['balance']['reflect_cap_bps'],self.stat(target,'reflect_bps')))//10000
            if reflected:self.damage(target,a,reflected,'neutral','reflect')
        return actual

    def turn(self):
        if self.c['version']==TIMED_VERSION and self.b['step']:
            self.s['elapsed_ms']+=interval(self.p)
        self.b['step']+=1;self.s['turn_counts']={}
        for actor in ('player','enemy'):
            if self.s['shield_until'][actor]<=self.b['step']:self.s['shields'][actor]=0
            if not self.s['shields'][actor]:self.s['statuses'][actor]=[s for s in self.rows(actor) if not self.c['statuses'][s['status_id']].get('requires_shield')]
            self.s['resources'][actor]=min(self.c['balance']['resource_cap'],self.s['resources'][actor]+self.c['balance']['resource_per_turn'])
        if self.b['step']==1:
            for actor in ('player','enemy'):self.trigger(actor,'battle_start')
        tier=self.context['tier']=self.c['enemies'].get(self.s['enemy_source'],{}).get('tier',0)
        # Establish turn-start stances before initiative. Active skills then run
        # in that initiative order, so a temporary speed bonus affects this turn.
        for actor in ('player','enemy'):
            if self.c['version']==TIMED_VERSION and self.b['player_hp_milli'] and self.b['enemy_hp_milli']:
                self.trigger(actor,'turn_start',phase='prepare',tier=tier)
            if self.b['player_hp_milli'] and self.b['enemy_hp_milli']:self.trigger(actor,'turn_start',phase='passive',tier=tier)
        order=('player','enemy') if self.stat('player','speed_bps')>=self.stat('enemy','speed_bps') else ('enemy','player')
        for actor in order:
            if not self.b['player_hp_milli'] or not self.b['enemy_hp_milli']:break
            self.actor=actor;self.trigger(actor,'turn_start',phase='active',tier=tier)
            target=self.other(actor)
            if self.b[actor+'_hp_milli'] and self.b[target+'_hp_milli'] and not self.stacks(actor,'freeze'):
                self.trigger(actor,'before_attack',tier=tier)
                accuracy=max(self.c['balance']['minimum_accuracy_bps'],min(10000,self.c['balance']['base_accuracy_bps']+self.stat(actor,'accuracy_bps')-self.stat(target,'evasion_bps')))
                self.event(actor+'_attack',actor,target)
                if roll(self.b,actor+':hit')<accuracy:
                    critical=roll(self.b,actor+':crit')<max(0,self.stat(actor,'crit_bps')-self.stat(target,'crit_resist_bps'))
                    n=self.stat(actor,'attack_milli')
                    if critical:n=n*(self.c['balance']['critical_multiplier_bps']+self.stat(actor,'crit_damage_bps'))//10000;self.event('critical',actor,target)
                    self.context={'tier':tier,'critical':int(critical)}
                    actual=self.damage(actor,target,n,self.element(actor),self.attack_kind(actor))
                    self.s['history'][actor]['hit']=self.s['history'][actor].get('hit',0)+1
                    element=self.element(actor);marker='dealt_'+element;new_element=marker not in self.s['history'][actor];self.s['history'][actor][marker]=1
                    self.trigger(actor,'on_hit',amount=actual,tier=tier,critical=int(critical),element=element,new_element=int(new_element))
                    if self.stat(actor,'burn_apply_bps')>roll(self.b,actor+':burn'):
                        self.actor=actor;self.source='basic';self.status(target,'burn',self.stat(actor,'attack_milli')//10,3,1,'fire')
                    if critical:self.trigger(actor,'on_crit',amount=actual,tier=tier)
                    steal=actual*max(0,min(self.c['balance']['lifesteal_cap_bps'],self.stat(actor,'lifesteal_bps')))//10000
                    if steal:
                        self.actor=actor;self.apply({'op':'heal','amount':steal})
                else:
                    self.event('miss',actor,target);self.s['history'][target]['evade']=self.s['history'][target].get('evade',0)+1;self.trigger(target,'on_evade',tier=tier)
            # Duration counts the affected actor's actions, including a skipped
            # action under control. Thus a one-turn freeze skips exactly one action.
            for row in list(self.rows(actor)):
                spec=self.c['statuses'][row['status_id']]
                if spec.get('tick')=='damage':self.damage(self.other(actor),actor,row['magnitude']*row['stacks'],row['element'],'dot')
                elif spec.get('tick')=='heal':self.actor=actor;self.apply({'op':'heal','amount':row['magnitude']*row['stacks']})
                row['duration']-=1
                if row['duration']<=0 and row in self.s['statuses'][actor]:self.s['statuses'][actor].remove(row);self.trigger(actor,'status_removed')
            self.trigger(actor,'turn_end',tier=tier)
        if not self.b['player_hp_milli']:
            self.b['status']='PLAYER_LOSE';self.event('player_defeated','enemy','player');self.event('battle_lost','enemy','player')
        elif not self.b['enemy_hp_milli']:
            self.trigger('player','kill',tier=tier);self.b.update(status='PLAYER_WIN',reward_state='READY',reward=dict(self.e.reward))
            self.trigger('player','battle_end',won=1);self.event('enemy_defeated','player','enemy');self.event('battle_won','player','enemy');self.event('reward_ready','player','enemy')
        elif self.b['step']>=self.c['balance']['max_turns']:
            self.b.update(status='ABANDONED',reward_state='NONE');self.event('battle_abandoned','player','enemy')
        terminal={'PLAYER_WIN':'battle_won','PLAYER_LOSE':'battle_lost','ABANDONED':'battle_abandoned'}
        self.b['latest_events']=self.events or [{'kind':terminal.get(self.b['status'],'battle_started'),'actor':'battle','target':'battle','damage_milli':0,'formula_damage_milli':0,'target_hp_milli':0}]

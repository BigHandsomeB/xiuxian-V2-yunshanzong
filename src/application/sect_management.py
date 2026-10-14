"""Sect services use the existing single save, transaction, receipts and workforce."""
from dataclasses import replace
from src.application.dungeons import DungeonApplication
from src.application.sect_management_settlement import ManagementSettlement
from src.application.memory import Command,Receipt
from src.application.danding import envelope,SliceRequestError
from src.application import equipment as equip
from src.application import offline_reports as reports
from src.core.save.codec import StoredReceipt
from src.core.state.envelope import thaw_json,freeze_json
from src.core.validation import ValidationError,ConflictError,integer
from src.core.time.world import require_running,paused
from src.data.registry import DefinitionKey
from src.systems.sect import management,buildings,rules
from src.systems.sect import market
from src.systems.sect import commerce
from src.application import commerce as commerce_app
from src.data.economy.market import settings as market_settings
from src.systems.resources import jobs
from src.systems.inventory import operations
from src.systems.dungeons import progress
from src.systems.equipment import items

COMMANDS=('sect_recruit','sect_supply','sect_facility_build','material_sell','material_reserve','equipment_enhance','sect_stone_buy','market_buy',*commerce_app.COMMANDS,'offline_report_ack')
class ManagementApplication(DungeonApplication):
    def require_management_command(self,state,name):
        if name in ('market_bid','market_consign','market_auction_claim','market_consignment_claim'):require_running(state.time)
    def _settlement_engine(self):return ManagementSettlement(self)
    def create(self,state):
        return super().create(replace(state,domains={**state.domains,'sect_management':state.domains.get('sect_management',management.initial(self.registry))}))
    def act(self,save_id,body):
        if isinstance(body,dict) and isinstance(body.get('command'),dict) and body['command'].get('name') in COMMANDS:
            envelope(save_id,body,'command');c=body['command']
            if set(c)!={'name','version','payload'} or type(c['payload']) is not dict or type(c['version']) is not int:raise SliceRequestError('invalid sect service command')
            return self.execute(Command(save_id,body['generation'],body['expected_revision'],body['request_id'],c['name'],c['payload'],c['version']))
        return super().act(save_id,body)
    def start_candidate(self,state,building_id,recipe_id,policy_row=None):
        candidate=super().start_candidate(state,building_id,recipe_id,policy_row)
        supply=state.domains['sect_management']['supply']
        if supply['enabled'] and supply['effect_until_ms']>state.time['sim_time_ms']:
            p=thaw_json(candidate.domains['production']);j=p['jobs'][building_id]
            j['work_rate_milli']=j['work_rate_milli']*(10000+management.config(self.registry)['meal_bonus_bps'])//10000
            j['due_ms']=j['started_ms']+(jobs.duration(j,self.registry)*1000+j['work_rate_milli']-1)//j['work_rate_milli']
            candidate=replace(candidate,domains={**candidate.domains,'production':p})
        return candidate
    def execute(self,q):
        if not isinstance(q,Command):raise ValidationError('Command required')
        if q.name not in COMMANDS:return super().execute(q)
        with self.store.transaction():
            original=self.query(q.save_id)
            if q.generation!=original.generation:raise ConflictError('存档已换代，请更新')
            record=self.store.receipt(q.save_id,q.generation,q.request_id)
            if record:
                if record.kind!='command' or record.intent!=q.digest():raise ConflictError('重复请求内容不一致')
                return self.foundation._decode_receipt(record)
            if q.name=='offline_report_ack':
                if q.expected_revision!=original.revision or original.time['pending']:raise ConflictError('请先完成续算并更新报告')
                if q.version!=1 or set(q.payload)!={'report_id'}:raise ValidationError('exact report acknowledgement required')
                candidate=reports.acknowledge(original,q.payload['report_id'])
                candidate=replace(candidate,revision=original.revision+1 if candidate!=original else original.revision)
                self.foundation.validate_state(candidate)
                receipt=Receipt(q.request_id,candidate.revision,{'operation':q.name,'report_id':q.payload['report_id']})
                self.store.commit(original,candidate,StoredReceipt(q.save_id,q.generation,q.request_id,q.digest(),candidate.revision,'command',thaw_json(receipt.result)))
                return receipt
            self.require_management_command(original,q.name)
            if q.expected_revision!=original.revision or original.time['pending']:raise ConflictError('状态已变化或正在续算，请更新')
            if q.version!=1:raise ValidationError('未知命令版本')
            state=self.prepare_economy_state(original);p=q.payload;cfg=management.config(self.registry);part=thaw_json(state.domains['sect_management']);details={'operation':q.name};candidate=state
            if q.name=='sect_recruit':
                if set(p) not in ({'group_id','count'},{'count'}):raise ValidationError('请选择招募人数')
                integer(p['count'],'招募人数',1);h=management.housing(state,self.registry)
                if part['recruit'] or p['count']>min(h['available'],cfg['max_recruit_count']):raise ValidationError('招募进行中或住房/宗门名额不足')
                group_id=p.get('group_id',next(iter(sorted(state.domains['disciples']['groups'])),None))
                if type(group_id) is not str or group_id not in state.domains['disciples']['groups']:raise ValidationError('弟子池不存在')
                cost={k:n*p['count'] for k,n in cfg['recruit_cost'].items()};stock,_=operations.consume(state.domains['inventory'],self.registry,cost)
                ic=state.identity['instance_counter']+1;ec=state.identity['event_counter']+1
                part['recruit']={'order_id':f'{state.save_id}:{state.generation}:i:{ic}','event_id':f'{state.save_id}:{state.generation}:e:{ec}','group_id':group_id,'count':p['count'],'started_ms':state.time['sim_time_ms'],'due_ms':state.time['sim_time_ms']+cfg['recruit_duration_ms']*p['count'],'ready':False}
                candidate=replace(state,identity={**state.identity,'instance_counter':ic,'event_counter':ec},domains={**state.domains,'inventory':stock,'sect_management':part});details.update(amounts=cost,order_id=part['recruit']['order_id'])
            elif q.name=='sect_supply':
                if set(p)!={'enabled','reserve'} or type(p['enabled']) is not bool:raise ValidationError('请选择供给开关与保留量')
                integer(p['reserve'],'口粮保留量');part['supply']['enabled']=p['enabled'];part['supply']['reserve']=p['reserve']
                if not p['enabled']:part['supply'].update(wake=None,tick_ready=False,effect_until_ms=0)
                candidate=replace(state,domains={**state.domains,'sect_management':part});candidate=self.engine.meals(candidate)
            elif q.name=='sect_facility_build':
                if set(p)!={'building_kind'} or p['building_kind'] not in ('pasture','spring'):raise ValidationError('此生产设施尚未开放建设')
                kind=p['building_kind']
                if any(r['definition_id']==kind for r in state.domains['sect']['buildings'].values()):raise ValidationError('设施已经存在')
                quote=self.facility_quote(state,kind)
                if quote['blocking_reasons']:raise ValidationError(quote['blocking_reasons'][0])
                cost=quote['cost'];stock,_=operations.consume(state.domains['inventory'],self.registry,cost)
                n=state.identity['instance_counter']+1;sect=thaw_json(state.domains['sect']);bid=f'{state.save_id}:{state.generation}:i:{n}';sect['buildings'][bid]={'definition_id':kind,'level':1,'construction_target':None}
                candidate=replace(state,identity={**state.identity,'instance_counter':n},domains={**state.domains,'inventory':stock,'sect':sect});details.update(building_id=bid,amounts=cost)
            elif q.name in ('market_buy','sect_stone_buy'):
                coins=market.quote(state,self.registry,p,buy=True)
                if q.name=='sect_stone_buy' and p['resource_id'] not in cfg['stone_trade_prices']:raise ValidationError('请选择当日正式灵石商品')
                cost={'coins':coins}
                stock,_=operations.consume(state.domains['inventory'],self.registry,cost)
                from src.application.sect_economy import reserved
                from src.systems.inventory import holdings
                capacity=self._capacity(state)-reserved(state,self.registry)
                if holdings.stock_size(stock,self.registry)+p['quantity']>capacity:raise ValidationError('仓库空间不足，交易未扣费')
                stock,_=operations.grant(stock,self.registry,{p['resource_id']:p['quantity']},capacity=capacity)
                ledger=commerce.today(state);ledger['purchases'][p['resource_id']]=ledger['purchases'].get(p['resource_id'],0)+p['quantity'];part['commerce']=ledger
                candidate=replace(state,domains={**state.domains,'inventory':stock,'sect_management':part});details.update(resource_id=p['resource_id'],quantity=p['quantity'],amounts=cost,market_day=p['market_day'],price_milli=p['price_milli'])
            elif q.name in ('material_sell','material_reserve'):
                fields={'resource_id','quantity'} if q.name=='material_reserve' else {'resource_id','quantity','market_day','price_milli'}
                if set(p)!=fields or type(p['resource_id']) is not str or p['resource_id'] not in market_settings(self.registry)['items']:raise ValidationError('请选择正式材料并刷新当日报价')
                integer(p['quantity'],'材料数量');reserves=part['material_reserves']
                if q.name=='material_reserve':
                    part['material_reserves']={**reserves,p['resource_id']:p['quantity']};candidate=replace(state,domains={**state.domains,'sect_management':part})
                else:
                    if p['quantity']<1 or state.domains['inventory']['holdings'].get(p['resource_id'],0)-p['quantity']<reserves.get(p['resource_id'],0):raise ValidationError('材料不足或触及库存保留量')
                    coins=market.quote(state,self.registry,p,buy=False)
                    stock,_=operations.consume(state.domains['inventory'],self.registry,{p['resource_id']:p['quantity']})
                    stock,_=operations.grant(stock,self.registry,{'coins':coins},capacity=self._capacity(state));candidate=replace(state,domains={**state.domains,'inventory':stock});details.update(coins=coins,quantity=p['quantity'],resource_id=p['resource_id'])
            elif q.name in commerce_app.COMMANDS:
                from src.application.sect_economy import reserved
                candidate,details=commerce_app.transition(state,self.registry,q.name,p,self._capacity(state)-reserved(state,self.registry))
            else:
                if set(p)!={'instance_id'} or type(p['instance_id']) is not str:raise ValidationError('请选择装备实例')
                if state.domains['dungeon']['auto']['enabled'] or (state.domains.get('combat',{}).get('battle') or {}).get('status') in ('ACTIVE','PLAYER_WIN'):raise ValidationError('请先停止挂机并结束/领取当前战斗')
                row=items.get(equip.equipment(state),p['instance_id']);n=row.get('enhancement',{}).get('level',0)+1
                quote=self.enhance_quote(state,p['instance_id'])
                if quote['blocking_reasons']:raise ValidationError(quote['blocking_reasons'][0])
                stock,_=operations.consume(state.domains['inventory'],self.registry,quote['cost']);e=thaw_json(equip.equipment(state));e['instances'][p['instance_id']]['enhancement']={'level':n,'bonus_bps':n*cfg['enhancement_bonus_bps_per_level'],'version':'sect-enhance-v1'}
                candidate=replace(state,domains={**state.domains,'inventory':stock,'equipment':e});details.update(instance_id=p['instance_id'],level=n,amounts=quote['cost'])
            candidate=self.engine.wake(candidate);candidate=replace(candidate,revision=original.revision+1 if candidate!=original else original.revision)
            self.foundation.validate_state(candidate);receipt=Receipt(q.request_id,candidate.revision,details)
            self.store.commit(original,candidate,StoredReceipt(q.save_id,q.generation,q.request_id,q.digest(),candidate.revision,'command',thaw_json(receipt.result)))
            return receipt
    def _capacity(self,state):
        from src.application.sect import capacity_source
        return capacity_source(state,self.registry)['effective']
    def facility_quote(self,state,kind):
        from src.application.cultivation import partition
        from src.systems.cultivation import growth
        cost={**management.config(self.registry)['upgrade_costs'][kind],**management.config(self.registry)['building_stone_costs']['1'],**management.config(self.registry)['upgrade_additional_costs']['1']};exists=any(r['definition_id']==kind for r in state.domains['sect']['buildings'].values());reasons=[]
        d=buildings.definition(self.registry,kind)
        if exists:reasons.append('设施已经存在')
        if not rules.can_build(self.registry,kind,cleared_floor=state.domains['dungeon']['cleared_floor'],realm=growth.realm(self.registry,partition(state)['current_realm']).index):reasons.append(f'建设需要荆棘古道通关{d.unlock_floor}层及相应境界')
        if state.time['pending']:reasons.append('宗门进度正在续算')
        if any(state.domains['inventory']['holdings'].get(k,0)<n for k,n in cost.items()):reasons.append('建设材料不足')
        return {'kind':kind,'exists':exists,'cost':cost,'can_build':not reasons,'blocking_reasons':reasons}
    def enhance_quote(self,state,identity):
        cfg=management.config(self.registry);row=items.get(equip.equipment(state),identity);level=row.get('enhancement',{}).get('level',0);next_level=level+1;reasons=[]
        rank=rules.development(state.domains['sect'],self.registry,state.domains['dungeon']['cleared_floor'])['level'];forge=max((r['level'] for r in state.domains['sect']['buildings'].values() if r['definition_id']=='forge'),default=0)
        if next_level>cfg['enhancement_max_level']:reasons.append('已达到当前强化上限')
        if rank<cfg['enhancement_min_sect_level'] or forge<max(cfg['enhancement_min_forge_level'],next_level):reasons.append('宗门等级或炼器阁等级不足')
        from src.application.item_retirement import RETIRED_ITEMS
        if items.unknown(row,self.registry) or row['definition_id'] in RETIRED_ITEMS:reasons.append('此装备属性尚不能安全强化')
        if state.time['pending']:reasons.append('宗门进度正在续算')
        if state.domains['dungeon']['auto']['enabled'] or (state.domains.get('combat',{}).get('battle') or {}).get('status') in ('ACTIVE','PLAYER_WIN'):reasons.append('请先停止挂机并结束/领取当前战斗')
        cost=dict(cfg['enhancement_costs'].get(str(next_level),{}))
        if any(state.domains['inventory']['holdings'].get(k,0)<n for k,n in cost.items()):reasons.append('强化材料不足')
        return {'level':level,'next_level':next_level,'max_level':cfg['enhancement_max_level'],'cost':cost,'blocking_reasons':reasons,'can_enhance':not reasons}
    def project_world(self,state):
        v=thaw_json(super().project_world(state));v['offline_reports']=thaw_json(state.domains.get(reports.DOMAIN,reports.empty())['unread']);v['offline_report_names']=reports.names(state,self.registry);v['latest_battle_report']=thaw_json(reports.latest_battle(state));cfg=management.config(self.registry);h=management.housing(state,self.registry);part=state.domains['sect_management'];supply=part['supply'];now=state.time['sim_time_ms'];running=state.time['pending'] is None
        # A registered building resource with no holdings is available with quantity 0.
        # This is a read model only; never insert zero holdings into the save.
        for rid in set(cfg['upgrade_cost_per_level'])|{r['resource_id'] for r in cfg['building_stone_stages']}|{r['resource_id'] for r in cfg['upgrade_material_stages']}:
            v['inventory'].setdefault(rid,{'name':self.registry.lookup(DefinitionKey('resources',rid)).display_name,'quantity':state.domains['inventory']['holdings'].get(rid,0)})
        for row in v['buildings'].values():
            if row['definition_id'] in cfg['facility_display_names']:row['name']=cfg['facility_display_names'][row['definition_id']]
        for group in v['disciples']['groups']:
            group['name']='宗门弟子'
            for assignment in group['assignments']:assignment['name']=v['buildings'][assignment['building_id']]['name']
        groups=[{'group_id':gid,'name':'宗门弟子','count':row['count']} for gid,row in state.domains['disciples']['groups'].items()]
        h.update(recruit_remaining_seconds=max(0,part['recruit']['due_ms']-now)//1000 if part['recruit'] else 0,groups=groups,recruit=thaw_json(part['recruit']),recruit_cost=dict(cfg['recruit_cost']),recruit_duration_seconds=cfg['recruit_duration_ms']//1000,max_recruit_count=cfg['max_recruit_count'],can_recruit=running and part['recruit'] is None and h['available']>0)
        supply_view={**thaw_json(supply),'active':supply['enabled'] and supply['effect_until_ms']>now,'remaining_seconds':max(0,supply['effect_until_ms']-now)//1000,'bonus_percent':cfg['meal_bonus_bps']/100,'food':state.domains['inventory']['holdings'].get('food',0),'per_period':h['people']*cfg['meal_food_per_person'],'period_seconds':cfg['meal_period_ms']//1000}
        matters=[]
        if not h['available']:matters.append({'id':'housing','name':'住房或宗门名额不足','detail':'扩建弟子居或查看宗务殿下一等级条件；已有弟子保留。','route':'#building/house'})
        if not supply_view['active']:matters.append({'id':'supply','name':'灵膳加成未启用或口粮不足','detail':f"每次需口粮 {supply_view['per_period']}，库存保留 {supply_view['reserve']}。",'route':'#building/kitchen'})
        if h['idle']:matters.append({'id':'workforce','name':f"{h['idle']}名弟子待命，可安排岗位",'detail':'安排岗位不收费；正在生产的岗位占用持续至交付。','route':'#building/house'})
        if not any(row.get('assigned_count',0) for row in v['buildings'].values() if row['definition_id']=='alchemy'):matters.append({'id':'alchemy-workers','name':'丹鼎阁无人，可安排弟子','detail':'使用现有共享弟子岗位，不自动转移在产人员。','route':'#building/alchemy'})
        if part['recruit']:matters.append({'id':'recruit','name':'山门招募进行中','detail':f"{part['recruit']['count']}个住房名额已预留。",'route':'#building/gate'})
        materials=[];reserves=part['material_reserves']
        market_day=market.day(state)
        for rid in market_settings(self.registry)['items']:
            n=state.domains['inventory']['holdings'].get(rid,0)
            price=market.price(self.registry,state.save_id,market_day,rid)
            if n:materials.append({'resource_id':rid,'name':self.registry.lookup(DefinitionKey('resources',rid)).display_name,'quantity':n,'price':price['sell_price_milli']/1000,'price_milli':price['sell_price_milli'],'market_day':market_day,'variation_percent':price['variation_permille']/10,'reserve':reserves.get(rid,0),'can_sell':running and (n-reserves.get(rid,0))*price['sell_price_milli']>=1000})
        for row in materials:
            cap=max(cfg['material_retention_cap'],row['reserve'])
            if row['quantity']>cap:matters.append({'id':row['resource_id'],'name':row['name']+'超过保留上限','detail':f"可处理 {row['quantity']-cap} 份；每份 {row['price']} 灵钱。",'route':'#building/market'})
        for rid,row in v['inventory'].items():
            if rid in cfg['sale_prices']:
                row.update(source_label='主角副本掉落或装备分解',use_label='打造、丹药、强化或材料收购；保留量保护库存')
            elif rid in ('grain','food','egg','fish','wood','stone','ore','ingot','herb','spirit_iron_ore','spirit_iron_ingot','spirit_plank','refined_iron_ingot','ordinary_wood','spring_water'):
                row.update(source_label='宗门生产与加工',use_label='宗门建设、日常供给或加工辅料')
        for rid,row in v.get('holdings',{}).items():
            if rid in v['inventory']:
                for key in ('source_label','use_label'):
                    if key in v['inventory'][rid]:row[key]=v['inventory'][rid][key]
        v['sect_services']={'housing':h,'supply':supply_view,'matters':matters,'materials':materials,'log':thaw_json(part['log']),'enhancements':{identity:self.enhance_quote(state,identity) for identity in equip.equipment(state)['instances']},'facilities':[self.facility_quote(state,k) for k in ('pasture','spring')]}
        from src.application.sect_economy import reserved
        from src.systems.inventory import holdings
        free=max(0,self._capacity(state)-reserved(state,self.registry)-holdings.stock_size(state.domains['inventory'],self.registry))
        offers=[]
        for rid in market.current_offers(state,self.registry):
            price=market.price(self.registry,state.save_id,market_day,rid);cost=price['buy_price_milli']
            offers.append({'resource_id':rid,'name':self.registry.lookup(DefinitionKey('resources',rid)).display_name,'shop_level':market_settings(self.registry)['items'][rid]['level'],'boss_only':market_settings(self.registry)['items'][rid]['boss_only'],'remaining_stock':market.stock_remaining(state,self.registry,rid),'price':cost/1000,'price_milli':cost,'market_day':market_day,'variation_percent':price['variation_permille']/10,'quantity':state.domains['inventory']['holdings'].get(rid,0),'max_quantity':min(market_settings(self.registry)['max_purchase_quantity'],market.stock_remaining(state,self.registry,rid),state.domains['inventory']['holdings'].get('coins',0)*1000//cost,free) if running else 0})
        v['sect_services']['market']={'day':market_day,'display_day':market_day+1,'remaining_seconds':(state.time['day_length_ms']-now%state.time['day_length_ms']+999)//1000,'day_seconds':state.time['day_length_ms']//1000,'offers':offers}
        orders=commerce.orders(state,self.registry)
        for row in orders:
            row['name']=self.registry.lookup(DefinitionKey('resources',row['resource_id'])).display_name
            row['can_deliver']=running and not row['complete'] and state.domains['inventory']['holdings'].get(row['resource_id'],0)-reserves.get(row['resource_id'],0)>=row['quantity']
        auctions=commerce.public_auctions(state,self.registry)
        for rows in (auctions['offers'],auctions['claims'],auctions['consignments'],auctions['history']):
            for row in rows:row['name']=self.registry.lookup(DefinitionKey('resources',row['resource_id'])).display_name
        auctions['eligible']=[{'resource_id':rid,'name':self.registry.lookup(DefinitionKey('resources',rid)).display_name,'quantity':state.domains['inventory']['holdings'].get(rid,0),'reserve':market_settings(self.registry)['items'][rid]['value_coins']*9//10,'can_consign':running and not paused(state.time) and state.domains['inventory']['holdings'].get(rid,0)>reserves.get(rid,0)} for rid in market.eligible(state,self.registry) if market_settings(self.registry)['items'][rid]['boss_only'] or market_settings(self.registry)['items'][rid]['level']>=4]
        v['sect_services']['orders']=orders;v['sect_services']['auctions']=auctions
        v['sect_services']['stone_trades']=[row for row in offers if row['resource_id'] in cfg['stone_trade_prices']]
        v['sect_services']['building_stone_stages']=[{**thaw_json(row),'name':self.registry.lookup(DefinitionKey('resources',row['resource_id'])).display_name} for row in cfg['building_stone_stages']]
        for rid in (row['resource_id'] for row in cfg['building_stone_stages']):
            v['inventory'][rid].update(source_label='后山开采' if rid=='spirit_stone_low' else '万宝楼灵钱交易',use_label='对应阶段的宗门建筑建设与升级')
        return freeze_json(v)
    def view(self,save_id):
        v=thaw_json(super().view(save_id))
        for row in v['equipment']['instances']:row['enhancement']=v['sect_services']['enhancements'][row['instance_id']]
        return freeze_json(v)
    def project_economy(self,state):
        v=super().project_economy(state);p=state.domains['sect_management']
        if p['recruit'] or p['supply']['wake']:v['needs_poll']=v['needs_settlement']=True
        return v

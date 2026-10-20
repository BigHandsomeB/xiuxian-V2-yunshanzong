"""Four-building commands over the existing SQLite/Work/Inventory authority."""
from dataclasses import replace
from hashlib import sha256
from src.application.sect_management import ManagementApplication
from src.application.dungeons import DungeonPersistence
from src.application.ecology_settlement import EcologySettlement
from src.application.memory import Command, Receipt
from src.application.danding import envelope, SliceRequestError
from src.application.work import references
from src.application import sect
from src.core.save.codec import StoredReceipt
from src.core.state.envelope import thaw_json, freeze_json
from src.core.time.world import require_running, paused
from src.core.validation import ValidationError, ConflictError, integer
from src.data.registry import DefinitionKey
from src.data.economy.ecology import settings, lookup
from src.systems.sect import ecology, nutrition, buildings
from src.systems.resources import jobs
from src.systems.disciples import work
from src.systems.economy import policy
from src.systems.inventory import operations, holdings
from src.application.ecology_views import EcologyViews
from src.application import garden as garden_app
from src.application import habitats as habitat_app
from src.systems.sect import habitats
from src.systems.sect import garden

from src.systems.sect import activities
from src.application import sect_activities, exploration as exploration_app, attribute_trials as trial_app
from src.systems.cultivation import attribute_trials as trial_rules
from src.systems.sect import exploration
from src.application.sect_economy import reserved
from src.systems.cultivation import techniques
from src.application.cultivation import partition
from src.systems.artifacts import artifacts
from src.data.artifacts.definitions import settings as artifact_settings
from src.application import artifacts as artifact_app

COMMANDS = (*habitats.COMMANDS, *garden.COMMANDS, *trial_rules.COMMANDS, *exploration.COMMANDS, *artifacts.COMMANDS, *activities.COMMANDS, *techniques.COMMANDS, 'ecology_buy', 'ecology_collect', 'ecology_supply', 'ecology_meal')


def validate_state(state, registry):
    trial_app.validate_state(state,registry)
    if 'exploration' in state.domains['sect_management']:
        exploration.validate_state(state,registry)
    if artifact_settings(registry):
        artifact_app.validate_state(state,registry)
    part = state.domains[ecology.DOMAIN]
    ecology.validate(part, registry)
    garden_app.validate_state(state, registry)
    actual = state.domains['sect']['buildings']
    identities = set(actual) | set(state.domains['disciples']['groups'])
    identities |= {row['job_id'] for row in state.domains['production']['jobs'].values()}
    identities |= set(state.domains.get('equipment', {}).get('instances', {}))
    battle = state.domains.get('combat', {}).get('battle')
    if battle:
        identities.add(battle['battle_id'])
    for identity, row in part['batches'].items():
        pieces = identity.split(':')
        try:
            generation, counter = int(pieces[1]), int(pieces[3])
        except (IndexError, ValueError) as exc:
            raise ValidationError('invalid husbandry identity') from exc
        if len(pieces) != 4 or pieces[0] != state.save_id or pieces[2] != 'i' or not (
            1 <= generation <= state.generation and 1 <= counter <= state.identity['instance_counter']
        ) or str(generation) != pieces[1] or str(counter) != pieces[3] or identity in identities:
            raise ValidationError('husbandry identity outside allocated namespace')
        identities.add(identity)
        species = lookup(registry, 'species', row['species_id'])
        building = actual.get(row['building_id'])
        if not building or building['definition_id'] != species['building_kind'] or building['level'] < 1:
            raise ValidationError('husbandry building reference invalid')
        total = ecology.total_work(row, registry, state.time['day_length_ms'])
        if row['progress_milli'] > ecology.credit_limit(row, registry, state.time['day_length_ms']) or row['progress_milli'] > total:
            raise ValidationError('husbandry work must be funded by paid feed')
        if row['stage'] == 'READY' and row['progress_milli'] != total:
            raise ValidationError('husbandry output not ready')
        if row['rate_milli'] > 1500 or row['cycle_rate_milli'] > 1500:
            raise ValidationError('husbandry rate exceeds confirmed limit')
        if row['extra_bps'] > max(meal['extra_bps'] for meal in settings(registry)['meals']
                                  if nutrition.matching(meal, species['building_kind'])):
            raise ValidationError('husbandry probability exceeds meal limit')
    for bid in {row['building_id'] for row in part['batches'].values()}:
        if ecology.occupied(part, registry, bid) > ecology.capacity(state, registry, bid):
            raise ValidationError('兽栏或水池容量不足')
    for bid in {row['building_id'] for row in part['batches'].values()}:
        habitats.layout(part, registry, bid, ecology.capacity(state, registry, bid))
    for bid, installed in part['facilities'].items():
        if bid not in actual:
            raise ValidationError('facility building missing')
        for fid, count in installed.items():
            definition = lookup(registry, 'facilities', fid)
            if definition['building_kind'] != actual[bid]['definition_id'] or count > (actual[bid]['level'] if definition['per_level'] else 1):
                raise ValidationError('facility count/target invalid')
    for bid, meal in part['meals'].items():
        if bid not in actual or not nutrition.matching(lookup(registry, 'meals', meal['meal_id']), actual[bid]['definition_id']):
            raise ValidationError('岗位与灵膳用途不匹配')
    for key in ('served', 'hungry', 'people_snapshot'):
        if not set(part['supply'][key]) <= set(state.domains['disciples']['groups']):
            raise ValidationError('nutrition references unknown workforce')
        if any(count > state.domains['disciples']['groups'][gid]['count']
               for gid, count in part['supply'][key].items()):
            raise ValidationError('nutrition count exceeds workforce')
    current_jobs = {row['job_id'] for row in state.domains['production']['jobs'].values()}
    if not set(part['job_effects']) <= current_jobs:
        raise ValidationError('orphan production meal snapshot')
    for bid, job in state.domains['production']['jobs'].items():
        effect = part['job_effects'].get(job['job_id'])
        if not effect:
            continue
        meal = lookup(registry, 'meals', effect['meal_id']) if effect['meal_id'] else None
        if meal and (meal['basic'] or not nutrition.matching(meal, actual[bid]['definition_id'])):
            raise ValidationError('production meal snapshot scope invalid')
        if any(effect[key] > (meal[key] if meal else 0) for key in ('extra_bps', 'discovery_bps')):
            raise ValidationError('production meal snapshot exceeds recipe effect')
    for gid, count in part['supply']['served'].items():
        if count > part['supply']['people_snapshot'].get(gid, 0):
            raise ValidationError('daily portions exceed workforce snapshot')
    wake = part['wake']
    if wake:
        event_ids = set()
        for identity in (wake['event_id'], wake['next_event_id']):
            pieces = identity.split(':') if type(identity) is str else []
            if len(pieces) != 4 or pieces[0] != state.save_id or pieces[2] != 'e':
                raise ValidationError('ecology event identity invalid')
            try:
                generation, counter = int(pieces[1]), int(pieces[3])
            except ValueError as exc:
                raise ValidationError('ecology event identity invalid') from exc
            if not (1 <= generation <= state.generation and 1 <= counter <= state.identity['event_counter']) or str(generation) != pieces[1] or str(counter) != pieces[3] or identity in event_ids:
                raise ValidationError('ecology event outside allocated namespace')
            event_ids.add(identity)
    if part['tick_ready']:
        raise ValidationError('ecology event must be dispatched before persistence')
    if state.domains['sect_management']['supply']['enabled']:
        raise ValidationError('旧供养方式已退出，请使用灵膳供应')
    return state


class EcologyPersistence(DungeonPersistence):
    def _validate(self, state):
        return validate_state(super()._validate(state), self.registry)


class EcologyApplication(EcologyViews, ManagementApplication):
    def _settlement_engine(self):
        return EcologySettlement(self)

    def _application(self, specs):
        validators = {**sect.validators(self.registry),
                      'production': lambda part: jobs.validate(part, self.registry),
                      'disciples': lambda part: work.validate(part, self.registry),
                      'automation': lambda part: policy.validate(part, self.registry),
                      ecology.DOMAIN: lambda part: ecology.validate(part, self.registry)}
        return EcologyPersistence(self.store, self.registry, specs,
                                  references=lambda state: references(state, self.registry),
                                  validators=validators, settlement_engine=self.engine, clock=self.clock)

    def validate_ecology(self, state):
        return validate_state(state, self.registry)

    def create(self, state):
        if artifact_settings(self.registry):
            state=replace(state,domains={**state.domains,artifacts.DOMAIN:state.domains.get(artifacts.DOMAIN,artifacts.initial())})
        part = state.domains.get(ecology.DOMAIN, ecology.initial())
        grown=techniques.migrate(partition(state),self.registry)
        return super().create(replace(state, domains={**state.domains, ecology.DOMAIN: part,'cultivation':grown}))

    def act(self, save_id, body):
        if isinstance(body, dict) and isinstance(body.get('command'), dict) and body['command'].get('name') in COMMANDS:
            envelope(save_id, body, 'command')
            command = body['command']
            if set(command) != {'name', 'version', 'payload'} or type(command['payload']) is not dict or type(command['version']) is not int:
                raise SliceRequestError('invalid ecology command')
            return self.execute(Command(save_id, body['generation'], body['expected_revision'],
                                        body['request_id'], command['name'], command['payload'], command['version']))
        return super().act(save_id, body)

    def prepare_economy_state(self,state):
        state=super().prepare_economy_state(state)
        grown=techniques.migrate(partition(state),self.registry)
        if grown!=partition(state):state=replace(state,domains={**state.domains,'cultivation':grown})
        quantity=state.domains['inventory']['holdings'].get('food',0)
        if not quantity:return state
        stock=thaw_json(state.domains['inventory']);stock['holdings'].pop('food')
        replacement=settings(self.registry)['legacy_food_replacement']
        stock['holdings'][replacement]=stock['holdings'].get(replacement,0)+quantity
        return replace(state,domains={**state.domains,'inventory':stock})

    def settle_combat_candidate(self,state):
        return super().settle_combat_candidate(self.prepare_economy_state(state))

    def reward_amounts(self,b):
        amounts=super().reward_amounts(b)
        from src.systems.dungeons.progress import floor_of
        from src.data.dungeons.expeditions import owner
        from src.systems.dungeons.progress import definition
        c=techniques.config(self.registry);rules=c.get('sources',{}) if c else {}
        floor=floor_of(self.registry,b['encounter_id']);did=owner(self.registry,b['encounter_id'])
        if rules and floor==rules['boss_floor'] and did and definition(self.registry,did).tiers[floor-1]=='boss':amounts={**amounts,rules['page_resource_id']:rules['pages_per_boss']}
        return amounts

    def stone_reward_quote(self,state,b):
        from src.systems.dungeons.progress import floor_of
        from src.data.dungeons.expeditions import owner
        part=partition(state).get('techniques',{});latest=part.get('latest_stone_reward',{})
        if latest.get('battle_id')==b['battle_id']:return thaw_json(latest['amounts'])
        if b.get('status')=='SETTLED':return {}
        rules=techniques.config(self.registry)['sources'];out={}
        if floor_of(self.registry,b['encounter_id'])!=rules['boss_floor']:return out
        if (part.get('boss_wins',0)+1)%rules['supreme_boss_interval']==0:out['spirit_stone_supreme']=rules['supreme_per_reward']
        did=owner(self.registry,b['encounter_id'])
        if did==rules['immortal_first_dungeon'] and did not in part.get('stone_first_claimed',()):out['spirit_stone_immortal']=rules['immortal_first_count']
        return out

    def reward_grant(self,state,b):
        amounts,candidate=super().reward_grant(state,b)
        return {**amounts,**self.stone_reward_quote(state,b)},candidate

    def combat_reward_candidate(self,state,candidate):
        candidate=super().combat_reward_candidate(state,candidate)
        from src.systems.dungeons.progress import floor_of
        from src.data.dungeons.expeditions import owner
        b=candidate.domains['combat']['battle'];rules=techniques.config(self.registry)['sources']
        if floor_of(self.registry,b['encounter_id'])!=rules['boss_floor']:return candidate
        p=thaw_json(partition(candidate));part=p['techniques'];part['boss_wins']=part.get('boss_wins',0)+1
        extra=self.stone_reward_quote(state,state.domains['combat']['battle']);part['latest_stone_reward']={'battle_id':b['battle_id'],'amounts':extra}
        did=owner(self.registry,b['encounter_id'])
        if did==rules['immortal_first_dungeon']:part['stone_first_claimed']=list(set(part.get('stone_first_claimed',()))|{did})
        candidate=replace(candidate,domains={**candidate.domains,'cultivation':p})
        activity=activities.issue_chest(state,candidate,self.registry,b)
        if activity is not None:
            management=thaw_json(candidate.domains['sect_management']);management['activities']=activity
            candidate=replace(candidate,domains={**candidate.domains,'sect_management':management})
        if extra:
            from src.application.offline_reports import observe_battle_reward
            candidate=observe_battle_reward(candidate,extra,{},0,0)
        return candidate

    def project_combat(self,state):
        view=thaw_json(super().project_combat(state));b=state.domains.get('combat',{}).get('battle')
        if b and view.get('battle_id')==b['battle_id'] and b['status'] in ('PLAYER_WIN','SETTLED'):
            settled_new=partition(state).get('techniques',{}).get('latest_stone_reward',{}).get('battle_id')==b['battle_id']
            count=self.reward_amounts(b).get('manual_page',0) if b['status']=='PLAYER_WIN' or settled_new else 0
            if count:view['reward'].append({'resource_id':'manual_page','name':'功法残页','quantity':count})
            for key,n in self.stone_reward_quote(state,b).items():view['reward'].append({'resource_id':key,'name':self.registry.lookup(DefinitionKey('resources',key)).display_name,'quantity':n})
            quote=activities.chest_quote(state,self.registry,b) if b['status']=='PLAYER_WIN' else None
            pending=next(((did,r) for did,r in activities.ledger(state)['chests'].items() if r['battle_id']==b['battle_id']),None)
            if quote:view['choice_chest']={**quote,'state':'AWAITING_REWARD'}
            elif pending:
                did,row=pending
                from src.systems.dungeons.progress import definition
                view['choice_chest']={'chest_id':did,'name':definition(self.registry,did).display_name+'首通宝箱','tier':row['tier'],'state':'READY_IN_WAREHOUSE'}
        return freeze_json(view)

    def project_economy(self,state):
        view=thaw_json(super().project_economy(state))
        if trial_rules.running(partition(state)):view['needs_poll']=view['needs_settlement']=True
        return freeze_json(view)

    def require_manual_combat(self,state):
        if trial_rules.running(partition(state)):raise ConflictError('请先停止属性试炼，再进入冒险战斗。')
        return super().require_manual_combat(state)

    def require_management_command(self,state,name):
        require_running(state.time)

    def execute(self, request):
        if not isinstance(request, Command):
            raise ValidationError('Command required')
        if request.name == 'sect_supply':
            with self.store.transaction():
                state = self.query(request.save_id)
                if request.generation != state.generation:
                    raise ConflictError('存档已换代，请刷新')
                saved = self.store.receipt(state.save_id, state.generation, request.request_id)
                if saved:
                    if saved.kind != 'command' or saved.intent != request.digest() or saved.committed_revision > state.revision:
                        raise ConflictError('重复请求内容不一致')
                    return self.foundation._decode_receipt(saved)
            raise ValidationError('旧供养方式已退出，请使用灵膳供应')
        if request.name not in COMMANDS:
            return super().execute(request)
        with self.store.transaction():
            original = self.query(request.save_id)
            if request.generation != original.generation:
                raise ConflictError('存档已换代，请刷新')
            saved = self.store.receipt(original.save_id, original.generation, request.request_id)
            if saved:
                if saved.kind != 'command' or saved.intent != request.digest() or saved.committed_revision > original.revision:
                    raise ConflictError('重复请求内容不一致')
                return self.foundation._decode_receipt(saved)
            if request.name not in (*activities.COMMANDS,'attribute_trial_stop'):require_running(original.time)
            if request.expected_revision != original.revision or original.time['pending']:
                raise ConflictError('请先完成续算并刷新状态')
            if request.version != 1:
                raise ValidationError('未知命令版本')
            candidate, details = self.transition(self.prepare_economy_state(original), request.name, request.payload)
            candidate = self.engine.wake(candidate)
            candidate = replace(candidate, revision=original.revision + 1 if candidate != original else original.revision)
            self.foundation.validate_state(candidate)
            receipt = Receipt(request.request_id, candidate.revision, details)
            self.store.commit(original, candidate, StoredReceipt(
                original.save_id, original.generation, request.request_id, request.digest(),
                candidate.revision, 'command', thaw_json(receipt.result)))
            return receipt

    def transition(self, state, name, payload):
        if name in habitats.COMMANDS:return habitat_app.transition(self,state,name,payload)
        if name in garden.COMMANDS:return garden_app.transition(self,state,name,payload)
        if name in trial_rules.COMMANDS:return trial_app.transition(self,state,name,payload)
        if trial_rules.running(partition(state)) and name in ('technique_equip','technique_unequip','artifact_equip','artifact_unequip','artifact_feed','artifact_enhance'):raise ConflictError('请先停止属性试炼再调整功法或法宝。')
        if name in exploration.COMMANDS:
            return exploration_app.transition(state,self.registry,name,payload,self._capacity(state)-reserved(state,self.registry))
        if name in artifacts.COMMANDS:
            return artifact_app.transition(state,self.registry,name,payload)
        if name in activities.COMMANDS:
            return sect_activities.transition(state,self.registry,name,payload,self._capacity(state)-reserved(state,self.registry))
        if name in techniques.COMMANDS:
            battle=state.domains.get('combat',{}).get('battle') or {}
            if name in ('technique_equip','technique_unequip') and (state.domains['dungeon']['auto']['enabled'] or battle.get('status') in ('ACTIVE','PLAYER_WIN')):raise ValidationError('请先停止挂机并结束或领取当前战斗，再更换功法。')
            stock=state.domains['inventory'];cost={}
            if name in ('technique_equip','technique_unequip'):grown=techniques.change(partition(state),self.registry,name,payload)
            else:
                from src.systems.dungeons.progress import cleared
                grown,cost=techniques.acquire(partition(state),self.registry,name,payload,stock['holdings'],cleared(state.domains['dungeon'],'thorn_path'))
                stock,_=operations.consume(stock,self.registry,cost) if cost else (stock,{})
            return replace(state,domains={**state.domains,'cultivation':grown,'inventory':stock}),{'operation':name,'cost':cost,**payload}
        part = thaw_json(state.domains[ecology.DOMAIN])
        stock = state.domains['inventory']
        now = state.time['sim_time_ms']
        counters = dict(state.identity)
        details = {'operation': name}
        if name == 'ecology_buy':
            if set(payload) != {'building_id', 'species_id', 'count'}:
                raise ValidationError('请选择品种、设施和数量')
            integer(payload['count'], '购入数量', 1)
            count = payload['count']
            species = lookup(self.registry, 'species', payload['species_id'])
            building = buildings.get_building(state.domains['sect'], self.registry, payload['building_id'])
            if building['definition_id'] != species['building_kind'] or building['level'] < 1:
                raise ValidationError('请先建设对应养殖设施')
            if len(part['batches']) >= settings(self.registry)['limits']['max_batches'] or count > settings(self.registry)['limits']['max_count']:
                raise ValidationError('养殖批次或购入数量超过上限')
            if ecology.occupied(part, self.registry, payload['building_id']) + count * species['slots'] > ecology.capacity(state, self.registry, payload['building_id']):
                raise ValidationError('兽栏或水池容量不足')
            cost = {'coins': count * species['purchase_coins']}
            stock, _ = operations.consume(stock, self.registry, cost)
            counters['instance_counter'] += 1
            identity = f'{state.save_id}:{state.generation}:i:{counters["instance_counter"]}'
            part['batches'][identity] = {
                'species_id': species['id'], 'building_id': payload['building_id'], 'count': count,
                'stage': 'JUVENILE', 'progress_milli': 0, 'feed_paid': 0, 'rate_milli': 0,
                'cycle_rate_milli': 0, 'extra_bps': 0, 'cycle': 0,
                'last_collection_ms': 0, 'reason': '等待照料与饲料'}
            details.update(batch_id=identity, amounts=cost)
        elif name == 'ecology_collect':
            if set(payload) != {'batch_id', 'mode', 'count'} or payload['batch_id'] not in part['batches']:
                raise ValidationError('请选择有效养殖批次')
            row = part['batches'][payload['batch_id']]
            integer(payload['count'], '收获数量', 1)
            count = payload['count']
            if count > row['count'] or row['stage'] == 'JUVENILE':
                raise ValidationError('数量不足或尚未成熟')
            species = lookup(self.registry, 'species', row['species_id'])
            periodic = payload['mode'] == 'periodic'
            if payload['mode'] not in ('periodic', 'harvest') or (periodic and row['stage'] != 'READY'):
                raise ValidationError('此批次尚无可领取周期产物')
            if row['last_collection_ms'] == now:
                raise ValidationError('同一结算窗口不能重复采集或屠宰')
            base = species['periodic_outputs'] if periodic else species['harvest_outputs']
            if not base:
                raise ValidationError('此品种没有该类产物')
            amounts = {rid: n * count for rid, n in base.items()}
            if periodic and self.roll(state, f'{payload["batch_id"]}:{row["cycle"]}', 'animal', row['extra_bps']):
                amounts = {rid: n + base[rid] for rid, n in amounts.items()}
            capacity = self._capacity(state)
            needed = sum(n for rid, n in amounts.items() if holdings.definition(self.registry, rid).warehouse_counted)
            if holdings.stock_size(stock, self.registry) + needed > capacity:
                raise ValidationError('仓库空间不足，个体与产物均已保留')
            stock, result = operations.grant(stock, self.registry, amounts, capacity=capacity)
            if any(result['discarded'].values()):
                raise ValidationError('不能丢弃养殖产物')
            old_count = row['count']
            if periodic:
                renewed = {**row, 'count': count, 'stage': 'MATURE', 'progress_milli': 0,
                           'feed_paid': 0, 'rate_milli': 0, 'cycle_rate_milli': 0,
                           'cycle': row['cycle'] + 1, 'last_collection_ms': now, 'reason': '周期已采集'}
                if count == old_count:
                    part['batches'][payload['batch_id']] = renewed
                else:
                    if len(part['batches']) >= settings(self.registry)['limits']['max_batches']:
                        raise ValidationError('分批收获将超过批次上限，请整批领取')
                    row['count'] -= count
                    row['feed_paid'] = species['feed_quantity'] * row['count']
                    counters['instance_counter'] += 1
                    identity = f'{state.save_id}:{state.generation}:i:{counters["instance_counter"]}'
                    part['batches'][identity] = renewed
            elif count == old_count:
                del part['batches'][payload['batch_id']]
            else:
                row['count'] -= count
                row['feed_paid'] = (row['feed_paid'] * row['count'] + old_count - 1) // old_count
            details.update(amounts=amounts, count=count, mode=payload['mode'])
        elif name == 'ecology_supply':
            if set(payload) != {'enabled', 'target_days'} or type(payload['enabled']) is not bool:
                raise ValidationError('请选择供应开关和储备天数')
            integer(payload['target_days'], '储备天数', 3)
            if payload['target_days'] > 7:
                raise ValidationError('储备天数必须为3至7日')
            supply = part['supply']
            supply.update(enabled=payload['enabled'], target_days=payload['target_days'])
            if payload['enabled'] and not supply['activated']:
                supply.update(activated=True, next_day_ms=(now // state.time['day_length_ms'] + 1) * state.time['day_length_ms'])
        else:
            if set(payload) != {'building_id', 'meal_id', 'enabled'} or type(payload['enabled']) is not bool:
                raise ValidationError('请选择岗位和灵膳')
            bid = payload['building_id']
            building = buildings.get_building(state.domains['sect'], self.registry, bid)
            meal = lookup(self.registry, 'meals', payload['meal_id'])
            if meal['basic'] or not nutrition.matching(meal, building['definition_id']):
                raise ValidationError('灵膳不适合此岗位')
            old = part['meals'].get(bid)
            if old and old['expires_ms'] > now and old['meal_id'] != meal['id']:
                raise ValidationError('当前岗位餐尚未到期，不可叠加或覆盖')
            part['meals'][bid] = {**(old if old and old['meal_id'] == meal['id'] else {
                'covered_count': 0, 'expires_ms': 0}), 'meal_id': meal['id'], 'enabled': payload['enabled']}
        return replace(state, identity=counters, domains={**state.domains, 'inventory': stock, ecology.DOMAIN: part}), details

    def start_candidate(self, state, building_id, recipe_id, policy_row=None):
        definition = jobs.definition(self.registry, recipe_id)
        config = settings(self.registry)
        if definition.building_kind == 'garden' and any(garden.plots(state.domains['ecology'], building_id).values()):
            raise ValidationError('田中已有灵植，请等待收获后再营造或开始整批生产')
        if recipe_id in config['retired_recipes']:
            raise ValidationError('旧配方已退出，请使用灵膳和存栏养殖')
        if recipe_id.startswith('grow_sect_crop_'):
            if work.capability(state.domains['disciples'], self.registry, building_id, recipe_id)['workers'] > ecology.capacity(state, self.registry, building_id):
                raise ValidationError('种植人数超过田块，请减少岗位人数或增设田块')
        if definition.facility_output_id:
            candidate = self.start_facility(state, building_id, definition, policy_row)
        else:
            basic = set(nutrition.basic_ids(self.registry))
            priority = bool(basic & {rid for rid, _ in definition.outputs}) or recipe_id.startswith('grow_')
            if not priority:
                cap = work.capability(state.domains['disciples'], self.registry, building_id, recipe_id)
                for rid, required in nutrition.protected_inputs(state, self.registry).items():
                    consumed = dict(definition.inputs).get(rid, 0) * cap['workers']
                    if consumed and state.domains['inventory']['holdings'].get(rid, 0) - consumed < required:
                        raise ValidationError('基础灵膳原料优先保留，请先补足口粮')
            candidate = super().start_candidate(state, building_id, recipe_id, policy_row)
        effect = nutrition.effects(state, self.registry, building_id)
        production = thaw_json(candidate.domains['production'])
        job = production['jobs'][building_id]
        job['work_rate_milli'] = job['work_rate_milli'] * effect['rate_milli'] // 1000
        job['due_ms'] = job['started_ms'] + (definition.duration_ms * 1000 + job['work_rate_milli'] - 1) // job['work_rate_milli']
        part = thaw_json(candidate.domains[ecology.DOMAIN])
        current = {row['job_id'] for row in production['jobs'].values()}
        part['job_effects'] = {jid: row for jid, row in part['job_effects'].items() if jid in current}
        part['job_effects'][job['job_id']] = {key: effect[key] for key in ('extra_bps', 'discovery_bps', 'meal_id')}
        return replace(candidate, domains={**candidate.domains, 'production': production, ecology.DOMAIN: part})

    def start_facility(self, state, bid, definition, policy_row):
        if policy_row:
            raise ValidationError('营造设施需要手动确认，不自动重复施工')
        building = buildings.get_building(state.domains['sect'], self.registry, bid)
        facility = lookup(self.registry, 'facilities', definition.facility_output_id)
        installed = state.domains[ecology.DOMAIN]['facilities'].get(bid, {}).get(facility['id'], 0)
        if building['definition_id'] != facility['building_kind'] or building['level'] < 1:
            raise ValidationError('建筑未建成或设施不匹配')
        if installed >= (building['level'] if facility['per_level'] else 1):
            raise ValidationError('当前等级的设施已经建齐')
        cap = work.capability(state.domains['disciples'], self.registry, bid, definition.machine_id)
        if not cap['workers']:
            raise ValidationError('请先安排施工弟子')
        stock, _ = operations.consume(state.domains['inventory'], self.registry, dict(definition.inputs))
        counters = {**state.identity, 'instance_counter': state.identity['instance_counter'] + 1,
                    'event_counter': state.identity['event_counter'] + 1}
        jid = f'{state.save_id}:{state.generation}:i:{counters["instance_counter"]}'
        eid = f'{state.save_id}:{state.generation}:e:{counters["event_counter"]}'
        production = jobs.start(state.domains['production'], self.registry, building_id=bid,
                                recipe_id=definition.machine_id, job_id=jid, event_id=eid,
                                sim_ms=state.time['sim_time_ms'], workers=cap['workers'],
                                yield_milli=1000, work_rate_milli=1000)
        domains = self._start_domains(state, production, stock, jid, {'building_id': bid, 'recipe_id': definition.machine_id})
        return replace(state, identity=counters, domains=domains)

    @staticmethod
    def roll(state, identity, stream, probability):
        digest = sha256(f'{state.save_id}:{state.content_version}:{identity}:{stream}'.encode()).digest()
        return int.from_bytes(digest[:8], 'big') % 10000 < probability

    def delivery_outputs(self, state, job):
        definition = jobs.definition(self.registry, job['recipe_id'])
        amounts = jobs.outputs(job, self.registry)
        if 'food' in amounts:
            quantity = amounts.pop('food')
            rid = settings(self.registry)['legacy_food_replacement']
            amounts[rid] = amounts.get(rid, 0) + quantity
        effect = state.domains[ecology.DOMAIN]['job_effects'].get(job['job_id'], {})
        if self.roll(state, job['job_id'], 'extra', effect.get('extra_bps', 0)):
            for rid, quantity in definition.outputs:
                rid = settings(self.registry)['legacy_food_replacement'] if rid == 'food' else rid
                amounts[rid] = amounts.get(rid, 0) + quantity
        # One declared mining pool: Lv4+ ore deposits that already support the
        # formal spirit_iron_ore recipe. Meals never unlock the resource/site.
        if job['recipe_id'] == 'ore' and effect.get('discovery_bps', 0):
            bid = next(key for key, row in state.domains['production']['jobs'].items() if row['job_id'] == job['job_id'])
            if state.domains['sect']['buildings'][bid]['level'] >= jobs.definition(self.registry, 'spirit_iron_ore').min_level and self.roll(state, job['job_id'], 'discovery', effect['discovery_bps']):
                amounts['spirit_iron_ore'] = amounts.get('spirit_iron_ore', 0) + 1
        return amounts

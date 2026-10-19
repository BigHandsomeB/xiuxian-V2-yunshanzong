"""Read-only projections of four-building state and legal content choices."""
from src.core.state.envelope import thaw_json, freeze_json
from src.core.time.world import paused
from src.data.economy.ecology import settings, lookup
from src.data.registry import DefinitionKey
from src.systems.sect import ecology, nutrition
from src.systems.resources import jobs
from src.systems.disciples import work


class EcologyViews:
    def preparation_view(self, state, view):
        """Current-snapshot advice only; existing screens retain all command authority."""
        from src.application import equipment as equip
        from src.application.sect_economy import craft_cost
        from src.systems.cultivation import techniques
        from src.systems.dungeons import progress
        from src.data.dungeons import loot
        stock = state.domains['inventory']['holdings']
        floor = progress.cleared(state.domains['dungeon'], 'thorn_path')
        def requirements(cost):
            return [{'resource_id': rid, 'name': self.registry.lookup(DefinitionKey('resources', rid)).display_name,
                     'quantity': n, 'current': stock.get(rid, 0), 'missing': max(0, n-stock.get(rid, 0))}
                    for rid, n in cost.items()]
        equipment = equip.equipment(state)['instances']
        blades = [row for row in equipment.values() if row['definition_id']=='thorn_fang_blade']
        defense = sum(not row['equipped'] and not equip.items.unknown(row,self.registry)
                      and equip.items.definition(self.registry,row['definition_id']).quality=='white'
                      and equip.items.definition(self.registry,row['definition_id']).slot!='left'
                      and equip.can_equip_realm(state,self.registry,row['definition_id']) for row in equipment.values())
        spring = self.facility_quote(state, 'spring')
        supply = view['ecology']['supply']
        phase = 'prepare' if floor<10 else 'spring' if not spring['exists'] else 'supply'
        if phase=='supply' and supply['enabled'] and supply['active'] and supply['basic_stock']>=supply['people']*3:
            phase='development'
        table = loot.content()['normal_materials']
        sources = [f for f in range(1,100) if f%10 and table[(f-1-(f-1)//10)%len(table)]=='thorn_boar_bone']
        source_floor = sources[0] if sources else None
        recipe = jobs.definition(self.registry,'ingot')
        from src.data.economy.sect_rules import settings as sect_settings
        unlock = sect_settings(self.registry).get('recipe_unlock_overrides',{}).get('ingot',{'floor':recipe.unlock_floor,'realm':recipe.unlock_realm})
        config = techniques.config(self.registry)
        key = 'manual_a00f304b07a9a'
        row = techniques.definition(config,key)
        owned = next((r for r in view['techniques']['instances'] if r['id']==key),None)
        quote = next(r for r in view['techniques']['catalog'] if r['id']==key)['source']
        level = owned['level'] if owned else 1
        bonus = owned['bonus'] if owned else techniques.effective_bonus(config,row,1)
        water = next((r for r in view['sect_services']['market']['offers'] if r['resource_id']=='spring_water'),None)
        return {'phase':phase, 'cleared_floor':floor, 'selected_thorn':progress.selected(state.domains['dungeon'])=='thorn_path',
                'pending':bool(state.time['pending']), 'paused':paused(state.time),
                'blade':{'name':equip.items.definition(self.registry,'thorn_fang_blade').display_name,
                         'owned':bool(blades),'equipped':any(r['equipped'] for r in blades),
                         'requirements':requirements(craft_cost(self.registry,'thorn_fang_blade'))},
                'sources':{'bone_floor':source_floor,'bone_enterable':source_floor is not None and source_floor<=floor+1,
                           'ingot_floor':unlock['floor']},
                'unequipped_defense':defense,
                'technique':{'name':row['name'],'owned':bool(owned),'level':level,
                             'equipped':bool(owned and owned['equipped_slot']),
                             'bonuses':[{'name':{'max_hp_milli':'生命','armor_milli':'护甲'}.get(k,k),'amount':n/1000} for k,n in bonus.items()],
                             'requirements':requirements(quote['cost']) if not owned else [],
                             'blocking_reasons':quote['blocking_reasons'] if not owned else []},
                'spring':{'exists':spring['exists'],'can_build':spring['can_build'],'requirements':requirements(spring['cost']),
                          'blocking_reasons':spring['blocking_reasons']},
                'supply':{'people':supply['people'],'stock':supply['basic_stock'],'suggested_stock':supply['people']*3,
                          'target_days':supply['target_days'],'enabled':supply['enabled'],'active':supply['active'],
                          'hungry':supply['hungry_count'],'day_seconds':supply['day_seconds']},
                'water':{'listed':water is not None,'remaining':water['remaining_stock'] if water else 0,
                         'price':water['price'] if water else None,'max_quantity':water['max_quantity'] if water else 0}}

    def project_world(self, state):
        state=self.prepare_economy_state(state)
        view = thaw_json(super().project_world(state))
        from src.systems.cultivation import techniques
        from src.application.cultivation import partition
        combat=state.domains.get('combat',{}).get('battle') or {}
        blocked=paused(state.time) or bool(state.time['pending']) or state.domains['dungeon']['auto']['enabled'] or combat.get('status') in ('ACTIVE','PLAYER_WIN')
        from src.systems.dungeons.progress import cleared
        view['techniques']=techniques.view(partition(state),self.registry,blocked,state.domains['inventory']['holdings'],cleared(state.domains['dungeon'],'thorn_path'),paused(state.time) or bool(state.time['pending']))
        if view['techniques']:
            from src.application.combat_effect_views import technique as effect_view
            for row in (*view['techniques']['instances'],*view['techniques']['catalog']):row.update(effect_view(self.registry,row['id']))
        view['inventory'].setdefault('manual_page',{'name':'功法残页','quantity':state.domains['inventory']['holdings'].get('manual_page',0),'source_label':'100层Boss结算、首通宝箱或贡献兑换','use_label':'功法阁定向兑换橙、红阶功法'})
        from src.systems.sect import activities
        from src.application.sect_economy import reserved
        view['sect_activities']=activities.view(state,self.registry,max(0,self._capacity(state)-reserved(state,self.registry)))
        from src.systems.sect import exploration
        view['exploration']=exploration.view(state,self.registry,max(0,self._capacity(state)-reserved(state,self.registry)))
        config = settings(self.registry)
        part = state.domains[ecology.DOMAIN]
        now, day = state.time['sim_time_ms'], state.time['day_length_ms']
        for item in config['resources']:
            view['inventory'].setdefault(item['id'], {
                'name': item['name'], 'quantity': state.domains['inventory']['holdings'].get(item['id'], 0),
                'source_label': '灵植、存栏养殖或正式加工配方',
                'use_label': '基础供养、岗位灵膳、饲料或设施营造'})
        actual = state.domains['sect']['buildings']
        available = not paused(state.time) and not state.time['pending']
        farms = []
        for bid, building in actual.items():
            if building['definition_id'] not in ('garden', 'pasture', 'spring', 'canteen'):
                continue
            farms.append({'building_id': bid, 'building_kind': building['definition_id'],
                          'capacity': ecology.capacity(state, self.registry, bid),
                          'occupied': ecology.occupied(part, self.registry, bid),
                          'workers': work.capability(state.domains['disciples'], self.registry, bid)['workers']})
        species = []
        for definition in config['species']:
            bid = next((key for key, row in actual.items()
                        if row['definition_id'] == definition['building_kind'] and row['level'] > 0), None)
            free = ecology.capacity(state, self.registry, bid) - ecology.occupied(part, self.registry, bid) if bid else 0
            maximum = min(free // definition['slots'], state.domains['inventory']['holdings'].get('coins', 0) // definition['purchase_coins'])
            reasons = []
            if not bid:
                reasons.append('请先建设对应养殖设施')
            if maximum < 1:
                reasons.append('容量或灵钱不足')
            if len(part['batches']) >= config['limits']['max_batches']:
                reasons.append('养殖批次达到上限')
            species.append({**thaw_json(definition), 'building_id': bid,
                            'max_purchase': min(maximum, config['limits']['max_count']) if available and not reasons else 0,
                            'feed_name': self.registry.lookup(DefinitionKey('resources', definition['feed_id'])).display_name,
                            'blocking_reasons': reasons})
        batches = []
        for identity, row in sorted(part['batches'].items()):
            definition = lookup(self.registry, 'species', row['species_id'])
            total = ecology.total_work(row, self.registry, day)
            batches.append({**thaw_json(row), 'batch_id': identity, 'name': definition['name'],
                            'building_kind': definition['building_kind'], 'total_work_milli': total,
                            'progress_percent': row['progress_milli'] * 100 // total,
                            'remaining_seconds': (total - row['progress_milli'] + max(1, row['rate_milli']) - 1) // max(1, row['rate_milli']) // 1000,
                            'feed_name': self.registry.lookup(DefinitionKey('resources', definition['feed_id'])).display_name,
                            'feed_id': definition['feed_id'], 'periodic_outputs': thaw_json(definition['periodic_outputs']),
                            'harvest_outputs': thaw_json(definition['harvest_outputs']),
                            'can_collect': available and row['stage'] == 'READY',
                            'can_harvest': available and row['stage'] != 'JUVENILE' and row['last_collection_ms'] != now})
        supply = thaw_json(part['supply'])
        count = nutrition.people(state)
        supply.update(people=count, basic_stock=nutrition.basic_stock(state, self.registry),
                      daily_portions=count, target_stock=count * supply['target_days'],
                      hungry_count=sum(supply['hungry'].values()), served_count=sum(supply['served'].values()),
                      day_seconds=day // 1000, next_day_seconds=max(0, (supply['next_day_ms'] or now) - now) // 1000,
                      active=supply['activated'], food=nutrition.basic_stock(state, self.registry),
                      per_period=count, period_seconds=day // 1000, bonus_percent=0,
                      reserve=count * supply['target_days'], remaining_seconds=0)
        view['sect_services']['supply'] = supply
        view['sect_services']['matters'] = [row for row in view['sect_services']['matters'] if row['id'] != 'supply']
        if not supply['activated'] or supply['basic_stock'] < count:
            view['sect_services']['matters'].insert(0, {
                'id': 'supply', 'name': '灵膳供应未开启或口粮不足',
                'detail': f'每游戏日需要基础灵膳 {count} 份；不足的弟子次日工作效率降低30%。',
                'route': '#building/kitchen'})
        slots = {bid: {**thaw_json(row), 'remaining_seconds': max(0, row['expires_ms'] - now) // 1000}
                 for bid, row in part['meals'].items()}
        view['ecology'] = {'farms': farms, 'crops': thaw_json(config['crops']), 'species': species,
                           'batches': batches, 'supply': supply, 'meals': thaw_json(config['meals']),
                           'position_meals': slots, 'facilities': thaw_json(config['facilities']),
                           'installed_facilities': thaw_json(part['facilities']),
                           'basic_meal_ids': list(nutrition.basic_ids(self.registry)),
                           'available': available}
        view['preparation'] = self.preparation_view(state, view)
        from src.application.artifacts import view as artifact_view
        artifacts=artifact_view(state,self.registry)
        if artifacts is not None:view['artifacts']=artifacts
        return freeze_json(view)

    def project_economy(self, state):
        view = super().project_economy(state)
        config = settings(self.registry)
        crop_ids = {row['recipe_id'] for row in config['crops']}
        meal_by_id = {row['id']: row for row in config['meals']}
        for row in view['recipes']:
            definition = jobs.definition(self.registry, row['recipe_id'])
            if row['recipe_id'] in crop_ids:
                row['ecology_category'] = 'crop'
            elif definition.facility_output_id:
                row['ecology_category'] = 'facility'
                facility = lookup(self.registry, 'facilities', definition.facility_output_id)
                for item in row['inputs']:
                    item['quantity'] = dict(definition.inputs)[item['resource_id']]
                # Base production quotes multiply ingredients by workers;
                # facilities pay one fixed construction cost per installation.
                reasons = [reason for reason in row['blocking_reasons'] if reason != '材料不足']
                if any(item['current'] < item['quantity'] for item in row['inputs']):
                    reasons.append('材料不足')
                row['blocking_reasons'] = reasons
                row['can_start'] = not reasons
                row['facility_id'] = facility['id']
                row['effect_description'] = ('田块' if facility['building_kind'] == 'garden' else '兽栏' if facility['building_kind'] == 'pasture' else '水池容量') + f'+{facility["capacity"]}' if facility['capacity'] else '灵膳制作速度+5%'
            elif any(rid in meal_by_id for rid, _ in definition.outputs):
                row['ecology_category'] = 'meal'
                row['effect_description'] = next(meal_by_id[rid]['effect'] for rid, _ in definition.outputs if rid in meal_by_id)
            elif any('feed_' in rid for rid, _ in definition.outputs):
                row['ecology_category'] = 'feed'
            elif row['recipe_id'].startswith('supplement_recipe_'):
                row['ecology_category'] = 'material'
        journey = state.domains['sect_management'].get('exploration', {}).get('active')
        if state.domains[ecology.DOMAIN]['wake'] or (journey and journey['due_ms'] > state.time['sim_time_ms']):
            view['needs_poll'] = view['needs_settlement'] = True
        return view

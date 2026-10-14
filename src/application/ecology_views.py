"""Read-only projections of four-building state and legal content choices."""
from src.core.state.envelope import thaw_json, freeze_json
from src.core.time.world import paused
from src.data.economy.ecology import settings, lookup
from src.data.registry import DefinitionKey
from src.systems.sect import ecology, nutrition
from src.systems.resources import jobs
from src.systems.disciples import work


class EcologyViews:
    def project_world(self, state):
        state=self.prepare_economy_state(state)
        view = thaw_json(super().project_world(state))
        from src.systems.cultivation import techniques
        from src.application.cultivation import partition
        combat=state.domains.get('combat',{}).get('battle') or {}
        blocked=paused(state.time) or bool(state.time['pending']) or state.domains['dungeon']['auto']['enabled'] or combat.get('status') in ('ACTIVE','PLAYER_WIN')
        from src.systems.dungeons.progress import cleared
        view['techniques']=techniques.view(partition(state),self.registry,blocked,state.domains['inventory']['holdings'],cleared(state.domains['dungeon'],'thorn_path'),paused(state.time) or bool(state.time['pending']))
        view['inventory'].setdefault('manual_page',{'name':'功法残页','quantity':state.domains['inventory']['holdings'].get('manual_page',0),'source_label':'100层Boss结算、首通宝箱或贡献兑换','use_label':'功法阁定向兑换橙、红阶功法'})
        from src.systems.sect import activities
        from src.application.sect_economy import reserved
        view['sect_activities']=activities.view(state,self.registry,max(0,self._capacity(state)-reserved(state,self.registry)))
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
        if state.domains[ecology.DOMAIN]['wake']:
            view['needs_poll'] = view['needs_settlement'] = True
        return view

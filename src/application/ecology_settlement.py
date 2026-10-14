"""Four-building dispatch composed with existing production/dungeon settlement."""
from dataclasses import replace
from src.application.sect_management_settlement import ManagementSettlement
from src.application import equipment as equip, offline_reports as reports, sect
from src.core.state.envelope import thaw_json
from src.core.time.engine import SettlementEngine
from src.core.validation import ValidationError
from src.core.time.world import paused
from src.systems.sect import ecology, nutrition, management
from src.systems.resources import jobs
from src.systems.disciples import work
from src.systems.inventory import operations, holdings
from src.systems.economy import policy
from src.systems.dungeons import progress
from src.data.economy.ecology import lookup


class EcologySettlement(ManagementSettlement):
    def configure(self, day_length_ms):
        self.core = SettlementEngine({
            'production': jobs.simulation(self.registry),
            'automation': policy.simulation(self.registry),
            'dungeon': progress.simulation(self.registry),
            'sect_management': management.simulation(self.registry),
            ecology.DOMAIN: ecology.simulation(self.registry, day_length_ms)})

    def __init__(self, app):
        super().__init__(app)
        self.configure(120000)

    def advance(self, state, **kwargs):
        self.configure(state.time['day_length_ms'])
        return super().advance(state, **kwargs)

    def validate_state(self, state):
        super().validate_state(state)
        self.app.validate_ecology(state)
        return state

    def meals(self, state):
        # Old supply no longer consumes food or grants its +15% in this version.
        return state

    def daily_supply(self, state):
        part = thaw_json(state.domains[ecology.DOMAIN])
        supply = part['supply']
        now, day = state.time['sim_time_ms'], state.time['day_length_ms']
        if not supply['activated'] or supply['next_day_ms'] > now:
            return state
        groups = state.domains['disciples']['groups']
        supply['hungry'] = {
            gid: max(0, min(row['count'], supply['people_snapshot'].get(gid, 0))
                     - supply['served'].get(gid, 0)) for gid, row in groups.items()}
        supply['people_snapshot'] = {gid: row['count'] for gid, row in groups.items()}
        supply['served'] = {}
        stock = state.domains['inventory']
        legacy = supply['legacy_covered_count'] if supply['legacy_until_ms'] >= now + day else 0
        # Stable group order makes partial supply independent of UI/request order.
        for gid, row in sorted(groups.items()):
            served = min(legacy, row['count'])
            legacy -= served
            remaining = row['count'] - served
            if supply['enabled']:
                for rid in nutrition.basic_ids(self.registry):
                    quantity = min(remaining, stock['holdings'].get(rid, 0))
                    if quantity:
                        stock, _ = operations.consume(stock, self.registry, {rid: quantity})
                        remaining -= quantity
                        served += quantity
                    if not remaining:
                        break
            supply['served'][gid] = served
        supply['last_day_ms'] = now
        supply['next_day_ms'] = now + day
        return replace(state, domains={**state.domains, 'inventory': stock, ecology.DOMAIN: part})

    def position_meals(self, state):
        part = thaw_json(state.domains[ecology.DOMAIN])
        stock = state.domains['inventory']
        now, day = state.time['sim_time_ms'], state.time['day_length_ms']
        if nutrition.basic_stock(state, self.registry) < nutrition.people(state) * part['supply']['target_days']:
            return state
        for bid, slot in sorted(part['meals'].items()):
            if not slot['enabled']:
                continue
            count = work.capability(state.domains['disciples'], self.registry, bid)['workers']
            if not count:
                continue
            renewing = slot['expires_ms'] - now < day
            portions = count if renewing else max(0, count - slot['covered_count'])
            if portions and stock['holdings'].get(slot['meal_id'], 0) >= portions:
                stock, _ = operations.consume(stock, self.registry, {slot['meal_id']: portions})
                if renewing:
                    slot.update(covered_count=count, expires_ms=now + 8 * day)
                else:
                    slot['covered_count'] += portions
        return replace(state, domains={**state.domains, 'inventory': stock, ecology.DOMAIN: part})

    def progress_livestock(self, state):
        part = thaw_json(state.domains[ecology.DOMAIN])
        day = state.time['day_length_ms']
        for row in part['batches'].values():
            if row['stage'] == 'READY' or row['progress_milli'] < ecology.total_work(row, self.registry, day):
                continue
            if row['stage'] == 'JUVENILE':
                row.update(stage='MATURE', progress_milli=0, feed_paid=0,
                           rate_milli=0, cycle_rate_milli=0, reason='已成熟')
            else:
                row.update(stage='READY', rate_milli=0, reason='产物待领取')
        part['tick_ready'] = False
        return replace(state, domains={**state.domains, ecology.DOMAIN: part})

    def wake(self, state):
        state = super().wake(state)
        if paused(state.time):
            return state
        state = self.position_meals(state)
        part = thaw_json(state.domains[ecology.DOMAIN])
        now, day = state.time['sim_time_ms'], state.time['day_length_ms']
        stock = state.domains['inventory']
        deadlines = []
        supply = part['supply']
        if supply['activated']:
            deadlines.append(supply['next_day_ms'])
        for slot in part['meals'].values():
            if slot['enabled'] and slot['expires_ms'] > now + day:
                deadlines.append(slot['expires_ms'] - day + 1)
        next_day = (now // day + 1) * day
        if part['batches']:
            deadlines.append(next_day)
        for row in part['batches'].values():
            row['rate_milli'] = 0
            species = lookup(self.registry, 'species', row['species_id'])
            bid = row['building_id']
            if row['stage'] == 'READY':
                continue
            if row['stage'] == 'MATURE' and not species['periodic_outputs']:
                row['reason'] = '已成熟，可收获'
                continue
            workers = work.capability(state.domains['disciples'], self.registry, bid)['workers']
            job = state.domains['production']['jobs'].get(bid)
            if not workers or (job and job['status'] == 'WORKING'):
                row['reason'] = '等待照料弟子' if not workers else '加工中，照料暂停'
                continue
            if not row['cycle_rate_milli']:
                effect = nutrition.effects(state, self.registry, bid)
                row['cycle_rate_milli'] = effect['rate_milli']
                row['extra_bps'] = effect['extra_bps']
            rate = row['cycle_rate_milli']
            total = ecology.total_work(row, self.registry, day)
            target = min(total, row['progress_milli'] + (next_day - now) * rate)
            required = (target * ecology.total_feed(row, self.registry) + total - 1) // total
            payment = min(max(0, required - row['feed_paid']), stock['holdings'].get(species['feed_id'], 0))
            if payment:
                # Whole feed units fund proportional work; the unused fraction remains
                # in the group, so repeated daily rounding cannot grant free feeding.
                stock, _ = operations.consume(stock, self.registry, {species['feed_id']: payment})
                row['feed_paid'] += payment
            credit = ecology.credit_limit(row, self.registry, day)
            if credit <= row['progress_milli']:
                row['reason'] = '饲料不足，成长暂停'
                continue
            row['rate_milli'] = rate
            row['reason'] = '成长中' if row['stage'] == 'JUVENILE' else '周期生产中'
            deadlines.append(now + (min(total, credit) - row['progress_milli'] + rate - 1) // rate)
        old = part['wake']
        due = min(deadlines) if deadlines else None
        counter = state.identity['event_counter']
        if due is None:
            part['wake'] = None
        elif old is None or old['due_ms'] != due or old['next_event_id'] is None:
            counter += 2
            part['wake'] = {'event_id': f'{state.save_id}:{state.generation}:e:{counter - 1}',
                            'next_event_id': f'{state.save_id}:{state.generation}:e:{counter}', 'due_ms': due}
        return replace(state, identity={**state.identity, 'event_counter': counter},
                       domains={**state.domains, 'inventory': stock, ecology.DOMAIN: part})

    def deliver(self, state):
        production = thaw_json(state.domains['production'])
        part = thaw_json(state.domains[ecology.DOMAIN])
        stock = state.domains['inventory']
        capacity = sect.capacity_source(state, self.registry)['effective']
        for job in sorted(production['jobs'].values(), key=lambda row: (row['due_ms'], row['event_id'])):
            if job['status'] != 'OUTPUT_READY':
                continue
            definition = jobs.definition(self.registry, job['recipe_id'])
            amounts = self.app.delivery_outputs(state, job)
            needed = sum(n for rid, n in amounts.items() if holdings.definition(self.registry, rid).warehouse_counted)
            if holdings.stock_size(stock, self.registry) + needed > capacity:
                continue
            if definition.equipment_output_id:
                for _ in range(max(1, job['yield_milli'] // 1000)):
                    state, _ = equip.acquire(state, self.registry, definition.equipment_output_id, job['job_id'])
            if definition.facility_output_id:
                bid = next(key for key, row in production['jobs'].items() if row['job_id'] == job['job_id'])
                installed = part['facilities'].setdefault(bid, {})
                fid = definition.facility_output_id
                installed[fid] = installed.get(fid, 0) + 1
            stock, result = operations.grant(stock, self.registry, amounts, capacity=capacity)
            if any(result['discarded'].values()):
                raise ValidationError('产物必须完整入库')
            job['status'] = 'COMPLETE'
            state = reports.observe_production(state, job, amounts, int(bool(definition.equipment_output_id)))
        active = {row['job_id'] for row in production['jobs'].values() if row['status'] == 'WORKING'}
        current = {row['job_id'] for row in production['jobs'].values()}
        part['job_effects'] = {jid: row for jid, row in part['job_effects'].items() if jid in current}
        return replace(state, domains={**state.domains, 'production': production, 'inventory': stock,
                       'disciples': work.release_finished(state.domains['disciples'], self.registry, active),
                       ecology.DOMAIN: part})

    def dispatch(self, state):
        state = self.app.prepare_economy_state(state)
        state = self.progress_livestock(state)
        state = self.daily_supply(state)
        # Supply happens before automatic starts or discretionary position meals.
        return super().dispatch(state)

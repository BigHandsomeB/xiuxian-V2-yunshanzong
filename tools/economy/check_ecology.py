"""Reproducible 30-minute/24-hour simulations using real V2 SQLite and commands."""
import json
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
from src.application.ecology import EcologyApplication
from src.application.danding import initial_slice
from src.application.memory import Command
from src.application.settlement import SettlementRequest
from src.core.save.sqlite import SQLiteSave, V2_ROOT
from src.core.state.envelope import thaw_json
from src.core.time.model import Continuation
from src.data.dungeons.definitions import load_dungeons
from src.systems.economy import policy
from src.systems.inventory import holdings
from tests.fixtures.time import ManualClock


def simulate(minutes):
    registry = load_dungeons(management=True, cold_jade=True, ecology=True)
    clock = ManualClock()
    state = initial_slice(registry, last_settled_at_ms=clock.now_ms())
    initial = {'coins': 500, 'meal_qingling_rice': 24, 'sect_crop_01': 24, 'spring_water': 6}
    stock = {'holdings': initial}
    disciples = thaw_json(state.domains['disciples'])
    disciples['assignments'] = {}
    # Explicit test-only starting infrastructure, like the initial garden and
    # kitchen. Construction acquisition costs are outside this operating model.
    sect = thaw_json(state.domains['sect'])
    counter = state.identity['instance_counter'] + 1
    sect['buildings'][f'{state.save_id}:1:i:{counter}'] = {
        'definition_id': 'spring', 'level': 1, 'construction_target': None}
    state = replace(state, identity={**state.identity, 'instance_counter': counter},
                    domains={**state.domains, 'inventory': stock, 'sect': sect,
                                   'disciples': disciples, 'automation': policy.initial()})
    with TemporaryDirectory(dir=V2_ROOT / 'tests') as directory:
        root = Path(directory)
        with SQLiteSave.initialize(root / 'model.sqlite3', allowed_root=root) as store:
            app = EcologyApplication(store, registry, clock)
            app.create(state)
            metrics = {'delivery_attempts': 0, 'warehouse_blocked_attempts': 0,
                       'peak_used_capacity': holdings.stock_size(stock, registry)}
            deliver = app.engine.deliver
            def measured_delivery(candidate):
                ready = sum(row['status'] == 'OUTPUT_READY'
                            for row in candidate.domains['production']['jobs'].values())
                result = deliver(candidate)
                metrics['delivery_attempts'] += ready
                metrics['warehouse_blocked_attempts'] += sum(
                    row['status'] == 'OUTPUT_READY' for row in result.domains['production']['jobs'].values())
                metrics['peak_used_capacity'] = max(metrics['peak_used_capacity'],
                    holdings.stock_size(result.domains['inventory'], registry))
                return result
            app.engine.deliver = measured_delivery
            def command(name, payload):
                current = app.query(state.save_id)
                return app.execute(Command(current.save_id, current.generation, current.revision,
                                            str(uuid4()), name, payload))
            current = app.query(state.save_id)
            for kind, recipe, count, target in [('garden', 'grow_sect_crop_01', 2, 24),
                                                ('canteen', 'meal_qingling_rice', 1, 24),
                                                ('spring', 'sect_spring_water', 1, 6)]:
                bid = next((key for key, row in current.domains['sect']['buildings'].items()
                            if row['definition_id'] == kind), None)
                if bid is None:
                    raise RuntimeError('simulation requires an existing Lv1 spring')
                command('work_assign', {'building_id': bid, 'count': count})
                command('automation_production', {'building_id': bid, 'policy': {
                    'enabled': True, 'recipe_id': recipe, 'target': target,
                    'max_consumption': 100, 'reserves': {}}})
            command('ecology_supply', {'enabled': True, 'target_days': 3})
            clock.advance(minutes * 60000)
            requests = 0
            while True:
                current = app.query(state.save_id)
                app.settle(SettlementRequest(current.save_id, current.generation, current.revision,
                           str(uuid4()), 4096, Continuation.for_state(current) if current.time['pending'] else None))
                requests += 1
                final = app.query(state.save_id)
                if not final.time['pending']:
                    break
                if requests > 100:
                    raise RuntimeError('simulation exceeded bounded request budget')
            after = thaw_json(final.domains['inventory']['holdings'])
            result = {'minutes': minutes, 'simulation_days': final.time['sim_time_ms'] // final.time['day_length_ms'],
                      'people': 8, 'workers': {'garden': 2, 'canteen': 1, 'spring': 1},
                      'initial_stock': initial, 'final_stock': after,
                      'scenario': 'test-only prebuilt Lv1 garden/kitchen/spring; construction cost excluded',
                      'coins_delta': after['coins'] - initial['coins'],
                      'coins_per_real_hour': (after['coins'] - initial['coins']) * 60 / minutes,
                      'warehouse_net_units': holdings.stock_size(final.domains['inventory'], registry) - holdings.stock_size(stock, registry),
                      'warehouse_full_attempt_rate': metrics['warehouse_blocked_attempts'] / max(1, metrics['delivery_attempts']),
                      'measurements': metrics,
                      'final_used_capacity': holdings.stock_size(final.domains['inventory'], registry),
                      'hungry_at_end': sum(final.domains['ecology']['supply']['hungry'].values()),
                      'supply_at_end': sum(final.domains['ecology']['supply']['served'].values()),
                      'settlement_requests': requests, 'remaining_pending': bool(final.time['pending']),
                      'current_jobs': len(final.domains['production']['jobs']),
                      'meal_snapshot_records': len(final.domains['ecology']['job_effects'])}
            if result['hungry_at_end'] or result['supply_at_end'] != 8 or result['coins_delta'] != 0:
                raise RuntimeError('baseline supply model did not sustain all eight disciples')
            return result


if __name__ == '__main__':
    # Runs against disposable DBs only; never opens the live .game directory.
    results = [simulate(30), simulate(1440)]
    path = V2_ROOT / 'docs/acceptance/TASK0078/economy-simulation.json'
    path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(results, ensure_ascii=False))

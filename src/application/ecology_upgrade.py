"""Explicit, checkpointed upgrade; never called by GET or service startup."""
from dataclasses import replace
from src.application.ecology import EcologyApplication
from src.application.sect_management import ManagementApplication
from src.application.memory import Command, Receipt
from src.core.save.codec import StoredReceipt
from src.core.state.envelope import thaw_json
from src.core.validation import ValidationError, ConflictError
from src.data.dungeons.definitions import load_dungeons, COLD_JADE_MANAGEMENT_VERSION
from src.data.economy.ecology import VERSION, settings
from src.systems.sect import ecology


def upgrade(store, clock, request):
    if not isinstance(request, Command) or request.name != 'ecology_content_upgrade' or request.version != 1 or request.payload:
        raise ValidationError('exact trusted ecology upgrade required')
    registry = load_dungeons(management=True, cold_jade=True, ecology=True)
    with store.transaction():
        observation = store.inspect(request.save_id, include_recovery=False)
        if observation.status != 'CURRENT_VALID':
            raise ValidationError('valid current save required')
        state = observation.current
        if request.generation != state.generation:
            raise ConflictError('存档已换代')
        saved = store.receipt(state.save_id, state.generation, request.request_id)
        if saved:
            if saved.kind != 'command' or saved.intent != request.digest():
                raise ConflictError('迁移请求内容不一致')
            return Receipt(saved.request_id, saved.committed_revision, saved.payload)
        if state.content_version == VERSION:
            EcologyApplication(store, registry, clock).foundation.validate_state(state)
            return Receipt(request.request_id, state.revision, {'status': 'ALREADY_UPGRADED'})
        if state.content_version != COLD_JADE_MANAGEMENT_VERSION or request.expected_revision != state.revision:
            raise ConflictError('请先使用当前宗门管理与寒玉版本')
        if state.time['pending']:
            raise ConflictError('请先用旧版本完成当前离线窗口，再迁移供养')
        old_registry = load_dungeons(management=True, cold_jade=True)
        ManagementApplication(store, old_registry, clock).foundation.validate_state(state)
        part = thaw_json(ecology.initial())
        management = thaw_json(state.domains['sect_management'])
        old_supply = management['supply']
        if old_supply['enabled']:
            now, day = state.time['sim_time_ms'], state.time['day_length_ms']
            paid = next((row['count'] for row in reversed(management['log']) if row['operation'] == 'MEAL'), 0)
            part['supply'].update(activated=True, enabled=True, next_day_ms=(now // day + 1) * day,
                                  legacy_until_ms=old_supply['effect_until_ms'], legacy_covered_count=paid)
        old_supply.update(enabled=False, effect_until_ms=0, wake=None, tick_ready=False)
        inventory = thaw_json(state.domains['inventory'])
        quantity = inventory['holdings'].pop('food', 0)
        replacement = settings(registry)['legacy_food_replacement']
        if quantity:
            inventory['holdings'][replacement] = inventory['holdings'].get(replacement, 0) + quantity
        automatic = thaw_json(state.domains['automation'])
        retired = set(settings(registry)['retired_recipes'])
        for row in automatic['production'].values():
            if row['recipe_id'] in retired:
                row['enabled'] = False
        candidate = replace(state, content_version=VERSION, revision=state.revision + 1,
                            domains={**state.domains, 'inventory': inventory, 'sect_management': management,
                                     'automation': automatic, ecology.DOMAIN: part})
        app = EcologyApplication(store, registry, clock)
        # Migration only schedules future daily supply; it does not advance time,
        # start work, feed livestock, refund meals, or modify existing Job rates.
        candidate = app.engine.wake(candidate)
        app.foundation.validate_state(candidate)
        if candidate.time != state.time or candidate.domains['production'] != state.domains['production']:
            raise ValidationError('migration must preserve time and every existing job')
        for domain in state.domains:
            if domain not in ('inventory', 'sect_management', 'automation') and candidate.domains[domain] != state.domains[domain]:
                raise ValidationError('migration modified unrelated state')
        receipt = Receipt(request.request_id, candidate.revision, {
            'status': 'UPGRADED', 'content_version': VERSION, 'converted_food': quantity,
            'replacement': replacement, 'old_jobs': 'PRESERVED'})
        store.checkpoint(state.save_id)
        store.commit(state, candidate, StoredReceipt(state.save_id, state.generation,
                     request.request_id, request.digest(), candidate.revision, 'command', thaw_json(receipt.result)))
        store.checkpoint(state.save_id)
        return receipt

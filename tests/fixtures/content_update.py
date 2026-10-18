"""TEST ONLY: disposable JSON package and one explicit additive rehearsal edge.

No production migration/CLI entry point. Callers own the temporary tests directory;
all file redirection and cached content are restored on context exit.
"""
from contextlib import contextmanager, ExitStack
from dataclasses import replace
import importlib
import json
from pathlib import Path
import shutil
from unittest.mock import patch
from uuid import UUID, uuid4

from src.application.danding import initial_slice
from src.application.ecology import EcologyApplication
from src.application.memory import Command, Receipt
from src.application import equipment as equip
from src.application.settlement import SettlementRequest
from src.core.save.codec import StoredReceipt
from src.core.save.sqlite import V2_ROOT
from src.core.state.envelope import thaw_json
from src.core.time.model import Continuation
from src.core.validation import ConflictError, ValidationError
from src.data import content_loader
from src.data.content_compatibility import differences, package_evidence
from src.data.dungeons import catalog, expeditions, loot
from src.data.economy import ecology
from src.data.registry import DefinitionKey
from src.systems.cultivation import leveling, growth
from src.systems.dungeons import progress
from src.systems.economy import policy
from src.systems.equipment import items

VERSION = 'content-drill-only-v1'
SOURCE_VERSION = ecology.VERSION
DUNGEON = 'content_drill'
MATERIAL = DUNGEON + '_material_01'
GEAR = DUNGEON + '_equipment_01'
TONIC = 'drill_tonic'
RECIPE = 'brew_drill_tonic'
SAVE_ID = '00000000-0000-4000-8000-000000000002'
ENTRY = catalog.DungeonEntry(DUNGEON, 'expedition', DUNGEON + '.json')
# Explicit readers, not a global Path/import hook. All are restored by ExitStack.
READERS = ('dungeons.catalog', 'dungeons.definitions', 'dungeons.expeditions',
           'dungeons.loot', 'dungeons.balance', 'dungeons.durability',
           'economy.definitions', 'economy.sect_rules', 'economy.ecology',
           'economy.market', 'economy.activities', 'cultivation.definitions',
           'combat.definitions', 'disciples.work', 'recipes.production',
           'buildings.definitions', 'items.resources')


def test_root(root):
    root = Path(root)
    if root.is_symlink() or root.resolve() == V2_ROOT/'tests' or not root.resolve().is_relative_to(V2_ROOT/'tests'):
        raise ValidationError('dedicated V2 tests directory required')
    return root.resolve()


def read(root, relative):
    return json.loads((root/'src/data'/relative).read_text())


def write(root, relative, value):
    (root/'src/data'/relative).write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')


def prepare_package(root):
    """Copy JSON only; no source tree, database, or player data is copied."""
    root = test_root(root)
    if (root/'src').exists():
        raise ValidationError('fresh rehearsal directory required')
    for source in (content_loader.ROOT/'src/data').rglob('*.json'):
        target = root/source.relative_to(content_loader.ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    dungeon = json.loads(json.dumps(read(root, 'dungeons/red_copper_mine.json')).replace('red_copper_mine', DUNGEON))
    dungeon['name'] = '隔离演练洞府'
    dungeon['unlock'] = {'dungeon_id':'thorn_path', 'cleared_floor':30}
    # Functional fixture only: actual combat/reward, without a balance experiment.
    dungeon['balance']['curve'] = {'hp':['1','0','0'], 'attack':['0.1','0','0'], 'armor':['0','0','0']}
    dungeon['loot']['rates']['normal'].update(material_bps=10000, material_quantity=4, equipment_bps=10000)
    write(root, 'dungeons/'+ENTRY.source, dungeon)
    rules = read(root, 'economy/sect_rules.json')
    rules['additional_resources'].append({'machine_id':TONIC, 'display_name':'演练修为药', 'capacity_counted':False, 'grade':1})
    rules['additional_recipes'].append({'machine_id':RECIPE, 'display_name':'炼制演练修为药', 'building_kind':'alchemy',
        'inputs':{MATERIAL:1}, 'outputs':{TONIC:1}, 'duration_ms':1000, 'min_level':1, 'unlock_floor':0, 'unlock_realm':0})
    rules['production_whitelist'].append(RECIPE)
    rules['recipe_sect_minimum'][RECIPE] = 2
    write(root, 'economy/sect_rules.json', rules)
    management = read(root, 'economy/sect_management.json')
    management['craft_costs'][GEAR] = {MATERIAL:1, 'coins':1}
    management['craft_gates'][GEAR] = {'forge_level':3, 'dungeon_id':DUNGEON}
    write(root, 'economy/sect_management.json', management)
    levels = read(root, 'cultivation/leveling.json')
    levels['pills'][TONIC] = dict(levels['pills']['ju_qi_pill'])
    write(root, 'cultivation/leveling.json', levels)
    eco = read(root, 'economy/ecology.json');eco['content_version'] = VERSION
    write(root, 'economy/ecology.json', eco)
    manifest = read(root, 'content_manifest.json');manifest['content_version'] = VERSION
    next(row for row in manifest['packages'] if row['id']=='expeditions')['sources'].append('src/data/dungeons/'+ENTRY.source)
    write(root, 'content_manifest.json', manifest)


@contextmanager
def package(root):
    """Use original strict assembly against explicit temporary JSON readers."""
    root = test_root(root)
    from src.data.dungeons import durability
    from src.data.economy import activities
    caches = (loot.content, expeditions.content, durability.settings, activities.content)
    with ExitStack() as stack:
        for name in READERS:
            module = importlib.import_module('src.data.'+name)
            stack.enter_context(patch.object(module, '__file__', str(root/'src/data'/Path(*name.split('.')).with_suffix('.py'))))
        stack.enter_context(patch.object(catalog, 'ENTRIES', (*catalog.ENTRIES, ENTRY)))
        stack.enter_context(patch.object(ecology, 'VERSION', VERSION))
        def assemble(profile):
            selected, _ = content_loader.content_snapshot(root, content_loader.DEFAULT_MANIFEST)
            catalog.validate_sources(content_loader.validate_manifest(selected))
            return content_loader._assemble_profile(profile)
        try:
            yield content_loader.ContentLoader(root=root, assembler=assemble)
        finally:
            for reader in caches:
                reader.cache_clear()


def assert_additive(source, target):
    """Reject edits/deletions; enumerate and inspect every intentional aggregate delta."""
    if source.content_version != SOURCE_VERSION or target.content_version != VERSION:
        raise ValidationError('only the rehearsal forward edge is supported')
    delta = differences(package_evidence(source), package_evidence(target))
    if delta['definitions']['removed'] or delta['effects']['removed'] or delta['effects']['modified']:
        raise ValidationError('non-additive rehearsal content')
    if set(delta['definitions']['modified']) != {'sect_rules:shipping', 'alchemy:additional_recipes'}:
        raise ValidationError('unexpected historical definition edit')
    left = source.lookup(DefinitionKey('sect_rules','shipping'))
    right = target.lookup(left.key)
    values = thaw_json(right.values)
    original = thaw_json(left.values)
    # Remove only named additions; all preexisting values and ordering must match.
    values['additional_resources'] = [row for row in values['additional_resources'] if row['machine_id'] != TONIC]
    values['additional_recipes'] = [row for row in values['additional_recipes'] if row['machine_id'] != RECIPE]
    values['production_whitelist'].remove(RECIPE)
    values['recipe_sect_minimum'].pop(RECIPE)
    values['leveling']['pills'].pop(TONIC)
    values['management']['craft_costs'].pop(GEAR)
    values['management']['craft_gates'].pop(GEAR)
    values['craft']['materials'].pop(GEAR)
    values['ecology']['content_version'] = SOURCE_VERSION
    if values != original or set(left.references) - set(right.references):
        raise ValidationError('historical rule values changed')
    expected_refs = {DefinitionKey('production',RECIPE),DefinitionKey('resources',MATERIAL),DefinitionKey('equipment',GEAR)}
    if set(right.references)-set(left.references) != expected_refs:
        raise ValidationError('unexpected aggregate references')
    old = source.lookup(DefinitionKey('alchemy','additional_recipes'))
    new = target.lookup(old.key)
    added_ref = DefinitionKey('production',RECIPE)
    if (replace(new,references=old.references) != old or new.references.count(added_ref) != 1
            or tuple(k for k in new.references if k != added_ref) != old.references):
        raise ValidationError('historical alchemy membership changed')
    return delta


def migrate(store, clock, request, source, target):
    """Only this synthetic save and tests-directory SQLite; never called by runtime."""
    test_root(store.path.parent)
    if request.save_id != SAVE_ID or request.name != 'drill_upgrade' or request.version != 1 or request.payload:
        raise ValidationError('exact synthetic rehearsal command required')
    assert_additive(source, target)
    with store.transaction():
        observation = store.inspect(SAVE_ID, include_recovery=False)
        if observation.status != 'CURRENT_VALID':
            raise ValidationError('valid rehearsal save required')
        state = observation.current
        if state.generation != request.generation:
            raise ConflictError('generation changed')
        saved = store.receipt(SAVE_ID, state.generation, request.request_id)
        if saved:
            if saved.kind != 'command' or saved.intent != request.digest():
                raise ConflictError('migration intent changed')
            return Receipt(saved.request_id, saved.committed_revision, saved.payload)
        if state.content_version != SOURCE_VERSION or state.revision != request.expected_revision or state.time['pending']:
            raise ConflictError('settle source window before forward migration')
        EcologyApplication(store, source, clock).foundation.validate_state(state)
        candidate = replace(state, content_version=VERSION, revision=state.revision+1)
        EcologyApplication(store, target, clock).foundation.validate_state(candidate)
        result = {'status':'DRILL_UPGRADED', 'content_version':VERSION}
        store.checkpoint(SAVE_ID)
        store.commit(state, candidate, StoredReceipt(SAVE_ID,state.generation,request.request_id,
                     request.digest(),candidate.revision,'command',result))
        store.checkpoint(SAVE_ID)
        return Receipt(request.request_id,candidate.revision,result)


def synthetic_state(registry, clock):
    with patch('src.core.state.envelope.uuid4', return_value=UUID(SAVE_ID)):
        state = initial_slice(registry,last_settled_at_ms=clock.now_ms())
    domains = thaw_json(state.domains)
    domains['disciples']['assignments'] = {}
    domains['automation'] = thaw_json(policy.initial())
    domains['inventory']['holdings'].update(coins=1000, herb=30, spring_water=30)
    domains['dungeon'] = {**progress.initial(), 'cleared_floor':29}
    for row in domains['sect']['buildings'].values():
        row['level'] = max(3,row['level'])
    cultivation = thaw_json(growth.initial(state.save_id))
    cultivation['total_xp'] = leveling.table(leveling.config(registry))[90]
    domains['cultivation'] = cultivation
    state = replace(state,domains=domains)
    for index in (11,3,5,12,9,10):
        state, identity = equip.acquire(state,registry,f'cold_jade_cave_equipment_{index:02d}',
                                       'synthetic-old-roll:'+str(index),roll_version='cold_jade_cave-roll-v1')
        gear = items.equip(equip.equipment(state),registry,identity,False)
        state = replace(state,domains={**state.domains,'equipment':gear})
    return state


def command(app, name, payload=None):
    state = app.query(SAVE_ID)
    return Command(SAVE_ID,state.generation,state.revision,str(uuid4()),name,payload or {})


def execute(app, name, payload=None):
    request = command(app,name,payload)
    return request, app.execute(request)


def drain(app, clock, elapsed=0, budget=32):
    clock.advance(elapsed)
    for _ in range(200):
        state = app.query(SAVE_ID)
        continuation = Continuation.for_state(state) if state.time['pending'] else None
        app.settle(SettlementRequest(SAVE_ID,state.generation,state.revision,str(uuid4()),budget,continuation))
        if app.query(SAVE_ID).time['pending'] is None:
            return
    raise AssertionError('bounded rehearsal settlement did not finish')


def win_and_claim(app):
    battle = app.query(SAVE_ID).domains['combat']['battle']
    bid = battle['battle_id']
    for _ in range(200):
        if app.query(SAVE_ID).domains['combat']['battle']['status'] != 'ACTIVE':
            break
        execute(app,'combat_attack',{'battle_id':bid})
    if app.query(SAVE_ID).domains['combat']['battle']['status'] != 'PLAYER_WIN':
        raise AssertionError('real rehearsal combat did not win')
    request, receipt = execute(app,'combat_reward',{'battle_id':bid})
    return request, receipt

"""Bounded level-2 refinement comparison; synthetic actors, no SQLite or player data."""
import json
import re
from pathlib import Path
from statistics import mean
from src.core.state.envelope import thaw_json
from src.data.content_loader import load_current
from src.data.economy.refinement import settings
from src.systems.equipment import items, refinement
from src.systems.combat import battle

ROOT = Path(__file__).resolve().parents[2]
GEAR = ('thorn_fang_blade', 'thorn_vine_gloves', 'thorn_travel_belt',
        'thorn_scale_shirt', 'thorn_moss_boots', 'thorn_feather_hood')
COMBINATIONS = {
    'control': (0, None),
    'one_ore': (1, ['ore', 'ore', 'ore']),
    'six_thorn': (6, ['thorn_boar_bone', 'thorn_spine', 'thorn_vine_core']),
    'six_late_boss': (6, ['fire_elixir_ruins_material_11', 'fire_elixir_ruins_material_12', 'cold_jade_cave_material_12']),
}


def run():
    registry = load_current()
    cfg = settings(registry)
    actors = json.loads(re.search(r'```json\n(.*?)\n```', (ROOT/'balance/baseline-spec.md').read_text(), re.S).group(1))
    bare = actors['筑基裸装']
    equipment = items.initial()
    for i, key in enumerate(GEAR):
        identity = f'design:1:i:{i+1}'
        equipment = items.add(equipment, registry, identity, key, 'refinement-balance', 0, False)
        equipment = items.equip(equipment, registry, identity, False)
    rows = []
    for name, (count, materials) in COMBINATIONS.items():
        part = thaw_json(equipment)
        for row in list(part['instances'].values())[:count]:
            row['refinement'] = thaw_json(refinement.result(materials, cfg))
        items.validate(part, registry, 'design')
        actor = items.projection(part, bare)
        for floor in (10, 50, 100):
            def fight(seed, verify=False):
                identity = f'refine-v1:{floor}:{seed}'
                start = battle.start(battle.initial(), registry, 'design', identity,
                    f'thorn_path_v2_{floor:03}', player_snapshot=actor, equipment_sources=GEAR)
                result, _, rounds = battle.result_only(start, registry, 'design')
                if verify:
                    current = start
                    for _ in range(200):
                        if current['battle']['status'] != 'ACTIVE':break
                        current = battle.attack(current, registry, 'design', identity)
                    for field in ('status', 'step', 'player_hp_milli', 'enemy_hp_milli'):
                        assert current['battle'][field] == result['battle'][field], field
                return result['battle'], rounds
            fight(0, True)
            samples = [fight(seed) for seed in range(64)]
            pct = 100 * sum(b['status'] == 'PLAYER_WIN' for b, _ in samples) / len(samples)
            if 5 < pct < 95:
                samples.extend(fight(seed) for seed in range(64, 1000))
            wins = [(b, n) for b, n in samples if b['status'] == 'PLAYER_WIN']
            rows.append({'combination': name, 'floor': floor, 'runs': len(samples),
                'win_pct': 100*len(wins)/len(samples),
                'mean_rounds': mean(n for _, n in samples),
                'mean_win_hp_pct': mean(100*b['player_hp_milli']/actor['max_hp_milli'] for b, _ in wins) if wins else None,
                'player_stats': {k: actor.get(k, 0) for k in items.STATS if actor.get(k, 0)}})
    output = ROOT/'.tmp/refinement-20261020/balance.json'
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps({'content_version': registry.content_version,
        'seeds': 'refine-v1:{floor}:{0..63}; critical cells extended to 0..999',
        'assumptions': 'Frozen foundation bare actor + six mean thorn items, no affixes/enhancement/techniques/artifact; later Boss materials deliberately stress tested on early gear. Not a progression or long-term economy simulation.',
        'cases': sum(row['runs'] for row in rows), 'rows': rows}, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'cases': sum(r['runs'] for r in rows), 'output': str(output),
        'rows': [{k: r[k] for k in ('combination', 'floor', 'runs', 'win_pct', 'mean_rounds')} for r in rows]}, ensure_ascii=False))


if __name__ == '__main__':
    run()

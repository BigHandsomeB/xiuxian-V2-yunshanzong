"""Generate batch-one recipe quantities and deadlines; never touch saves or old jobs."""
import argparse
import json
from pathlib import Path
from math import ceil
ROOT = Path(__file__).resolve().parents[2]
MODEL = Path(__file__).with_name('economy_model.json')

def generate(model):
    recipes = []
    for entry in model['recipes']:
        row = {k: entry[k] for k in ('machine_id', 'display_name', 'building_kind')}
        row.update(inputs={k: ceil(n * entry.get('cost_multiplier', 1)) for k,n in entry.get('base_inputs', {}).items()},
                   outputs=entry['outputs'], duration_ms=round(model['base_cycle_seconds'] * entry.get('time_multiplier', 1) * 1000),
                   min_level=entry.get('source_level', max(model['processing_level'],entry.get('minimum_input_level',model['processing_level'])+entry.get('processing_level_offset',0))), unlock_floor=0, unlock_realm=0)
        recipes.append(row)
    for index, entry in enumerate(model.get('foundation_pills', [])):
        discount=model['foundation_discount_per_tier']**index
        gain=model['foundation_base_gain']*entry['weight']
        seconds=model['foundation_target_hours']*3600*gain/model['foundation_threshold']*discount*model['foundation_reference_workers']
        recipes.append(dict(machine_id=entry['machine_id'],display_name='炼制'+entry['display_name'],building_kind='alchemy',
            inputs={k:ceil(n*entry['weight']*discount) for k,n in entry['base_inputs'].items()},outputs={entry['machine_id']:1},
            duration_ms=round(seconds)*1000,min_level=entry['level'],unlock_floor=0,unlock_realm=0))
    return recipes

def generate_management(model):
    base=model['sect_management'];cfg=dict(base)
    cfg['recruit_duration_ms']=round(model['base_cycle_seconds']*base['recruit_cycles_per_person']*1000)
    cfg['meal_period_ms']=round(model['base_cycle_seconds']*base['meal_period_cycles']*1000)
    cfg['recipes']=generate({**model,'recipes':model['sect_management_recipes'],'foundation_pills':[]})
    cfg['upgrade_costs']={kind:dict(base['upgrade_cost_per_level']) for kind in ('warehouse','garden','alchemy','mine','forest','quarry','smelter','house','canteen','forge','pasture','spring')}
    cfg['building_stone_costs']={str(level):{stage['resource_id']:level*base['building_stones_per_target_level']} for stage in base.get('building_stone_stages',[]) for level in range(stage['min_level'],stage['max_level']+1)}
    cfg['upgrade_additional_costs']={str(level):{row['resource_id']:level*row['per_target_level'] for row in base.get('upgrade_material_stages',[]) if level>=row['min_level']} for level in range(1,11)}
    cfg['craft_costs']={};cfg['craft_gates']={};cfg['sale_prices']={}
    for index,name in enumerate(('red_copper_mine','mist_marsh'),2):
        data=json.loads((ROOT/'src/data/dungeons'/f'{name}.json').read_text())
        theme=data['loot']['theme_materials'][0]
        for row in data['equipment']:
            suffix=int(row['id'].rsplit('_',1)[1]);material=data['materials'][suffix-1]['id'];v=base['new_craft_cost'];scale=2 if row['boss_only'] else 1
            cfg['craft_costs'][row['id']]={'ingot':v['ingot']*scale,theme:v['theme_mine']*scale,material:v['monster_material']*scale,'coins':v['coins']*(index-1)*scale}
            cfg['craft_gates'][row['id']]={'dungeon_id':name,'forge_level':base['new_craft_min_forge_level']+index-2}
            cfg['sale_prices'][material]=base['material_sale_coins']*(index-1)
    shared=json.loads((ROOT/'src/data/dungeons/expedition_materials.json').read_text())
    for row in shared['materials']:cfg['sale_prices'][row['id']]=base['material_sale_coins']
    thorn=json.loads((ROOT/'src/data/dungeons/thorn_loot.json').read_text())
    for row in thorn['materials']:cfg['sale_prices'][row['id']]=base['material_sale_coins']
    for rid in ('copper','hide'):cfg['sale_prices'][rid]=base['material_sale_coins']
    cfg['pill_inputs']={r['machine_id']:{**r['inputs'],model['sect_pill_core']['resource_id']:max(1,ceil(model['sect_pill_core']['per_base_batch']*entry['weight']*model['foundation_discount_per_tier']**i))} for i,entry in enumerate(model['foundation_pills']) for r in generate(model) if r['machine_id']==entry['machine_id']}
    for rid in ('copper','hide'):cfg['sale_prices'][rid]=base['material_sale_coins']
    cfg['pill_inputs']['breakthrough_pill']={**model['sect_pill_core']['breakthrough_base_inputs'],model['sect_pill_core']['resource_id']:model['sect_pill_core']['per_base_batch']*model['sect_pill_core']['breakthrough_core_batches']}
    cfg['enhancement_costs']={str(n):{key:value*(n*n if key=='coins' else n) for key,value in base['enhancement_cost'].items()} for n in range(1,base['enhancement_max_level']+1)}
    return cfg

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');args=parser.parse_args()
    model=json.loads(MODEL.read_text())
    if 'sect_management' in model:
        management=generate_management(model);mp=ROOT/'src/data/economy/sect_management.json'
        if args.check:
            if not mp.exists() or json.loads(mp.read_text())!=management:raise SystemExit('generated management differs')
        else:
            import importlib.util
            spec=importlib.util.spec_from_file_location('guard',ROOT/'tools/project_paths.py');guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)
            guard.write(mp,json.dumps(management,ensure_ascii=False,indent=2)+'\n')
    path=ROOT/'src/data/economy/sect_rules.json';cfg=json.loads(path.read_text())
    generated=generate(model)
    canonical_path=ROOT/'src/data/recipes/production.json'
    canonical=json.loads(canonical_path.read_text())
    canonical_ids={r['machine_id'] for r in canonical['definitions']}
    for row in generated:
        if row['machine_id'] in canonical_ids:
            old=next(r for r in canonical['definitions'] if r['machine_id']==row['machine_id'])
            if args.check and old!=row:raise SystemExit('canonical generated recipe differs')
            old.update(row)
    if not args.check:canonical_path.write_text(json.dumps(canonical,ensure_ascii=False,indent=2)+'\n')
    generated=[r for r in generated if r['machine_id'] not in canonical_ids]
    ids={r['machine_id'] for r in generated}
    rows=[r for r in cfg['additional_recipes'] if r['machine_id'] not in ids]+generated
    pills={r['machine_id']:{'gain':model['foundation_base_gain']*r['weight']} for r in model.get('foundation_pills',[])}
    if args.check and cfg.get('foundation_cultivation',{}).get('pills',{})!=pills:raise SystemExit('generated pill gains differ')
    if pills:
        if args.check and cfg['foundation_cultivation']['threshold']!=model['foundation_threshold']:raise SystemExit('foundation threshold differs')
        cfg['foundation_cultivation']['pills']=pills
        cfg['foundation_cultivation']['threshold']=model['foundation_threshold']
    if args.check:
        if rows!=cfg['additional_recipes']:raise SystemExit('generated recipes differ; run generate_costs.py')
    else:
        cfg['additional_recipes']=rows
        path.write_text(json.dumps(cfg,ensure_ascii=False,indent=2)+'\n')
    print(f'{len(model["recipes"])+len(model.get("foundation_pills",[]))+len(model.get("sect_management_recipes",[]))} recipes and management costs: '+('verified' if args.check else 'generated'))
if __name__=='__main__':main()

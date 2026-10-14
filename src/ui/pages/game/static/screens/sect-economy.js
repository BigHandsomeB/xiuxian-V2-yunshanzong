import {el,button,facts} from '../components/dom.js';
import {resourceIcon,itemIcon} from '../components/item-icon.js';
import {requirementRow,confirmSheet} from '../components/features.js';
export function upgradeControls(ctx,row){
 const box=el('section','panel');box.dataset.building=row.instance_id;
 box.append(el('h2','',`${row.name} · Lv${row.level}`));
 const requirements=el('div','upgrade-requirements');requirements.setAttribute('aria-label','升级材料需求，横向查看');requirements.setAttribute('tabindex','0');
 for(const r of row.upgrade_requirements||[]){const material=requirementRow(r.name,r.quantity,r.current,resourceIcon(ctx,r.resource_id));material.dataset.resourceId=r.resource_id;requirements.append(material);}
 if(requirements.children.length)box.append(requirements);
 if(!row.upgrade_opened){box.append(el('p','muted',row.next_level?'仅报价，升级尚未开放':'已达最高等级'));return box;}
 box.append(el('p','muted',`升级至 Lv${row.next_level} · 即时完成`));
 const action=button('升级建筑',()=>confirmSheet(ctx,'确认升级',`${row.name}：Lv${row.level} → Lv${row.next_level}，按上方需求扣费，即时完成。`,()=>ctx.economyAction('building_upgrade',{building_id:row.instance_id})),'primary block');
 action.disabled=ctx.busy||!row.upgrade_available;action.dataset.buildingUpgrade=row.instance_id;box.append(action);return box;
}
export function renderCrafting(ctx){
 const box=el('section','economy-panel'),grid=el('div','inventory-grid');box.append(el('h2','','装备打造'));
 for(const r of ctx.data.view.economy?.crafting||[]){
  const cell=button('',()=>{const latest=ctx.data.view.economy?.crafting?.find(row=>row.equipment_id===r.equipment_id);if(latest)ctx.sheet(latest.name,craftingDetail(ctx,latest));},'inventory-item');
  cell.dataset.equipmentId=r.equipment_id;cell.append(craftIcon(ctx,r),el('span','item-name',r.name),el('small','',r.quality_name||({white:'凡品',green:'灵品',blue:'玄品',rare:'稀有'})[r.quality]));grid.append(cell);
 }
 box.append(grid,el('p','muted','点击装备查看属性与打造材料。打造装备与战利品装备相同，战利品管家同样会处理新装备。'));return box;
}
function craftIcon(ctx,r,profile=null){const binding=ctx.data.presentation?.equipment_icons?.[r.equipment_id]||ctx.data.presentation?.icons?.[r.equipment_id]||ctx.data.assetManifest?.icons?.[r.equipment_id]||(ctx.data.assetManifest?.catalog?.groups||[]).flatMap(g=>g.items||[]).find(row=>row.asset_id===r.asset_id)?.visual||{};return itemIcon({asset_id:binding.asset_id||r.asset_id,asset:binding.asset,fallback:'equipment',quality:r.quality,profile:profile||ctx.ui?.iconProfile||'compact'});}
function craftingDetail(ctx,r){
 const row=el('article','equipment-detail');row.dataset.equipmentId=r.equipment_id;
 row.append(craftIcon(ctx,r,'detail'),el('h2','',r.name),facts([['部位',r.slot_name||'—'],['品质',r.quality_name||({white:'凡品',green:'灵品',blue:'玄品',rare:'稀有'})[r.quality]],['打造时间','即时完成']]));
 const names={max_hp:'生命',attack:'攻击',armor:'护甲',pierce:'破甲',crit:'暴击',accuracy:'命中加成',evasion:'闪避',speed:'速度',reflect:'反伤',poison_resist:'抗毒',execute:'斩杀增伤',crit_damage:'暴击伤害加成',crit_resist:'抗暴',lifesteal:'吸血',damage_bonus:'伤害加成',damage_reduction:'伤害减免'};
 row.append(facts(Object.entries(r.stats||{}).map(([key,value])=>[names[key]||key,(r.stat_ranges?.[key]?r.stat_ranges[key].join('–'):String(value))+(['max_hp','attack','armor'].includes(key)?'':'%')])));
 if(Object.keys(r.stat_ranges||{}).length)row.append(el('p','muted','打造时随机生成范围内属性，获得后数值固定。'));
 row.append(el('h3','','打造材料'));for(const req of r.requirements)row.append(requirementRow(req.name,req.quantity,req.current,resourceIcon(ctx,req.resource_id)));
 const action=button('打造',()=>confirmSheet(ctx,'确认打造',`打造 ${r.name} 将消耗：${r.requirements.map(q=>`${q.name} ×${q.quantity}`).join('、')}。即时完成，属性在现有范围内随机生成。`,()=>ctx.economyAction('equipment_craft',{equipment_id:r.equipment_id})),'primary block');
 action.dataset.craftEquipment=r.equipment_id;action.disabled=ctx.busy||!r.can_craft;row.append(action);
 if(r.blocking_reasons.length)row.append(el('p','blocking',r.blocking_reasons.join(' · ')));return row;
}

// Committed state only; every catalog uses the shared two-column recipe grid.
import {el,button,facts,empty,link} from '../components/dom.js';
import {confirmSheet,featureTab} from '../components/features.js';
import {resourceIcon} from '../components/item-icon.js';
import {renderProduction} from './economy.js';
import {renderHabitats} from './habitats.js';
import {renderGardenPlots} from './garden.js';

const current=ctx=>ctx.data.view.ecology;
const usable=ctx=>!ctx.busy&&current(ctx)?.available;
const name=(ctx,id)=>ctx.data.view.inventory[id]?.name||id;
function card(id,title,lines,open,icon){
 const node=button('',open,'panel recipe-card ecology-card');node.dataset.id=id;node.setAttribute('aria-label',title+' · 查看详情');
 node.append(el('strong','recipe-card-name',title));if(icon)node.append(icon);
 for(const text of lines)node.append(el('span','recipe-meta',text));return node;
}
function tabs(ctx,key,items){
 const saved=ctx.ui.ecologyTabs??={},selected=saved[key]||items[0][0];
 return {selected,node:featureTab(items,selected,value=>{saved[key]=value;ctx.redraw();})};
}
function productionSubset(ctx,kinds,predicate){
 const view=ctx.data.view;return renderProduction({...ctx,data:{...ctx.data,view:{...view,economy:{...view.economy,recipes:view.economy.recipes.filter(predicate)}}}},kinds);
}
export function renderGarden(ctx){return renderGardenPlots(ctx);}
export function renderHusbandry(ctx,kind){return renderHabitats(ctx,kind);}
export function renderMeals(ctx){
 const box=el('section','ecology-panel');box.dataset.systemIcon='ecology-meals';
 const tab=tabs(ctx,'meals',[['basic','基础灵膳'],['position','岗位灵膳'],['supply','供养设置'],['facility','营造设施']]);box.append(tab.node);
 if(tab.selected==='supply'){box.append(supplyControls(ctx),positionMealCards(ctx));return box;}
 const basic=new Set(current(ctx).basic_meal_ids);
 box.append(productionSubset(ctx,['canteen'],row=>tab.selected==='facility'?row.ecology_category==='facility':row.ecology_category==='meal'&&row.outputs.some(output=>tab.selected==='basic'?basic.has(output.resource_id):!basic.has(output.resource_id))));return box;
}
function supplyControls(ctx){
 const s=current(ctx).supply,box=el('section','panel');box.dataset.systemIcon='ecology-daily-supply';
 box.append(el('h2','','基础灵膳供应'),facts([['供应',s.enabled?'自动供应':s.activated?'已停发，仍按日检查供养':'尚未开启'],['基础灵膳库存',String(s.basic_stock)],['每日需要',`${s.daily_portions} 份`],['目标储备',`${s.target_days} 日 / ${s.target_stock} 份`],['当日已供养',`${s.served_count} 人`],['当前缺粮减速',`${s.hungry_count} 人`]]));
 const days=el('select');days.setAttribute('aria-label','基础灵膳储备天数');days.dataset.id='ecology-reserve-days';for(let n=3;n<=7;n++){const option=el('option','',n+' 游戏日');option.value=String(n);days.append(option);}days.value=String(s.target_days);const label=el('label','policy-field','口粮目标储备');label.append(days);box.append(label);
 const save=enabled=>{const target_days=Number(days.value);confirmSheet(ctx,'灵膳供应',enabled?'按游戏日为全宗弟子发放基础灵膳；缺粮次日减速30%。':'停止自动发餐；已开启的日供养检查继续执行，缺粮惩罚不会因关停清除。',()=>ctx.economyAction('ecology_supply',{enabled,target_days}));};
 const actions=el('div','action-grid'),toggle=button(s.enabled?'停止发餐':'开启自动供养',()=>save(!s.enabled),'primary'),reserve=button('保存储备天数',()=>save(s.enabled),'secondary');toggle.disabled=reserve.disabled=!usable(ctx);actions.append(toggle,reserve);box.append(actions,el('p','muted',`每 ${s.day_seconds} 秒为一游戏日。基础灵膳优先于岗位餐；岗位餐另消耗，不替代基础餐。`),link('查看库存','#inventory','external-link'));return box;
}
function positionMealCards(ctx){
 const grid=el('div','recipe-grid');grid.dataset.systemIcon='ecology-position-meals';
 for(const row of Object.values(ctx.data.view.buildings||{}).filter(item=>item.slot_capacity>0)){
  const slot=current(ctx).position_meals[row.instance_id];grid.append(card('position-'+row.instance_id,row.name,[slot?name(ctx,slot.meal_id):'未设置岗位餐',slot?(slot.remaining_seconds>0?`已供餐 ${slot.covered_count} 人 · 余 ${slot.remaining_seconds} 秒`:'餐效到期，等待补餐'):'餐效作用于下一批工作'],()=>positionDetail(ctx,row.instance_id),resourceIcon(ctx,slot?.meal_id||'meal_qingling_rice')));
 }return grid;
}
function positionDetail(ctx,bid){
 const building=ctx.data.view.buildings[bid],box=el('section','panel'),grid=el('div','recipe-grid');
 const matches=meal=>meal.scope==='all'||meal.scope===building.definition_id||(meal.scope==='gather'&&['mine','forest','quarry'].includes(building.definition_id));
 for(const meal of current(ctx).meals.filter(row=>!row.basic&&matches(row))){const slot=current(ctx).position_meals[bid],selected=slot?.meal_id===meal.id;
  const pick=card('meal-choice-'+meal.id,meal.name,[meal.effect,'持续8游戏日，综合与专属互斥'],()=>confirmSheet(ctx,'设置岗位餐',`${building.name} 使用 ${meal.name}，按实际岗位人数发餐。需要基础口粮充足；当前任务保持开工速度。`,()=>ctx.economyAction('ecology_meal',{building_id:bid,meal_id:meal.id,enabled:!(selected&&slot.enabled)})),resourceIcon(ctx,meal.id,ctx.data.view.inventory[meal.id]?.quantity||0));pick.disabled=!usable(ctx);if(selected)pick.append(el('span','status-badge',slot.enabled?'已启用':'已停续餐'));grid.append(pick);
 }box.append(grid,el('p','muted','调入新增人数需要补餐；调出不退款，餐效留在岗位。关闭仅停止续餐，已付费餐效持续到期。'));ctx.sheet(building.name+' · 岗位餐',box);
}
export function renderFacilities(ctx){return productionSubset(ctx,['garden','pasture','spring','canteen'],row=>row.ecology_category==='facility');}

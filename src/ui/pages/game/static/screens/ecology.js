// Committed state only; every catalog uses the shared two-column recipe grid.
import {el,button,facts,empty,link} from '../components/dom.js';
import {quantityControls,confirmSheet,featureTab} from '../components/features.js';
import {resourceIcon} from '../components/item-icon.js';
import {renderProduction,workerControls} from './economy.js';
import {renderFacility} from './sect-management.js';

const current=ctx=>ctx.data.view.ecology;
const usable=ctx=>!ctx.busy&&current(ctx)?.available;
const building=(ctx,kind)=>current(ctx).farms.find(row=>row.building_kind===kind);
const name=(ctx,id)=>ctx.data.view.inventory[id]?.name||id;
const outputs=(ctx,values)=>Object.entries(values).map(([id,n])=>`${name(ctx,id)} ×${n}`).join('、')||'无';
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
export function renderGarden(ctx){
 const box=el('section','ecology-panel'),farm=building(ctx,'garden');box.dataset.systemIcon='ecology-garden';
 if(farm)box.append(facts([['可用田块',String(farm.capacity)],['农务弟子',`${farm.workers} 人`]]),workerControls(ctx,farm.building_id));
 box.append(el('p','muted','每位农务弟子使用一块田。新增灵植需要灵泉水，完成后整批入库。'),renderProduction(ctx,['garden']));return box;
}
export function renderHusbandry(ctx,kind){
 const farm=building(ctx,kind);if(!farm)return renderFacility(ctx,kind);
 const box=el('section','ecology-panel');box.dataset.systemIcon='ecology-'+kind;
 box.append(facts([['存栏占用',`${farm.occupied} / ${farm.capacity}`],['照料弟子',`${farm.workers} 人`]]),workerControls(ctx,farm.building_id));
 const tab=tabs(ctx,kind,[['stock','当前存栏'],['purchase',kind==='pasture'?'购入幼体':'投放鱼苗'],['feed','加工与营造']]);box.append(tab.node);
 const grid=el('div','recipe-grid');
 if(tab.selected==='stock'){
  const rows=current(ctx).batches.filter(row=>row.building_kind===kind);
  for(const row of rows)grid.append(card('batch-'+row.batch_id,row.name,[`存栏 ${row.count} · ${row.stage==='JUVENILE'?'幼体':row.stage==='READY'?'产物待领取':'已成熟'}`,row.reason,`当前周期 ${row.progress_percent}%`],()=>batchDetail(ctx,row.batch_id),resourceIcon(ctx,row.species_id)));
  if(!rows.length)box.append(empty('暂无存栏','先购入幼体或鱼苗，准备饲料并安排照料弟子。'));
  box.append(grid,el('p','muted','缺饲料暂停成长。加工占用照料岗位时，养殖暂停。成熟后再经过完整周期，才有首批可再生产物。'));
 }else if(tab.selected==='purchase'){
  for(const row of current(ctx).species.filter(row=>row.building_kind===kind))grid.append(card('species-'+row.id,row.name,[`购入 ${row.purchase_coins} 灵钱 / 只`,`容量 ${row.slots} / 只 · 成熟 ${row.days} 游戏日`,`${row.feed_name} ×${row.feed_quantity} / 只 / 周期`],()=>purchaseDetail(ctx,row.id),resourceIcon(ctx,row.id)));
  box.append(grid);
 }else box.append(renderProduction(ctx,[kind]));return box;
}
function purchaseDetail(ctx,speciesId){
 const row=current(ctx).species.find(item=>item.id===speciesId);if(!row)return;
 const box=el('section','panel');box.append(el('h3','',row.name),facts([['每只费用',`${row.purchase_coins} 灵钱`],['每只容量',String(row.slots)],['成熟周期',`${row.days} 游戏日`],['周期饲料',`${row.feed_name} ×${row.feed_quantity}`]]),el('p','',`成熟周期产物：${outputs(ctx,row.periodic_outputs)}`),el('p','',`一次性收获：${outputs(ctx,row.harvest_outputs)}`));
 box.append(quantityControls(ctx,{label:row.building_kind==='pasture'?'购入数量':'投苗数量',max:usable(ctx)?row.max_purchase:0,text:row.building_kind==='pasture'?'购入幼体':'投放鱼苗',onSubmit:count=>ctx.economyAction('ecology_buy',{building_id:row.building_id,species_id:row.id,count}),confirm:count=>`购入 ${row.name} ×${count}，支付 ${row.purchase_coins*count} 灵钱，占用 ${row.slots*count} 容量；成熟后才能收获。`}));
 if(row.blocking_reasons.length)box.append(el('p','blocking',row.blocking_reasons.join(' · ')));ctx.sheet(row.name,box);
}
function batchDetail(ctx,batchId){
 const row=current(ctx).batches.find(item=>item.batch_id===batchId);if(!row)return;
 const box=el('section','panel');box.append(el('h3','',row.name),facts([['存栏',String(row.count)],['状态',row.reason],['当前周期',`${row.progress_percent}%`],['已支付饲料',String(row.feed_paid)]]),el('p','',`周期采集：${outputs(ctx,row.periodic_outputs)}`),el('p','',`一次性收获：${outputs(ctx,row.harvest_outputs)}`));
 if(Object.keys(row.periodic_outputs).length)box.append(quantityControls(ctx,{label:'周期采集数量',max:usable(ctx)&&row.can_collect?row.count:0,text:'采集产物',onSubmit:count=>ctx.economyAction('ecology_collect',{batch_id:batchId,mode:'periodic',count})}));
 box.append(quantityControls(ctx,{label:row.building_kind==='pasture'?'屠宰数量':'捕捞数量',max:usable(ctx)&&row.can_harvest?row.count:0,text:row.building_kind==='pasture'?'屠宰收获':'捕捞收获',onSubmit:count=>ctx.economyAction('ecology_collect',{batch_id:batchId,mode:'harvest',count}),confirm:count=>`收获 ${row.name} ×${count}，这些个体将移出存栏；重新养殖需再次付费补栏并等待成熟。`}));
 box.append(el('p','muted','仓库不足时保留个体与待领取产物。同一结算窗口不能先周期采集，再屠宰或捕捞相同个体。'));ctx.sheet(row.name,box);
}
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

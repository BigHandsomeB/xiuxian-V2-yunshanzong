// Only selection and display live here; the server recomputes every cost and bonus.
import {el,button,empty} from '../components/dom.js';
import {confirmSheet} from '../components/features.js';
import {itemIcon,resourceIcon} from '../components/item-icon.js';
import {names} from './equipment.js';

const keyName=k=>k.replace(/_(milli|bps)$/,'');
const amount=(k,n)=>`${Number((n/(k.endsWith('_bps')?100:1000)).toFixed(2))}${k.endsWith('_bps')?'%':''}`;
const describe=stats=>Object.entries(stats).map(([k,n])=>`${names[keyName(k)]||keyName(k)} +${amount(k,n)}`).join(' · ');
function equipmentIcon(ctx,row,profile='compact'){
 const binding=ctx.data.presentation?.equipment_icons?.[row.definition_id]||{};
 return itemIcon({asset_id:row.asset_id,asset:binding.asset,fallback:'equipment',quality:row.quality,
  enhancement_level:row.enhancement?.level||0,refinement_element:row.refinement?.element,profile});
}
function close(){document.getElementById('sheet')?.close();}

export function renderRefinement(ctx){
 const host=el('section','refinement-panel'),view=ctx.data.view.refinement;
 host.dataset.id='equipment-refinement';host.append(el('h2','','装备精炼'));
 if(!view){host.append(empty('精炼尚未开放'));return host;}
 const state=ctx.ui.refinement??={instanceId:null,materials:[null,null,null]};
 const rows=ctx.data.view.equipment?.instances||[],row=rows.find(r=>r.instance_id===state.instanceId);
 const catalog=new Map(view.materials.map(m=>[m.resource_id,m]));
 // A removed instance or material never silently selects a replacement.
 const selected=state.materials.map(id=>catalog.get(id)||null),grid=el('div','refinement-slots');
 grid.dataset.id='refinement-slots';
 const selectEquipment=()=>{
  const body=el('div','inventory-grid');
  if(!rows.length)body.append(empty('暂无可精炼装备'));
  for(const item of rows){const choice=button('',()=>{state.instanceId=item.instance_id;close();ctx.redraw();},'inventory-item');
   choice.dataset.equipmentId=item.instance_id;choice.append(equipmentIcon(ctx,item),el('span','item-name',item.name),el('small','',item.equipped?'已穿戴':item.refinement?'已有精炼':'未精炼'));
   choice.disabled=ctx.busy||!!view.equipment[item.instance_id]?.blocking_reasons.length;body.append(choice);}
  ctx.sheet('选择精炼装备',body);
 };
 const equip=button('',selectEquipment,'refinement-slot refinement-slot--equipment');equip.dataset.id='refinement-equipment';equip.setAttribute('aria-label',row?'更换精炼装备：'+row.name:'放入精炼装备');equip.disabled=ctx.busy;
 equip.append(row?equipmentIcon(ctx,row,'detail'):el('span','refinement-plus','＋'),el('span','item-name',row?.name||'放入装备'));grid.append(equip);
 const pick=index=>{
  const body=el('div'),list=el('div','refinement-material-list'),search=el('input');
  search.type='search';search.placeholder='搜索矿石、材料或副本';search.setAttribute('aria-label','搜索精炼材料');
  body.append(el('p','muted',`${view.slots[index].name}发挥 ${view.slots[index].weight_bps/100}% 属性；重复材料会合并扣除。`));
  const clear=button('清空此格',()=>{state.materials[index]=null;close();ctx.redraw();},'secondary');clear.disabled=ctx.busy;body.append(clear,search,list);
  const render=()=>{list.replaceChildren();for(const material of view.materials){
   if(!`${material.name} ${material.source}`.includes(search.value.trim()))continue;
   const elsewhere=state.materials.filter((id,i)=>i!==index&&id===material.resource_id).length;
   const choice=button('',()=>{state.materials[index]=material.resource_id;close();ctx.redraw();},'panel refinement-material');choice.dataset.resourceId=material.resource_id;
   choice.append(resourceIcon(ctx,material.resource_id),el('strong','',material.name),el('small','muted',material.source),
    el('span','',describe(material.contributions[index])),el('small','muted',`每格 ${material.quantity} 份 · 可用 ${material.available} / 持有 ${material.current} · 保留 ${material.reserved}`));
   choice.disabled=ctx.busy||material.available<material.quantity*(elsewhere+1);list.append(choice);
  }if(!list.children.length)list.append(empty('没有匹配的材料'));};
  search.addEventListener('input',render);render();ctx.sheet('选择'+view.slots[index].name,body);
 };
 for(let i=0;i<3;i++){
  const material=selected[i],cell=button('',()=>pick(i),'refinement-slot');cell.dataset.id='refinement-material-'+i;
  cell.setAttribute('aria-label',`${view.slots[i].name}：${material?.name||'放入矿石或怪物材料'}`);cell.disabled=ctx.busy;
  cell.append(material?resourceIcon(ctx,material.resource_id):el('span','refinement-plus','＋'),el('span','item-name',material?.name||view.slots[i].name),el('small','muted',`${view.slots[i].weight_bps/100}%`));grid.append(cell);
 }
 host.append(el('p','muted','一件装备，至多三份材料组合。精炼必成；重新精炼替换上次加成，保留原属性与强化。'),grid);
 const bonus={},cost=new Map();
 selected.forEach((material,i)=>{if(!material)return;cost.set(material.resource_id,(cost.get(material.resource_id)||0)+material.quantity);
  for(const [key,n]of Object.entries(material.contributions[i]))bonus[key]=(bonus[key]||0)+n;
  const line=el('p','refinement-contribution',`${view.slots[i].name} · ${material.name}：${describe(material.contributions[i])}`);line.dataset.id='refinement-contribution-'+i;host.append(line);
 });
 const info=row?view.equipment[row.instance_id]:null,reasons=[...(info?.blocking_reasons||view.blocking_reasons)];
 if(!row)reasons.push('请放入一件装备');
 if(!selected.some(Boolean))reasons.push('至少放入一种矿石或怪物材料');
 for(const [rid,n]of cost)if(catalog.get(rid).available<n)reasons.push(catalog.get(rid).name+'不足或触及保留量');
 if(view.coins_available<view.coin_cost)reasons.push('灵钱不足或触及保留量');
 if(row?.refinement&&JSON.stringify(state.materials)===JSON.stringify(row.refinement.materials))reasons.push('与当前精炼相同，请更换材料或位置');
 if(row&&info){
  host.append(el('h3','','精炼前 → 精炼后'));
  const keys=new Set([...Object.keys(info.base_stats),...Object.keys(bonus),...Object.keys(row.refinement?.stats||{})]);
  for(const key of keys){const before=(info.base_stats[key]||0)+(row.refinement?.stats?.[key]||0),after=(info.base_stats[key]||0)+(bonus[key]||0);
   const text=el('p','',`${names[keyName(key)]||keyName(key)}：${amount(key,before)} → ${amount(key,after)}`);text.dataset.attributeId=key;host.append(text);}
  host.append(el('small','muted','此处为该件装备的完整属性；主角总属性仍遵循战斗上限。'));
 }
 const expense=el('div','refinement-cost');expense.dataset.id='refinement-cost';expense.append(el('h3','','本次消耗'),el('p','',`灵钱 ×${view.coin_cost}`));
 for(const [rid,n]of cost){const line=el('p','icon-label');line.dataset.resourceId=rid;line.append(resourceIcon(ctx,rid,n),el('span','',catalog.get(rid).name+' ×'+n));expense.append(line);}host.append(expense);
 for(const reason of new Set(reasons))host.append(el('p','blocking',reason));
 const submit=button(row?.refinement?'重新精炼':'开始精炼',()=>{
  if(ctx.busy||reasons.length)return;
  const payload={instance_id:row.instance_id,materials:[...state.materials]},text=[`为${row.name}精炼`,...Array.from(cost,([rid,n])=>catalog.get(rid).name+' ×'+n),`灵钱 ×${view.coin_cost}`,`加成：${describe(bonus)}`,row.refinement?'替换原精炼加成，旧材料不返还。':'材料消耗后不返还。'].join('；');
  confirmSheet(ctx,'确认精炼',text,()=>{if(ctx.busy)return;close();return ctx.economyAction('equipment_refine',payload);});
 },'primary block');submit.dataset.id='refinement-submit';submit.disabled=ctx.busy||reasons.length>0;host.append(submit);
 return host;
}

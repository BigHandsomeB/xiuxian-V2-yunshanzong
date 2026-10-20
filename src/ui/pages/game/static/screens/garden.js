// Five-column herb beds. All plot states, costs and progress come from the server.
import {el,button,facts,link} from '../components/dom.js';
import {resourceIcon,systemIcon} from '../components/item-icon.js';
import {requirementRow} from '../components/features.js';
import {workerControls,renderProduction,automationControls} from './economy.js';

const latest=(ctx,bid)=>ctx.data.view.ecology?.gardens?.find(row=>row.building_id===bid);
const active=ctx=>!ctx.busy&&!ctx.data.view.world?.paused&&!ctx.data.view.time?.pending;
const labels={UNCULTIVATED:'未开垦',EMPTY:'待种植',GROWING:'生长中',WAITING:'等待弟子',READY:'成熟待入库',REPLANT_WAIT:'等待续种'};

function plotDetail(ctx,bid,index){
 const garden=latest(ctx,bid),plot=garden?.plots.find(row=>row.index===index);if(!plot)return;
 const body=el('section','garden-detail');body.append(el('h3','',`第 ${index+1} 块灵田`));
 if(plot.state==='UNCULTIVATED'){
  body.append(el('p','','清理田块，整理灵土后即可种植。'),el('p','muted','此田块已随灵植园解锁，开垦不额外消耗材料。'));
  const reclaim=button('开垦此田',()=>ctx.economyAction('garden_reclaim',{building_id:bid,plot_index:index}),'primary block');reclaim.disabled=!active(ctx)||!garden.available;body.append(reclaim);
 }else if(plot.state==='EMPTY'){
  body.append(el('p','muted','选择灵植，查看这一块田的消耗与产出。'));
  const grid=el('div','recipe-grid garden-choices');
  for(const crop of garden.choices){
   const card=button('',()=>plantDetail(ctx,bid,index,crop.recipe_id),'panel recipe-card garden-choice');card.dataset.recipeId=crop.recipe_id;
   card.append(resourceIcon(ctx,crop.resource_id),el('strong','recipe-card-name',crop.name));
   card.append(el('span','recipe-meta',crop.can_plant?'可种植':crop.blocking_reasons.join(' · ')));grid.append(card);
  }
  body.append(grid);
 }else{
  body.append(resourceIcon(ctx,plot.resource_id,null,'detail'),el('h3','',plot.name),facts([['状态',labels[plot.state]],['生长进度',plot.progress_percent===undefined?'等待续种':`${plot.progress_percent}%`]]));
  if(plot.state==='WAITING')body.append(el('p','muted','请安排农务弟子，并等待原有批次或营造完成；灵植保留已获得的生长进度。'),workerControls(ctx,bid));
  else if(plot.state==='READY')body.append(el('p','muted','仓库空间不足，灵植已成熟并保留在田中。腾出仓容后自动入库。'),link('整理万宝库','#inventory','external-link'));
  else if(plot.state==='REPLANT_WAIT')body.append(el('p','blocking',plot.waiting_reason||'等待材料和空闲农务弟子，条件满足后自动续种。'));
  else body.append(el('p','muted',`预计剩余 ${plot.remaining_seconds} 秒。成熟后自动入库${plot.repeat?'并重复种植同一种灵植':'，田块恢复待种植'}。`));
  const repeat=button(plot.repeat?'停止重复种植':'开启重复种植',()=>ctx.economyAction('garden_repeat',{building_id:bid,plot_index:index,enabled:!plot.repeat}),'secondary block');repeat.disabled=!active(ctx);body.append(repeat);
 }
 ctx.sheet(plot.state==='EMPTY'?'选择灵植':`灵田 · ${labels[plot.state]}`,body);
}

function plantDetail(ctx,bid,index,recipeId){
 const crop=latest(ctx,bid)?.choices.find(row=>row.recipe_id===recipeId);if(!crop)return;
 const body=el('section','garden-detail');body.append(resourceIcon(ctx,crop.resource_id,null,'detail'),el('h3','',crop.name));
 for(const input of crop.inputs)body.append(requirementRow(input.name,input.quantity,input.current,resourceIcon(ctx,input.resource_id)));
 if(!crop.inputs.length)body.append(el('p','','无需种子或材料。'));
 body.append(facts([['照料弟子','1 人'],['基础生长时间',`${crop.duration_seconds} 秒`],['收获',crop.outputs.map(row=>`${row.name} ×${row.quantity}`).join('、')]]));
 const repeat=el('input');repeat.type='checkbox';repeat.checked=true;repeat.dataset.id='garden-repeat-choice';const repeatLabel=el('label','garden-repeat-choice','收获后重复种植');repeatLabel.prepend(repeat);body.append(repeatLabel,el('p','muted','每轮按这一块田重新扣材料。缺水、缺材料或弟子时暂停，条件满足后续种；满仓保留成熟灵植。'));
 if(crop.blocking_reasons.length)body.append(el('p','blocking',crop.blocking_reasons.join(' · ')));
 const plant=button('种植',()=>{
  const current=latest(ctx,bid),choice=current?.choices.find(row=>row.recipe_id===recipeId),plot=current?.plots.find(row=>row.index===index);
  if(!active(ctx)||!current?.available||!choice?.can_plant||!['EMPTY','REPLANT_WAIT'].includes(plot?.state)){plotDetail(ctx,bid,index);return;}
  ctx.economyAction('garden_plant',{building_id:bid,plot_index:index,recipe_id:recipeId,repeat:repeat.checked});
 },'primary block');plant.disabled=!active(ctx)||!crop.can_plant;body.append(plant,button('返回选择灵植',()=>plotDetail(ctx,bid,index),'secondary block'));ctx.sheet('种植灵植',body);
}

export function renderGardenPlots(ctx){
 const garden=ctx.data.view.ecology?.gardens?.[0];if(!garden)return renderProduction(ctx,['garden']);
 const bid=garden.building_id,box=el('section','garden-panel');box.dataset.id='garden-'+bid;
 const head=el('header','garden-heading');head.append(systemIcon(ctx,'ecology-garden'),el('h2','','宗门灵药圃'),el('span','garden-caption',`已开垦 ${garden.reclaimed} / ${garden.capacity}`));box.append(head);
 const grid=el('div','garden-grid');grid.setAttribute('aria-label','灵植田块，每行五格');
 for(const plot of garden.plots){
  const tile=button('',()=>plotDetail(ctx,bid,plot.index),'garden-plot garden-plot--'+plot.state.toLowerCase());tile.dataset.id=`garden-plot-${bid}-${plot.index}`;tile.dataset.plotState=plot.state;
  const description=`第 ${plot.index+1} 块灵田，${labels[plot.state]}${plot.name?'，'+plot.name+(plot.progress_percent===undefined?'':'，'+plot.progress_percent+'%'):''}`;tile.setAttribute('aria-label',description);tile.setAttribute('title',description);
  const ground=systemIcon(ctx,'garden_soil');ground.classList.add('garden-ground');ground.setAttribute('aria-hidden','true');tile.append(ground);
  if(plot.state==='EMPTY'){const plus=el('span','garden-plus','+');plus.setAttribute('aria-hidden','true');tile.append(plus);}
  else if(plot.resource_id){const plant=resourceIcon(ctx,plot.resource_id);plant.classList.add('garden-plant');tile.append(plant);tile.append(el('span','garden-growth',plot.state==='READY'?'待入库':plot.state==='WAITING'?'待照料':plot.state==='REPLANT_WAIT'?'待续种':`${plot.progress_percent}%`));}
  else tile.append(el('span','garden-reclaim-label','开垦'));
  grid.append(tile);
 }
 // Show one future row, rounded to the same five-column layout. It grants no capacity.
 const locked=garden.expandable===false?0:5-(garden.capacity%5);for(let n=0;n<locked;n++){
  const tile=button('',()=>{const body=el('section');body.append(el('p','','升级灵植园可解锁更多可开垦田块；营造设施也可扩充容量。'),link('前往营造司','#building/construction','external-link'));ctx.sheet('田块尚未解锁',body);},'garden-plot garden-plot--locked');tile.dataset.id=`garden-locked-${bid}-${n}`;tile.setAttribute('aria-label','未解锁田块，升级灵植园后可开垦');tile.append(el('span','garden-lock','锁'));grid.append(tile);
 }
 box.append(grid,el('p','garden-hint','空地开垦后点击 ＋ 选择灵植。升级灵植园，可开垦更多田块。'));
 const farm=ctx.data.view.ecology.farms.find(row=>row.building_id===bid),growing=garden.plots.filter(row=>['GROWING','WAITING'].includes(row.state)).length;
 box.append(facts([['农务弟子',`${farm?.workers||0} 人`],['生长中的灵田',`${growing} 块`]]),workerControls(ctx,bid),link('升级灵植园','#building/construction','external-link'));
 box.append(el('p','muted','每位农务弟子照料一块田；成熟自动入库并重复种植，可在田块详情关闭续种。'));
 if(garden.legacy_job||garden.auto_enabled){
  const legacy=el('details','feature-rules');legacy.dataset.id='garden-legacy';legacy.open=true;legacy.append(el('summary','','原有整批生产'),el('p','muted','原有任务和自动策略已保留。逐格种植前，请关闭整批自动生产并等待当前批次完成。'));
  const configured=ctx.data.view.economy?.automation?.production?.[bid];if(configured)legacy.append(automationControls(ctx,bid,configured.recipe_id));
  if(garden.auto_enabled){const stop=button('关闭整批自动生产',()=>{const policy=ctx.data.view.economy?.automation?.production?.[bid];if(policy)ctx.economyAction('automation_production',{building_id:bid,policy:{enabled:false,recipe_id:policy.recipe_id,target:policy.target}});},'secondary');stop.disabled=!active(ctx);legacy.append(stop);}
  if(garden.legacy_job)legacy.append(renderProduction(ctx,['garden']));box.append(legacy);
 }
 return box;
}

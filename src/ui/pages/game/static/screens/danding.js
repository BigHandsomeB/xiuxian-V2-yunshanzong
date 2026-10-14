import {systemIcon,iconLabel} from '../components/item-icon.js';
import {jobProgress,productionSnapshot} from '../components/job-progress.js';
import {el,button,facts} from '../components/dom.js';
import {resourceIcon,itemIcon} from '../components/item-icon.js';
const reasons={WORLD_PAUSED:'世界已暂停，请先继续运行',NO_ASSIGNED_WORKERS:'请先安排炼丹弟子',BUILDING_NOT_READY:'建筑尚未开放',BUILDING_BUSY:'丹炉使用中',PENDING_SETTLEMENT:'正在续算离线进度',INSUFFICIENT_INPUTS:'材料不足',INVENTORY_CAPACITY:'仓容不足',PROGRESSION_DEFERRED:'条件尚未开放'};
function amounts(ctx,values={}){const list=el('div','resource-pairs');for(const [id,n]of Object.entries(values)){const pair=el('span','resource-pair');pair.append(resourceIcon(ctx,id),el('span','',`${ctx.data.view.inventory[id]?.name||id} × ${n}`));list.append(pair);}return list;}
export function renderAlchemy(ctx){const v=ctx.data.view,a=v.alchemy,c=a.current,r=a.recipes[0],node=el('div','alchemy-panel');
 node.append(systemIcon(ctx,'production'),facts([['建筑等级',`Lv${v.building.level}`],['当前状态',({WORKING:'炼制中',COMPLETE:'上一炉已入库',OUTPUT_READY:'产物等待入库',IDLE:'待开炉'})[c.status]||'待开炉'],['炼丹岗位',`${v.work.assigned_count} 人 · 工作中 ${v.work.working_count} 人`]]));
 node.append(el('h2','','炉旁库存'));node.append(amounts(ctx,Object.fromEntries(Object.entries(v.inventory).filter(([id])=>id==='herb'||id==='pill').map(([id,row])=>[id,row.quantity]))));
 if(!r){node.append(el('p','','暂无可用丹方'));return node;}
 const recipe=el('article','recipe-scroll'),title=el('div','recipe-title');title.append(resourceIcon(ctx,Object.keys(r.outputs_per_base_worker)[0]),el('h2','',r.display_name_zh));recipe.append(title);
 recipe.append(el('small','','每位工人所需'),amounts(ctx,r.inputs_per_worker),el('small','','每位基础工人产出'),amounts(ctx,r.outputs_per_base_worker));
 recipe.append(facts([['炼制时间',`${r.duration_ms/1000} 秒`],['所需工人',`至少 ${r.minimum_assigned_workers} 人`],['建筑要求',`Lv${r.required_building_level}`]]));
 if(c.status==='WORKING'){
 const furnace=el('div',v.world?.paused?'furnace-feedback paused':'furnace-feedback');furnace.append(itemIcon({fallback:'building'}),el('span','',v.world?.paused?'世界暂停 · 丹火静候':'丹火温养 · 炼制中'));recipe.append(furnace);
 recipe.append(jobProgress(productionSnapshot(ctx,c.job,r.duration_ms*1000,c.remaining_ms,'真实炼丹进度')));
 }else if(c.status==='COMPLETE'){recipe.append(el('p','success-text','上一炉已炼成，产物已入库。'));}
 else if(c.status==='OUTPUT_READY'){recipe.append(el('p','','丹已成，仓容不足，待产物入库。'));const retry=button('重试入库',()=>ctx.sync(true),'primary block');retry.disabled=ctx.busy||v.world?.paused;recipe.append(retry);}
 if(!['WORKING','OUTPUT_READY'].includes(c.status)){const start=button('开始炼制',()=>ctx.action('start'),'primary block');start.id='alchemy-start';start.disabled=ctx.busy||!r.can_start;recipe.append(start);}
 const blocked=(r.blocking_reasons||[]).filter(x=>x!=='BUILDING_BUSY').map(x=>reasons[x]||'当前条件未满足');if(blocked.length)recipe.append(el('p','blocking',blocked.join(' · ')));node.append(recipe);
 const jobs=el('div','assignment-actions');const assign=button('安排炼丹弟子',()=>ctx.action('assign'),'secondary'),unassign=button('解除岗位',()=>ctx.action('unassign'),'quiet');assign.disabled=ctx.busy||!v.work.can_assign;unassign.disabled=ctx.busy||!v.work.can_unassign;jobs.append(assign,unassign);node.append(jobs);return node;
}

import {el,heading,facts,button,link,empty} from '../components/dom.js';
import {workforceSummary} from './disciples.js';
import {workerControls} from './economy.js';
export function render(ctx){const view=ctx.data.view,s=workforceSummary(view),selected=view.buildings[ctx.route.id],node=el('section');node.append(heading(selected?.name||'选择工作建筑','','#disciples'),facts([['未分配弟子',`${s.idle} 人`],['已分配弟子',`${s.occupied} 人`]]));
 if(view.recipe_staffing){
  const model=view.recipe_staffing,entries=model.buildings;
  if(!selected){
   for(const entry of entries){const card=link('',`#disciple_detail/${encodeURIComponent(entry.building_id)}`,'disciple-card');card.dataset.building=entry.building_id;card.append(el('strong','card-title',view.buildings[entry.building_id]?.name||entry.name),el('span','',`${entry.occupied} 人 · ${entry.recipe_mode?'查看配方':'查看岗位'}`));node.append(card);}
   if(!entries.length)node.append(empty('暂无可安排的工作建筑'));return node;
  }
  const entry=entries.find(b=>b.building_id===selected.instance_id);
  if(!entry){node.append(empty('此建筑没有可安排的工作岗位'));return node;}
  node.append(facts([['当前安排',`${entry.assigned} 人`],['实际占用',`${entry.occupied} / ${entry.capacity} 人`]]));
  if(entry.pending_release)node.append(el('p','muted',`${entry.pending_release} 人将在本轮完成后释放。`));
  if(entry.recipe_mode)node.append(el('p','muted','每点一次加减一人。各配方分别安排，多配方按现有批次轮流生产；本轮人数与产出保持，调整从后续批次生效。'),el('p','muted','新派工配方默认库存目标30，可在建筑配方中修改或关闭自动生产。'));
  if(model.blocked)node.append(el('p','blocking',view.world?.paused?'世界已暂停，请恢复后安排弟子。':'进度续算中，完成后可调整人数。'));
  const list=el('div','recipe-work-list');list.dataset.id='recipe-work-list';
  for(const recipe of entry.rows){
   const row=el('section','row recipe-work-row');row.dataset.id=`recipe-work:${entry.building_id}:${recipe.recipe_id||'shared'}`;
   const description=el('div','recipe-work-info');description.append(el('strong','card-title',recipe.name),el('p','recipe-work-count',`安排 ${recipe.count} 人${recipe.working?` · 本轮 ${recipe.working} 人`:''}`));
   description.append(el('small','muted',recipe.status));if(recipe.pending_release)description.append(el('small','muted',`本轮完成后释放 ${recipe.pending_release} 人`));
   const controls=el('div','work-stepper');
   for(const [delta,text,enabled]of [[-1,'−',recipe.can_remove],[1,'＋',recipe.can_add]]){
    const control=button(text,()=>{if(ctx.busy)return;return ctx.economyAction('work_recipe_adjust',{building_id:entry.building_id,recipe_id:recipe.recipe_id,delta});},'secondary work-stepper-button');
    control.setAttribute('aria-label',`${delta===1?'增加':'减少'}${recipe.name}一名弟子`);control.dataset.id=`work-step:${entry.building_id}:${recipe.recipe_id||'shared'}:${delta}`;
    control.disabled=ctx.busy||model.blocked||!enabled;controls.append(control);
   }
   row.append(description,controls);list.append(row);
  }
  if(!entry.rows.length)list.append(empty('暂无已解锁的生产配方'));node.append(list);return node;
 }
 const buildings=selected?[selected]:Object.values(view.buildings).filter(b=>b.slot_capacity>0);
 for(const b of buildings){const job=s.jobs.find(j=>j.building_id===b.instance_id),row=el('section','panel');row.dataset.building=b.instance_id;row.append(el('h2','',b.name),facts([['当前岗位',`${job?.count||0} 人`],['岗位容量',`${b.slot_capacity} 人`]]));if(job&&job.count>job.assigned)row.append(el('p','muted','已解除的弟子完成当前工作后释放。'));row.append(workerControls(ctx,b.instance_id));node.append(row);}
 if(!buildings.length)node.append(el('p','muted','暂无可安排的工作岗位'));return node;
}

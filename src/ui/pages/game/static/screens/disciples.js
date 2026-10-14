import {systemIcon} from '../components/item-icon.js';
import {el,heading,link,empty,facts} from '../components/dom.js';
export function discipleGroups(view){return view.disciples?.groups||[];}
export function workforceSummary(view){
 const groups=discipleGroups(view),jobs=new Map();let total=0,idle=0;
 for(const g of groups){total+=g.count;idle+=g.available_count;for(const [id,count]of Object.entries(g.allocations||{})){const row=jobs.get(id)||{building_id:id,name:view.buildings[id]?.name||'宗门工作',count:0,assigned:0};row.count+=count;row.assigned+=(g.assignments||[]).find(a=>a.building_id===id)?.count||0;jobs.set(id,row);}}
 return {total,idle,occupied:total-idle,jobs:[...jobs.values()]};
}
export function render(ctx){const node=el('section','disciples-screen'),s=workforceSummary(ctx.data.view);if(!ctx.embedded)node.append(heading('弟子居','安排弟子，共营宗门。'));
 node.append(facts([['未分配弟子',`${s.idle} 人`],['已分配弟子',`${s.occupied} 人`]]));
 if(!s.total){node.append(empty('暂无弟子'));return node;}
 for(const job of s.jobs){const card=link('',`#disciple_detail/${encodeURIComponent(job.building_id)}`,'disciple-card');card.dataset.id=job.building_id;card.append(systemIcon(ctx,'disciples'),el('strong','card-title',job.name),el('span','',`${job.count} 人`));if(job.count>job.assigned)card.append(el('small','muted','含完成当前工作后释放的弟子'));node.append(card);}
 if(!s.jobs.length)node.append(el('p','muted','暂无弟子被安排工作'));
 node.append(link('分配弟子','#disciple_detail/pool','external-link'));return node;
}

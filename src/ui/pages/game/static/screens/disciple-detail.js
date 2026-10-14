import {el,heading,facts} from '../components/dom.js';
import {workforceSummary} from './disciples.js';
import {workerControls} from './economy.js';
export function render(ctx){const view=ctx.data.view,s=workforceSummary(view),selected=view.buildings[ctx.route.id],node=el('section');node.append(heading(selected?.name||'弟子分配','','#disciples'),facts([['未分配弟子',`${s.idle} 人`],['已分配弟子',`${s.occupied} 人`]]));
 const buildings=selected?[selected]:Object.values(view.buildings).filter(b=>b.slot_capacity>0);
 for(const b of buildings){const job=s.jobs.find(j=>j.building_id===b.instance_id),row=el('section','panel');row.dataset.building=b.instance_id;row.append(el('h2','',b.name),facts([['当前岗位',`${job?.count||0} 人`],['岗位容量',`${b.slot_capacity} 人`]]));if(job&&job.count>job.assigned)row.append(el('p','muted','已解除的弟子完成当前工作后释放。'));row.append(workerControls(ctx,b.instance_id));node.append(row);}
 if(!buildings.length)node.append(el('p','muted','暂无可安排的工作岗位'));return node;
}

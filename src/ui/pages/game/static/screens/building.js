import {patchPanel} from '../components/patch.js';
import {animateJobs} from '../components/job-progress.js';
import {workerControls} from './economy.js';
import {el,heading,empty,facts,link} from '../components/dom.js';
import {itemIcon} from '../components/item-icon.js';
import {entryFor,definitionFor} from '../buildings.js';
import {adapterFor,profiles} from '../building-adapters.js';
import {featureTab,buildingStatus,requirementRow,detailSheet} from '../components/features.js';
function build(ctx){const entry=entryFor(ctx.route.id);if(!entry){const node=el('section');node.append(heading('建筑','','#sect'),empty('未找到这处建筑'));return node;}
 const descriptions={garden:'管理灵植田块，种植食材和饲料作物；以真实灵泉水、弟子和生产时间完成收获。',kitchen:'制作基础灵膳和岗位餐，按游戏日供养弟子；岗位增益作用于新批次工作。',pasture:'付费购入灵兽幼体，准备饲料并安排照料；周期采集与屠宰分别结算。',abyss:'付费投放水产苗，管理池塘容量、饲料、周期产物与捕捞；灵泉水采集共享本建筑作业位。'};const profile=ctx.data.view.ecology&&descriptions[entry.id]?{...profiles[entry.id],description:descriptions[entry.id]}:profiles[entry.id],adapter=adapterFor(entry.id),node=el('section','building-screen');node.append(heading(entry.name,profile.flavor,'#sect'));
 const definition=definitionFor(entry.id),rows=Object.values(ctx.data.view.buildings||{}).filter(r=>ctx.route.id==='mountain'?['mine','forest','quarry'].includes(r.definition_id):ctx.route.id==='forge'?['forge','smelter'].includes(r.definition_id):r.definition_id===definition),actual=rows[0],visual=ctx.data.presentation?.building_icons?.[definition]||{};
 const identity=el('div',`building-identity ${entry.tone}`);identity.append(itemIcon({fallback:'building',asset_id:visual.asset_id,asset:visual.asset}),el('strong','',entry.name),buildingStatus(ctx.data.view.world?.paused?'PAUSED':(adapter.kind==='real'||adapter.realWhen?.(ctx))?'AVAILABLE':'COMING_SOON'));node.append(identity,facts([['建筑等级',actual?`Lv${actual.level}`:'尚未建设'],['当前状态',ctx.data.view.world?.paused?'世界暂停':actual?'已建成':ctx.data.view.sect_services&&['gate','hall'].includes(entry.id)?'宗门服务已开放':'入口预留']]));
 const keys=ctx.ui.buildingTabs??={},tab=keys[entry.id]||'function';node.append(featureTab([['function','功能'],['requirements','资源需求'],['workers','人员'],['info','说明']],tab,key=>{keys[entry.id]=key;ctx.redraw();}));
 if(tab==='function'){node.append(adapter.render(ctx));}
 else if(tab==='requirements'){node.append(el('h2','','资源需求'),el('p','muted','生产和功能消耗见功能页；建筑升级统一在营造司查看和操作。'),link('前往营造司','#building/construction','external-link'),link('查看真实库存','#inventory','external-link'));}
 else if(tab==='workers'){if(entry.id==='house')node.append(link('查看弟子经营与分配','#disciples','external-link'));if(ctx.data.view.economy){for(const r of rows)if(r.slot_capacity){node.append(link(`${r.name} · ${r.occupied_count} 人`, '#disciple_detail/'+encodeURIComponent(r.instance_id),'worker-slot'),workerControls(ctx,r.instance_id));}}else node.append(el('p','muted','可用岗位操作在丹鼎阁；其余人员分配未开放。'));}
 else{node.append(el('p','',profile.description));const details=el('details','feature-rules');details.append(el('summary','','展开规则'),el('p','','已实现功能读取真实存档；预留功能不会创建任务、产物或奖励。世界暂停时只能浏览，恢复后才可执行玩法操作。'));node.append(details);}
 return node;
}

export function render(ctx){const node=build(ctx);if(['alchemy','garden','mountain','forge','kitchen','pasture','abyss'].includes(ctx.route.id))ctx.afterMount=()=>{const animator=animateJobs(node);const cleanup=()=>animator.dispose();cleanup.dispose=cleanup;cleanup.update=(data,busy)=>{ctx.data=data;ctx.busy=busy;patchPanel(node,build(ctx));animator.refresh();};cleanup.suspend=()=>animator.suspend();cleanup.resume=()=>animator.resume();animator.refresh();return cleanup;};return node;}

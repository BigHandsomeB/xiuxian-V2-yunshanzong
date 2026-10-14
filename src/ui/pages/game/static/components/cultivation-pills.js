import {el,button} from './dom.js';
import {resourceIcon} from './item-icon.js';
import {quantityControls} from './features.js';
export function usePill(ctx,command,payload){
 if(ctx.busy)return;
 document.getElementById('sheet')?.close();
 return ctx.cultivationAction(command,payload);
}
export function cultivationPill(ctx,pill){
 const box=el('section','panel');box.dataset.resourceId=pill.item_id;
 const v=ctx.data.view.cultivation,paused=ctx.data.view.world?.paused;
 box.append(resourceIcon(ctx,pill.item_id,pill.quantity),el('h3','',pill.name),el('p','',`每枚增加 ${pill.gain} 修为（5分钟基础击杀修为）；第${pill.minimum_level}–${pill.maximum_level}级有效，超出不消耗。`));
 const max=pill.can_use&&!paused?pill.quantity:0;
 const action=button(paused?'世界已暂停':'服用'+pill.name,()=>usePill(ctx,'cultivation_use_pill',{item_id:pill.item_id}),'primary block');
 action.dataset.usePill=pill.item_id;action.disabled=ctx.busy||!max;box.append(action);
 box.append(quantityControls(ctx,{label:'服用数量',max,text:'批量服用'+pill.name,onSubmit:count=>usePill(ctx,'cultivation_use_pill',{item_id:pill.item_id,count}),confirm:count=>`服用最多 ${pill.name} ${count} 枚；按有效等级区间、每日衰减与境界上限结算，无效部分不消耗。`}));
 for(const reason of pill.blocking_reasons||[])box.append(el('p','blocking',reason.message));
 return box;
}

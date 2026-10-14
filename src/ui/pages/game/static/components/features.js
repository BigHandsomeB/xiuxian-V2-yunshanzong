import {el,button,empty,status} from './dom.js';
import {resourceIcon,itemIcon,portraitIcon} from './item-icon.js';
export const featureLabels={AVAILABLE:'可用',LOCKED:'未解锁',COMING_SOON:'后续开放',BLOCKED:'条件不足',ACTIVE:'进行中',PAUSED:'世界暂停'};
export function buildingStatus(state){return status(featureLabels[state]||featureLabels.COMING_SOON);}
export function detailSheet(ctx,title,description,state='COMING_SOON'){const body=el('div','feature-detail');body.append(buildingStatus(state),el('p','',description));if(state==='COMING_SOON'||state==='LOCKED')body.append(el('p','muted','尚未开放'));ctx.sheet(title,body);return body;}
export function featureTab(items,selected,onSelect){const bar=el('div','feature-tabs');bar.setAttribute('role','tablist');for(const [id,name]of items){const tab=button(name,()=>onSelect(id),'filter-chip');tab.setAttribute('role','tab');tab.setAttribute('aria-selected',String(id===selected));bar.append(tab);}return bar;}
export function actionButton(ctx,name,fn,{state='AVAILABLE',reason='此功能尚未开放'}={}){const btn=button(name,fn||(()=>detailSheet(ctx,name,reason,state)),'secondary');btn.disabled=ctx.busy||state==='PAUSED';return btn;}
export function resourceAmount(ctx,id,n){const row=el('span','resource-pair');row.append(resourceIcon(ctx,id,n),el('span','',ctx.data.view.inventory[id]?.name||'资源'));return row;}
export function requirementRow(name,needed,current,icon=null){const row=el('div','requirement-row');if(icon)row.append(icon);row.append(el('strong','requirement-name',name),el('span','requirement-amount',`${current} / ${needed}`),buildingStatus(current>=needed?'AVAILABLE':'BLOCKED'));return row;}
export function productionSlot(ctx,name,description){const row=button('',()=>detailSheet(ctx,name,description),'production-slot');row.append(itemIcon({fallback:'resource'}),el('span','',name),buildingStatus('COMING_SOON'));return row;}
export function workerSlot(ctx,group){const row=button('',()=>{location.hash='#disciple_detail/'+encodeURIComponent(group.instance_id);},'worker-slot');row.append(portraitIcon(ctx,group),el('span','',`${group.name} · ${group.count}人`));return row;}
export function queueRow(ctx,name='生产队列'){const row=button('',()=>detailSheet(ctx,name,'队列位置已预留。对应生产规则尚未开放，不会产生任务、进度或产物。'),'queue-row');row.append(el('span','',name),el('small','','尚未开放'));return row;}
export function recipeCard(ctx,title,description){const row=button('',()=>detailSheet(ctx,title,description),'recipe-card');row.append(itemIcon({fallback:'resource'}),el('strong','',title),buildingStatus('COMING_SOON'));return row;}
export function progressBar(value,max,label){const row=el('progress');row.value=value;row.max=max;row.setAttribute('aria-label',label);return row;}
export function lockedState(ctx,title,description){const row=el('div','locked-feature');row.append(empty('尚未开放',description),actionButton(ctx,'查看'+title,()=>detailSheet(ctx,title,description)));return row;}
export function confirmSheet(ctx,title,description,submit){const body=el('div');body.append(el('p','',description),button('确认',submit,'primary'));ctx.sheet(title,body);}

// Quantity is UI input only; the authoritative command validates the whole batch.
export function quantityControls(ctx,{label='数量',min=1,max=1,onSubmit,text='确认数量',confirm=null}={}){
 const body=el('div','quantity-controls'),field=el('label','policy-field',label),input=el('input');
 input.type='number';input.min=String(min);input.max=String(max);input.step='1';input.value=String(min);input.inputMode='numeric';input.setAttribute('aria-label',label);field.append(input);
 const chips=el('div','inventory-filters');chips.setAttribute('role','group');chips.setAttribute('aria-label','快捷数量');
 const submit=button(text,()=>{const n=Number(input.value);if(!Number.isSafeInteger(n)||n<min||n>max)return;if(confirm)confirmSheet(ctx,text,confirm(n),()=>onSubmit(n));else onSubmit(n);},'primary');
 function update(){const n=Number(input.value);submit.disabled=ctx.busy||!Number.isSafeInteger(n)||n<min||n>max;input.setAttribute('aria-invalid',String(!Number.isSafeInteger(n)||n<min||n>max));}
 for(const n of [1,10]){const chip=button('×'+n,()=>{input.value=String(n);update();},'filter-chip');chip.disabled=ctx.busy||(n<min||n>max);chips.append(chip);}
 input.disabled=ctx.busy||max<min;input.addEventListener('input',update);input.addEventListener('change',update);update();body.append(chips,field,submit);return body;
}

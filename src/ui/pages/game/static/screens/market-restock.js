import {el,button} from '../components/dom.js';
import {confirmSheet} from '../components/features.js';
import {resourceIcon} from '../components/item-icon.js';
import {workerControls} from './economy.js';

const available=ctx=>!ctx.busy&&!ctx.data.view.time.pending;

function edit(ctx,row=null){
 const current=ctx.data.view.sect_services.restock,body=el('section','panel'),select=el('select');
 select.setAttribute('aria-label','购买材料');
 const choices=current.eligible.filter(r=>row?r.resource_id===row.resource_id:!current.rows.some(p=>p.resource_id===r.resource_id));
 for(const r of choices){const option=el('option','',r.name);option.value=r.resource_id;select.append(option);}
 select.value=row?.resource_id||choices[0]?.resource_id||'';select.disabled=!!row;
 const material=el('label','policy-field','购买材料');material.append(select);
 const target=el('input');target.type='number';target.min='1';target.max='10000';target.step='1';target.value=String(row?.target||100);target.setAttribute('aria-label','库存保有量');
 const label=el('label','policy-field','库存保有量');label.append(target);
 const error=el('p','blocking');error.setAttribute('role','status');
 const save=button(row?'保存保有量':'保存购买清单',()=>{
  const value=Number(target.value);
  if(!select.value||!Number.isSafeInteger(value)||value<1||value>10000){error.textContent='请选择材料，保有量填写1至10000的整数。';return;}
  ctx.economyAction('market_restock_set',{resource_id:select.value,target:value});
 },'primary block');save.disabled=!available(ctx)||!choices.length;
 body.append(material,label,el('p','muted','库存低于保有量时，按当日价格自动购买差额；受商品上架、每日限购、灵钱和仓库空间限制。'),error,save);
 ctx.sheet(row?'修改购买清单':'新增购买清单',body);return body;
}

export function renderRestock(ctx){
 const current=ctx.data.view.sect_services.restock,box=el('section','panel');box.dataset.id='market-restock';
 box.append(el('h2','','自动补货'));
 if(!current){box.append(el('p','muted','自动补货尚未开放'));return box;}
 box.append(el('p','',`万宝楼弟子 ${current.workers} 人`),el('p','muted','至少分配1名弟子执行全部清单。库存下降后自动补足，缺货或资金、仓容不足时等待；世界暂停时停止，离线结算同样执行。'));
 const buildings=Object.values(ctx.data.view.buildings).filter(r=>r.definition_id==='trading');
 for(const b of buildings)box.append(workerControls(ctx,b.instance_id));
 if(!buildings.length)box.append(el('p','muted','先新增购买清单，再为万宝楼分配弟子。'));
 const add=button('新增购买清单',()=>edit(ctx),'primary');add.disabled=!available(ctx)||!current.eligible.some(r=>!current.rows.some(p=>p.resource_id===r.resource_id));box.append(add);
 if(!current.rows.length)box.append(el('p','muted','暂无购买清单，选择已解锁材料并设置库存保有量。'));
 for(const r of current.rows){
  const row=el('section','row');row.dataset.id='restock-'+r.resource_id;
  row.append(resourceIcon(ctx,r.resource_id,r.quantity),el('h3','',r.name),el('p','',`库存 ${r.quantity} / 保有量 ${r.target}`),el('p','muted',r.reason));
  const actions=el('div','action-grid'),change=button('修改保有量',()=>edit(ctx,r),'secondary'),remove=button('删除清单',()=>confirmSheet(ctx,'删除购买清单',`停止自动购买${r.name}，已有库存保留。`,()=>ctx.economyAction('market_restock_delete',{resource_id:r.resource_id})),'secondary');
  change.disabled=remove.disabled=!available(ctx);actions.append(change,remove);row.append(actions);box.append(row);
 }
 if(current.log.length){const recent=el('details');recent.dataset.id='restock-log';recent.append(el('summary','','近期自动购买'));for(const r of current.log.slice(-5).reverse())recent.append(el('p','',`${r.name} ×${r.quantity} · ${r.coins} 灵钱`));box.append(recent);}
 return box;
}

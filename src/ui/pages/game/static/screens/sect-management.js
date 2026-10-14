import {renderCommissions,renderContributionExchange} from './activities.js';
import {patchPanel} from '../components/patch.js';
import {deferIconLoads,activateIconLoads} from '../components/icon-loading.js';
import {renderOrders,renderAuctions} from './commerce.js';
import {renderTechniqueLibrary} from './techniques.js';
import {el,button,facts,link} from '../components/dom.js';
import {quantityControls,confirmSheet,featureTab} from '../components/features.js';
import {resourceIcon,systemIcon,iconLabel} from '../components/item-icon.js';
import {renderProduction,recipeCard} from './economy.js';
import {renderTrade} from './equipment.js';
const available=ctx=>!ctx.busy&&!ctx.data.view.time.pending;
function housingFacts(h){return facts([['弟子',String(h.people)],['住房床位',String(h.beds)],['当前人数上限',String(h.limit)],['招募预留',String(h.reserved)],['可招募',String(h.available)],['岗位占用',String(h.occupied)],['待命',String(h.idle)]]);}
export function renderGate(ctx){
 const h=ctx.data.view.sect_services.housing,box=el('section','economy-panel'),summary=el('section','panel');box.dataset.systemIcon='sect-recruit';
 summary.append(iconLabel(ctx,'disciples','宗门弟子'),housingFacts(h));box.append(el('h2','','山门招募'),summary);
 const grid=el('div','recipe-grid'),inputs=Object.entries(h.recruit_cost).map(([id,n])=>({resource_id:id,name:ctx.data.view.inventory[id]?.name||id,quantity:n}));
 const card=recipeCard(ctx,{name:'招募弟子',id:'sect-recruit',inputs,outputs:[systemIcon(ctx,'disciples')],duration:h.recruit_duration_seconds+' 秒 / 人',workers:'完成后加入待命弟子',onClick:()=>recruitDetail(ctx)});
 if(h.recruit)card.append(el('span','status-badge',`招募 ${h.recruit.count} 人中 · 剩余 ${h.recruit_remaining_seconds} 秒`));
 grid.append(card);box.append(grid,el('p','muted','招募完成后加入未分配弟子，可前往弟子居安排岗位。'),link('前往弟子居安排岗位','#building/house','external-link'));return box;
}
function recruitDetail(ctx){
 const h=ctx.data.view.sect_services.housing,body=el('section','panel');body.dataset.systemIcon='sect-recruit-count';
 body.append(iconLabel(ctx,'disciples','招募宗门弟子'),el('h3','','每名弟子所需材料'));
 const costs=el('div','resource-pairs');for(const [id,n]of Object.entries(h.recruit_cost)){const pair=el('span','resource-pair');pair.append(resourceIcon(ctx,id,n),el('span','',ctx.data.view.inventory[id]?.name||id));costs.append(pair);}body.append(costs,facts([['每人招募时间',h.recruit_duration_seconds+' 秒'],['可用名额',String(h.available)],['本次最多',String(h.max_recruit_count)]]));
 const affordable=Math.min(...Object.entries(h.recruit_cost).map(([id,n])=>Math.floor((ctx.data.view.inventory[id]?.quantity||0)/n))),max=h.can_recruit&&available(ctx)?Math.max(0,Math.min(h.available,h.max_recruit_count,affordable)):0;
 if(h.recruit)body.append(el('p','blocking',`已有招募正在进行：${h.recruit.count} 人，剩余 ${h.recruit_remaining_seconds} 秒。`));
 else if(!h.available)body.append(el('p','blocking','住房或宗门人数名额不足，请扩建弟子居或提升宗门等级。'));
 else if(!affordable)body.append(el('p','blocking',Object.keys(h.recruit_cost).map(id=>ctx.data.view.inventory[id]?.name||id).join('或')+'不足。'));
 else if(ctx.data.view.time.pending)body.append(el('p','blocking','宗门进度正在续算，请稍候。'));
 body.append(quantityControls(ctx,{label:'招募人数',max,text:'招募',onSubmit:count=>ctx.economyAction('sect_recruit',{count}),confirm:count=>`招募 ${count} 人，预留床位，扣除 ${Object.entries(h.recruit_cost).map(([id,n])=>(ctx.data.view.inventory[id]?.name||id)+' ×'+n*count).join('、')}；总计 ${h.recruit_duration_seconds*count} 秒。`}));ctx.sheet('山门招募',body);return body;
}
export function renderHousing(ctx){const box=el('section','panel'),h=ctx.data.view.sect_services.housing;box.dataset.systemIcon='sect-housing';box.append(el('h2','','弟子经营'));if(h.people>h.limit)box.append(el('p','muted','已有弟子全部保留；扩建住房或提升宗门等级后可继续招募。'));box.append(link('前往山门招募','#building/gate','external-link'),link('灵膳供应','#building/kitchen','external-link'));return box;}
export function renderHallServices(ctx){const v=ctx.data.view.sect_services,box=el('section','panel');box.dataset.systemIcon='sect-overview';box.append(el('h2','','宗门运转'),housingFacts(v.housing),el('p','',`灵膳：${v.supply.active?'生效中':'未生效'} · 灵膳 ${v.supply.food}`));for(const r of v.matters){const row=el('section','row');row.dataset.id=r.id;row.append(link(r.name,r.route,'external-link'),el('p','muted',r.detail));box.append(row);}if(v.log.length){box.append(el('h3','','近期宗务'));for(const r of v.log.slice(-5))box.append(el('p','',r.operation==='RECRUIT'?`招募完成 ${r.count} 人`:`历史供养 ${r.count} 份`));}box.append(link('山门招募','#building/gate','external-link'),link('材料收购','#building/market','external-link'),link('炼器与强化','#building/forge','external-link'),renderCommissions(ctx));return box;}
export function renderSupply(ctx){const s=ctx.data.view.sect_services.supply,box=el('section','panel');box.dataset.systemIcon='sect-supply';box.append(el('h2','','灵膳供应'),facts([['状态',s.active?'生效中':s.enabled?'缺粮，等待补充':'关闭'],['当前基础口粮',String(s.food)],['每次供应',String(s.per_period)],['供应周期',`${s.period_seconds} 秒`],['库存保留',String(s.reserve)],['新开工效率',`+${s.bonus_percent}%`],['剩余',`${s.remaining_seconds} 秒`]]),el('p','muted','加成仅在新开工时确定；已开工任务保持原速度。暂停期间不消耗口粮。'));
 const input=el('input');input.type='number';input.min='0';input.step='1';input.value=String(s.reserve);input.setAttribute('aria-label','口粮保留量');const label=el('label','policy-field','口粮保留量');label.append(input);box.append(label);
 const save=enabled=>{const reserve=Number(input.value);if(!Number.isSafeInteger(reserve)||reserve<0){ctx.sheet('保留量',el('p','','请输入非负整数'));return;}confirmSheet(ctx,'确认灵膳供应',enabled?`启用供应，每 ${s.period_seconds} 秒消耗全宗弟子口粮，保留 ${reserve} 份口粮。`:'关闭后不再供应；已开工任务速度保持。',()=>ctx.economyAction('sect_supply',{enabled,reserve}));};
 const toggle=button(s.enabled?'关闭供应':'启用供应',()=>save(!s.enabled),'primary');toggle.disabled=!available(ctx);const reserve=button('保存保留量',()=>save(s.enabled),'secondary');reserve.disabled=!available(ctx);const actions=el('div','action-grid');actions.append(toggle,reserve);box.append(actions,renderProduction(ctx,['canteen']));return box;}
const movement=r=>`${r.variation_percent>0?'+':''}${Number(r.variation_percent||0).toFixed(1)}%`;
const money=n=>Number(n.toFixed(3)).toString();
const tradePayload=(r,quantity)=>({resource_id:r.resource_id,quantity,market_day:r.market_day,price_milli:r.price_milli});
export function materialControls(ctx,r){
 const box=el('section','material-detail');box.dataset.resourceId=r.resource_id;
 box.append(resourceIcon(ctx,r.resource_id,r.quantity),el('h3','',r.name),el('p','',`库存 ${r.quantity} · 保留 ${r.reserve}`),el('p','',`售价 ${money(r.price)} 灵钱 · 今日 ${movement(r)}`));
 const input=el('input');input.type='number';input.min='0';input.step='1';input.value=String(r.reserve);input.setAttribute('aria-label',r.name+'保留量');const label=el('label','policy-field','保留量');label.append(input);box.append(label);
 const save=button('保存保留量',()=>{const n=Number(input.value);if(Number.isSafeInteger(n)&&n>=0)ctx.economyAction('material_reserve',{resource_id:r.resource_id,quantity:n});},'secondary');save.disabled=!available(ctx);box.append(save);
 box.append(quantityControls(ctx,{label:'出售数量',min:Math.ceil(1000/r.price_milli),max:r.can_sell&&available(ctx)?Math.max(0,r.quantity-r.reserve):0,text:'出售材料',onSubmit:quantity=>ctx.economyAction('material_sell',tradePayload(r,quantity)),confirm:quantity=>`出售 ${r.name} ×${quantity}，获得 ${Math.floor(quantity*r.price_milli/1000)} 灵钱。按总额取整，保留量不受影响。`}));
 box.append(el('p','muted','售价按本批总额向下取整；不足1灵钱时请增加出售数量。'));return box;
}
function purchasePanel(ctx,r,resourceId){
 const box=el('section','material-detail');box.dataset.resourceId=resourceId;
 if(!r){box.append(el('p','blocking','今日此商品已下架，请返回查看当前商品。'));return box;}
 box.append(resourceIcon(ctx,r.resource_id,r.quantity),el('h3','',r.name),el('p','',`库存 ${r.quantity} · 商店剩余 ${r.remaining_stock} · 购入价 ${money(r.price)} 灵钱 · 今日 ${movement(r)}`));
 box.append(quantityControls(ctx,{label:'购买数量',max:available(ctx)?r.max_quantity:0,text:'购买材料',onSubmit:quantity=>ctx.economyAction('market_buy',tradePayload(r,quantity)),confirm:quantity=>`购买 ${r.name} ×${quantity}，消耗 ${Math.ceil(r.price_milli*quantity/1000)} 灵钱。按本批总额向上取整，材料进入仓库。`}));
 if(!available(ctx))box.append(el('p','blocking','宗门进度正在处理，完成后可购买。'));
 else if(!r.max_quantity)box.append(el('p','blocking',r.remaining_stock===0?'今日已售罄':'灵钱或仓库剩余空间不足'));
 return box;
}
function buyDetail(ctx,r){
 const box=purchasePanel(ctx,r,r.resource_id);
 box.__refresh=()=>{
  const latest=ctx.data.view.sect_services.market?.offers.find(row=>row.resource_id===r.resource_id);
  const fresh=deferIconLoads(()=>purchasePanel(ctx,latest,r.resource_id));
  const previousInput=box.querySelector('input[type=number]'),freshInput=fresh.querySelector('input[type=number]');
  if(previousInput&&freshInput){freshInput.value=previousInput.value;freshInput.dispatchEvent(new Event('input'));}
  const freshSubmit=fresh.querySelector('button.primary');
  patchPanel(box,fresh);activateIconLoads(box);
  const input=box.querySelector('input[type=number]'),submit=box.querySelector('button.primary');
  // Adopted input handlers must update the retained button, rather than the discarded clone.
  if(freshSubmit&&submit&&freshSubmit!==submit)Object.defineProperty(freshSubmit,'disabled',{configurable:true,get:()=>submit.disabled,set:value=>{submit.disabled=value;}});
  if(freshInput&&input&&freshInput!==input)freshInput.setAttribute=input.setAttribute.bind(input);
 };
 ctx.sheet(r.name,box);return box;
}
function renderMaterialGoods(ctx){
 const box=el('section','market-panel'),services=ctx.data.view.sect_services,market=services.market;
 box.dataset.systemIcon='sect-material-trade';const tab=ctx.ui.marketTab||'buy';
 box.append(featureTab([['buy','材料购买'],['sell','材料收购'],['equipment','装备收购'],['orders','收购订单'],['auctions','珍品拍卖']],tab,key=>{ctx.ui.marketTab=key;ctx.redraw();}));
 if(tab==='orders'){box.append(renderOrders(ctx));return box;}
 if(tab==='auctions'){box.append(renderAuctions(ctx));return box;}
 if(tab==='equipment'){box.append(renderTrade(ctx));return box;}
 box.append(el('h2','',tab==='buy'?'每日材料商店':'材料收购'));
 if(market)box.append(el('p','market-day',`第 ${market.display_day} 天 · ${market.remaining_seconds} 秒后换新`));
 box.append(el('p','muted',tab==='buy'?'每天随机20种已解锁材料，等级越高越少见；商品限量，Boss材料每天最多一种。价格每日浮动±20.0%。':'点击材料查看售价、设置保留量并出售；售价每日浮动±20.0%。'));
 const rows=tab==='buy'?(market?.offers||[]):services.materials,grid=el('div','inventory-grid market-grid');
 for(const r of rows){const cell=button('',()=>tab==='buy'?buyDetail(ctx,r):ctx.sheet(r.name,materialControls(ctx,r)),'inventory-item');cell.dataset.resourceId=r.resource_id;cell.setAttribute('aria-label',`${r.name}，库存${r.quantity}，${tab==='buy'?'购入价':'售价'}${money(r.price)}灵钱`);cell.append(resourceIcon(ctx,r.resource_id,r.quantity),el('span','item-name',r.name),el('small','market-price',`${tab==='buy'?'购':'售'} ${money(r.price)}`));if(tab==='buy')cell.append(el('small','muted',`余 ${r.remaining_stock}${r.boss_only?' · Boss':''}`));grid.append(cell);}
 box.append(grid);if(!rows.length)box.append(el('p','muted',tab==='buy'?'商品尚未开放':'暂无可收购材料'));
 return box;
}
export function renderFacility(ctx,kind){const f=ctx.data.view.sect_services.facilities.find(r=>r.kind===kind);if(f.exists)return renderProduction(ctx,[kind]);const box=el('section','panel');box.append(el('p','',kind==='pasture'?'建设御兽苑，可收集禽蛋供灵膳房使用。':'建设灵渊，可捕捞灵鱼供灵膳房使用。'));for(const [id,n]of Object.entries(f.cost))box.append(el('p','',`${ctx.data.view.inventory[id]?.name||id} ×${n}`));const action=button('建设设施',()=>confirmSheet(ctx,'确认建设','消耗上方材料建设一级设施，即时完成。',()=>ctx.economyAction('sect_facility_build',{building_kind:kind})),'primary');action.disabled=!available(ctx)||!f.can_build;box.append(action);if(f.blocking_reasons.length)box.append(el('p','blocking',f.blocking_reasons.join(' · ')));return box;}

export function renderMaterials(ctx){const host=renderMaterialGoods(ctx);host.append(renderContributionExchange(ctx),renderTechniqueLibrary(ctx,{shop:true}));return host;}

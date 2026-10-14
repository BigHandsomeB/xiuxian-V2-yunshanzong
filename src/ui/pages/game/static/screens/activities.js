// Consume server activity projections; choices are ephemeral, rewards commit on the server.
import {el,button,facts} from '../components/dom.js';
import {resourceIcon,iconLabel} from '../components/item-icon.js';
import {confirmSheet} from '../components/features.js';
const ready=(ctx,p)=>!ctx.busy&&!ctx.data.view.time?.pending&&!p.blocked;
function rewardRows(ctx,rewards){const host=el('div','material-detail');for(const r of rewards){const row=el('div','row');row.dataset.resourceId=r.resource_id;row.append(resourceIcon(ctx,r.resource_id,r.quantity),el('span','',`${r.name} ×${r.quantity}`));host.append(row);}return host;}
export function renderCommissions(ctx){
 const p=ctx.data.view.sect_activities,host=el('section',p?'panel':'');if(!p)return host;
 host.dataset.id='sect-commissions';host.append(el('h2','','宗门委托'),iconLabel(ctx,'sect_contribution',`贡献 ${p.contribution}`),iconLabel(ctx,'sect_reputation',`${p.reputation} · 累计贡献 ${p.earned}`),el('p','muted',`每个游戏日刷新，三类各完成一次，最多 ${p.daily_cap} 贡献。交付消耗真实库存并保护保留量；暂停时可即时操作，暂停不会刷新委托。`));
 for(const r of p.orders){const row=el('section','row');row.dataset.id='commission:'+r.order_id;row.append(iconLabel(ctx,'sect_commission',r.name),resourceIcon(ctx,r.resource_id,r.quantity),el('p','',`${r.resource_name} ×${r.quantity} → ${r.contribution} 贡献`));const action=button(r.complete?'今日已完成':'交付委托',()=>confirmSheet(ctx,'交付宗门委托',`交付 ${r.resource_name} ×${r.quantity}，获得 ${r.contribution} 贡献。`,()=>ctx.economyAction('sect_commission_claim',{order_id:r.order_id,market_day:r.market_day,quote_id:r.quote_id})),'primary');action.disabled=!ready(ctx,p)||!r.can_claim;row.append(action);if(!r.complete&&!r.can_claim)row.append(el('p','muted','材料不足、触及保留量或正在续算'));host.append(row);}
 return host;
}
export function renderContributionExchange(ctx){
 const p=ctx.data.view.sect_activities,host=el('section',p?'panel':'');if(!p)return host;
 host.dataset.id='contribution-exchange';host.append(el('h2','','贡献兑换'),iconLabel(ctx,'sect_contribution',`可用贡献 ${p.contribution}`),el('p','muted','兑换只消耗贡献，累计声望保留。材料包直接交付下列物品，仓满时不扣贡献。'));
 const grid=el('div','recipe-grid');
 for(const r of p.exchanges){const row=el('section','panel--inset recipe-card');row.dataset.id='contribution:'+r.id;row.append(iconLabel(ctx,'sect_material_pack',r.name),rewardRows(ctx,r.rewards));const text=r.rewards.map(x=>`${x.name} ×${x.quantity}`).join('、');const action=button(`${r.cost} 贡献兑换`,()=>confirmSheet(ctx,'贡献兑换',`消耗 ${r.cost} 贡献，获得 ${text}。`,()=>ctx.economyAction('sect_contribution_exchange',{exchange_id:r.id})),'primary block');action.disabled=!ready(ctx,p)||!r.can_exchange;row.append(action);if(!r.can_exchange)row.append(el('p','muted','贡献不足、仓库空间不足或正在续算'));grid.append(row);}
 host.append(grid);return host;
}
export function renderChoiceChests(ctx){
 const p=ctx.data.view.sect_activities,host=el('section',p?.chests?.length?'panel':'');if(!p?.chests?.length)return host;
 host.dataset.id='boss-choice-chests';host.append(el('h2','','首通定向宝箱'),el('p','muted','每个副本新增首通宝箱可选择一个成长方向；也可保留，稍后领取。'));
 for(const chest of p.chests){const row=el('section','row');row.dataset.id='choice-chest:'+chest.chest_id;row.append(iconLabel(ctx,'boss_choice_chest',chest.name));const open=button('查看并选择奖励',()=>{const body=el('section');body.append(el('p','muted','三种方向只可领取一种；确认前不消耗宝箱。'));for(const choice of chest.choices){const card=el('section','row');card.append(el('h3','',choice.name),rewardRows(ctx,choice.rewards));const text=choice.rewards.map(r=>`${r.name} ×${r.quantity}`).join('、');const action=button(`选择${choice.name}`,()=>confirmSheet(ctx,'领取首通宝箱',`选择${choice.name}：${text}。确认后消耗这个宝箱，其余方向不再领取。`,()=>ctx.economyAction('boss_chest_open',{chest_id:chest.chest_id,choice:choice.id})),'primary');action.disabled=!ready(ctx,p)||!choice.can_open;card.append(action);if(!choice.can_open)card.append(el('p','muted','仓库空间不足或正在续算，宝箱继续保留'));body.append(card);}ctx.sheet(chest.name,body);},'primary');open.disabled=!ready(ctx,p);row.append(open);host.append(row);}
 return host;
}

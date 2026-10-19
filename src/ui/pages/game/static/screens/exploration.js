// Exploration uses only committed server projections and the shared command lane.
import {el,button} from '../components/dom.js';
import {resourceAmount,confirmSheet,progressBar} from '../components/features.js';

function amounts(ctx,rows){const node=el('div','resource-pairs');for(const r of rows)node.append(resourceAmount(ctx,r.resource_id,r.quantity));return node;}
function description(rows){return rows.length?rows.map(r=>`${r.name} ×${r.quantity}`).join('、'):'无';}
function enabled(ctx,p){return !ctx.busy&&!p.blocked;}
function switchTab(ctx,name){ctx.ui.adventureTab=name;ctx.redraw();}
function currentJourney(ctx,p){
 const a=p.active,card=el('section','panel');card.dataset.id='exploration-current';
 if(!a){card.append(el('h2','','尚未出发'),el('p','muted','选择一个已解锁地点开始探索，途中发现的事件会在行程完成后出现。'));return card;}
 card.append(el('h2','',a.name),el('p','',a.ready?'探索完成 · 有一件奇遇待处理':'正在探索 · 收获与奇遇将在行程结束后揭晓'));
 const total=Math.max(1,a.due_ms-a.started_ms),done=total-a.remaining_ms;
 card.append(progressBar(done,total,'探索进度'));
 if(!a.ready){const day=ctx.data.view.time?.day_length_ms||120000;card.append(el('p','muted',`剩余约 ${Math.max(0.01,a.remaining_ms/day).toFixed(2)} 个游戏日。世界暂停时行程停止推进。`));const refresh=button('更新探索进度',()=>ctx.sync(true),'secondary');refresh.disabled=!enabled(ctx,p);card.append(refresh);}
 else{card.append(el('p','muted','基础收获'),amounts(ctx,a.rewards));const action=button('处理特殊事件',()=>switchTab(ctx,'事件'),'primary');action.disabled=ctx.busy;card.append(action);}
 return card;
}
export function renderExploration(ctx){
 const p=ctx.data.view.exploration,host=el('section');host.dataset.id='exploration-panel';
 if(!p){host.append(el('p','muted','探索尚未开放'));return host;}
 host.append(el('h2','','山外探索'),el('p','muted','一次只进行一处探索，可与副本挂机并行。每个地点有三种轮换奇遇；同地三次可遇全。基础收获和事件收益在处理事件后一起入库，待处理事件不会过期。'));
 if(p.blocked)host.append(el('p','blocking','世界暂停或正在续算，暂不能出发或处理事件。'));
 host.append(currentJourney(ctx,p));
 const grid=el('div','recipe-grid');
 for(const r of p.regions){const card=el('article','panel recipe-card');card.dataset.id='exploration-region:'+r.id;
  card.append(el('h3','',r.name),el('p','',r.description),el('p','muted',`行程 ${r.duration_days} 个游戏日 · 已探索 ${r.visits} 次`),el('p','muted','基础收获'),amounts(ctx,r.rewards));
  const start=button(r.unlocked?'开始探索':'尚未解锁',()=>confirmSheet(ctx,'出发探索',`前往${r.name}，耗时 ${r.duration_days} 个游戏日。基础收获：${description(r.rewards)}。完成后需处理一件特殊事件，才能再次出发。`,()=>ctx.economyAction('exploration_start',{region_id:r.id})),'primary block');start.disabled=!enabled(ctx,p)||!r.can_start;card.append(start);
  if(!r.unlocked)card.append(el('p','blocking',r.lock_reason));else if(p.active)card.append(el('p','muted','请先完成并处理当前探索。'));
  grid.append(card);
 }
 host.append(grid);return host;
}
export function renderEvents(ctx){
 const p=ctx.data.view.exploration,host=el('section');host.dataset.id='exploration-events';
 if(!p){host.append(el('p','muted','特殊事件尚未开放'));return host;}
 const a=p.active,e=a?.event;
 if(e){const card=el('section','panel');card.dataset.id='exploration-event:'+a.id;card.append(el('h2','',e.name),el('p','muted',a.name),el('p','',e.description),el('p','muted','基础收获（任意选项均可领取）'),amounts(ctx,a.rewards));
  for(const c of e.choices){const row=el('section','row');row.dataset.id='exploration-choice:'+c.id;
   row.append(el('h3','',c.name),el('p','muted',`消耗：${description(c.cost)}`),el('p','muted',`成功率 ${c.success_bps/100}%${c.success_bps<10000?'；未成功时无额外收获，基础收获保留。':'。'}`));
   if(c.rewards.length)row.append(el('p','muted','额外收获'),amounts(ctx,c.rewards));
   const text=`选择「${c.name}」。消耗：${description(c.cost)}。基础收获：${description(a.rewards)}；额外收获：${description(c.rewards)}，成功率 ${c.success_bps/100}%。${c.success_bps<10000?'失败时仍消耗上述材料，仅保留基础收获。':''}确认后结束本次探索。`;
   const choose=button('选择'+c.name,()=>confirmSheet(ctx,e.name,text,()=>ctx.economyAction('exploration_choose',{journey_id:a.id,choice_id:c.id})),'primary');choose.disabled=!enabled(ctx,p)||!c.can_choose;row.append(choose);if(c.blocking_reason)row.append(el('p','blocking',c.blocking_reason));card.append(row);
  }host.append(card);
 }else{host.append(el('h2','','暂无待处理事件'),el('p','muted',a?'当前探索尚在途中，行程完成后将发现特殊事件。':'先前往一个探索地点，沿途或有新的发现。'),button(a?'查看当前探索':'前往探索',()=>switchTab(ctx,'特殊探索'),'secondary'));}
 const history=el('section','panel');history.dataset.id='exploration-history';history.append(el('h2','','游历见闻'),el('p','muted',`保留最近 ${p.history_limit} 次探索结果。`));
 if(!p.history.length)history.append(el('p','muted','尚无游历记录。'));
 for(const h of p.history){const row=el('details','row');row.dataset.id='exploration-history:'+h.sequence;if(h===p.history[0]&&!a)row.open=true;const day=ctx.data.view.time?.day_length_ms||120000;
  row.append(el('summary','',`${h.region_name} · ${h.event_name} · ${h.choice_name}`),el('p','muted',`第 ${Math.floor(h.sim_ms/day)+1} 日 · ${h.success?'已完成':'未获额外收获'}`),el('p','',h.text),el('p','muted',`消耗：${description(h.cost)}`),el('p','muted','实际收获'),amounts(ctx,h.rewards));history.append(row);
 }
 host.append(history);return host;
}

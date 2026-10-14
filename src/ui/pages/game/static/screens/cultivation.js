import {renderTechniqueSlots} from '../components/technique-slots.js';
import {render as renderInventory} from './inventory.js';
import {portraitIcon} from '../components/item-icon.js';
import {systemIcon,iconLabel} from '../components/item-icon.js';
import {el,heading,status,button} from '../components/dom.js';
import {resourceIcon,itemIcon} from '../components/item-icon.js';
import {equipmentSlots} from './equipment.js';
export function render(ctx={}){
 const v=ctx.data?.view.cultivation,node=el('section','cultivation-screen');
 if(!v){node.append(heading('问道修炼','山中静坐，待大道初开。'));const seal=el('div','cultivation-seal');seal.append(el('span','','道'),el('p','','修炼系统尚未开放'));node.append(seal);for(const name of ['境界与修为','突破','功法','修炼丹药','闭关']){const row=el('div','locked-module');row.append(el('strong','',name),status('尚未开放'));node.append(row);}return node;}
 if(!ctx.embedded)node.append(heading('问道修炼','击杀积修为，服丹助修行。'));
 const portrait=el('div','growth-identity');portrait.append(portraitIcon(ctx),el('strong','',v.player.name),status(v.level?`${v.realm_name} · 第 ${v.level} 级`:v.realm_name));node.append(portrait);
 const progress=el('div','growth-progress'),meter=el('progress');meter.id='cultivation-progress';meter.max=v.threshold||1;meter.value=v.threshold?v.progress:1;meter.setAttribute('aria-label','修为');meter.setAttribute('aria-valuenow',String(v.progress));meter.setAttribute('aria-valuemax',String(v.threshold));progress.append(systemIcon(ctx,'cultivation'),el('h2','',v.foundation?'筑基修为':'修为'),el('p','growth-amount',v.status==='MAX_FOR_PHASE'&&!v.level?'当前阶段已达到可开放的最高境界':`${compact(v.progress)} / ${compact(v.threshold)}`),meter);node.append(progress);
 if(v.stage?.name){const box=el('section','panel');box.append(el('h2','',`${v.realm_name} · ${v.stage.name}`),el('p','',`基础生命、攻击加成 ${v.stage.bonus_bps/100}%`),el('p','',v.stage.remaining?`下一档需修为 ${v.stage.next_progress}，还需 ${v.stage.remaining}`:v.foundation?'筑基修为已满，本批暂无下一境界':'修为已满，可按突破需求破境'));node.append(box);}
 const milestone=v.milestone;if(milestone){const box=el('section','panel growth-milestone');const names={max_hp_milli:'生命',armor_milli:'护甲',attack_milli:'攻击',speed_bps:'攻速',evasion_bps:'闪避'};const amount=milestone.amount/(milestone.stat.endsWith('_bps')?100:1000);box.append(el('h2','',`第 ${milestone.level} 级里程碑`),el('p','',`还差 ${milestone.remaining} 级 · ${names[milestone.stat]} +${Math.round(amount)}${milestone.stat.endsWith('_bps')?'%':''}`));node.append(box);}if(v.level)node.append(el('p','muted',`修为来自击杀；丹药每24小时前 ${v.pill_daily_full_limit} 枚全效，已用 ${v.pill_daily_used} 枚，之后 ${v.pill_reduced_percent}% 效果。`));
 if(v.level&&!v.next_realm)node.append(el('p','muted','筑基第1000级修为满后停止积累；下一境界尚未开放。'));
 const breaking=button(ctx.busy?'处理中…':'突破',()=>confirm(),'primary block action-key');breaking.id='cultivation-breakthrough';breaking.hidden=v.status!=='BREAKTHROUGH_AVAILABLE';breaking.disabled=ctx.busy||ctx.data.view.world?.paused||!v.can_breakthrough;node.append(breaking);
 const reasons=v.status==='BREAKTHROUGH_AVAILABLE'?v.blocking_reasons.breakthrough:[];for(const r of reasons)node.append(el('p','growth-blocked',r.message));
 if(v.next_realm){const cost=el('div','growth-cost');cost.append(el('h2','',`下一境界 · ${v.next_realm.name}（需第500级且修为条满）`));for(const r of v.breakthrough_costs){const line=el('p','',`${r.name} ×${r.quantity}（当前${r.current_quantity}）`);if(r.resource_id)line.append(resourceIcon(ctx,r.resource_id));cost.append(line);}node.append(cost);}
 function attributes(title,stats,next=null){const box=el('div','growth-stats');box.append(el('h2','',title));for(const [k,name,id]of [['max_hp','生命','hp'],['attack','攻击','attack'],['armor','护甲','defense']]){const line=el('p','icon-label');line.append(systemIcon(ctx,id),el('span','',next?`${name}：${Math.round(stats[k])} → ${Math.round(next[k])}`:`${name}：${Math.round(stats[k])}`));box.append(line);}return box;}
 const loadout=el('div','cultivation-loadout'),stats=el('section','growth-stats character-attributes');stats.setAttribute('aria-label','主角战斗属性');stats.append(el('h2','','属性'));
 const list=el('div','character-attribute-list');list.setAttribute('tabindex','0');list.setAttribute('aria-label','属性列表，可滚动查看');
 const rows=v.attributes||[['max_hp','生命','hp'],['attack','攻击','attack'],['armor','护甲','defense']].map(([id,name,icon])=>({id,name,icon,value:v.combat_projection[id],unit:''}));
 for(const row of rows){const line=el('p','character-attribute');line.dataset.attributeId=row.id;line.title=row.description||row.name;line.setAttribute('aria-label',`${row.name} ${Math.round(row.value)}${row.unit}`);const value=el('span','character-attribute-text');value.append(el('small','character-attribute-name',row.name),el('strong','character-attribute-value',`${Math.round(row.value)}${row.unit}`));line.append(systemIcon(ctx,row.icon),value);list.append(line);}
 stats.append(list);loadout.append(stats,equipmentSlots(ctx));node.append(loadout,renderTechniqueSlots(ctx));
 node.append(renderInventory({...ctx,ui:ctx.ui||{},embedded:true,bag:true}));
 function confirm(){if(ctx.busy||!v.can_breakthrough)return;const box=el('div');box.append(el('p','',`${v.realm_name} → ${v.next_realm.name}`),attributes('突破后属性',v.combat_projection,v.next_realm_preview));for(const r of v.breakthrough_costs)box.append(el('p','',`消耗${r.name} ×${r.quantity}`));const yes=button('确认突破',()=>{if(ctx.busy)return;const promise=ctx.cultivationAction('cultivation_breakthrough');document.getElementById('sheet')?.close();return promise;},'primary block action-key');yes.id='cultivation-confirm';box.append(yes);ctx.sheet('确认突破',box);}
 const receipt=ctx.cultivationReceipt?.result;
 if(receipt?.events?.some(e=>e.kind==='breakthrough_completed')&&receipt.cultivation.growth_revision===v.growth_revision){const feedback=el('div','growth-success');feedback.append(el('strong','','境界突破成功'),attributes('战斗属性提升',receipt.stats_before,receipt.stats_after));node.append(feedback);}
 return node;
}

function compact(n){return n>=100000000?`${Number((n/100000000).toFixed(2))}亿`:n>=10000?`${Number((n/10000).toFixed(2))}万`:String(n);}

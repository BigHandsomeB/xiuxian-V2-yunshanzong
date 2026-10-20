import {el,button} from './dom.js';
import {itemIcon} from './item-icon.js';

const reasons={DEFEATED:'挑战失败，试炼已停止。已获得的经验和属性保留。',STOPPED:'已停止试炼。',COMPLETED:'已通关当前全部波次，可重新选择已解锁波次挑战。',MAXED:'该属性已达到当前试炼上限。'};
export function renderAttributeTrials(ctx){
 const view=ctx.data.view.cultivation.attribute_trials,box=el('section','panel attribute-trials');box.dataset.id='attribute-trials';
 box.append(el('h2','','属性试炼场'),el('p','muted','选择想提升的属性，经验达标自动永久成长。波次越高，怪物越强、经验越多；与冒险二选一挂机。'));
 const cards=el('div','trial-choices');
 for(const row of view.rows){
  const card=el('section','trial-choice');card.dataset.id='trial-'+row.id;const active=view.running&&view.stat===row.id;
  card.append(el('h3','',row.name),el('p','',`已提升 ${row.bonus} · 每级 +${row.gain}`),el('p','muted',row.maxed?'当前属性试炼等级已满':`试炼等级 ${row.level} · 经验 ${row.progress} / ${row.needed}`),el('p','muted',`最高通过第 ${row.highest_wave} 波`));
  const label=el('label','trial-wave','起始波次'),field=el('input');field.type='number';field.inputMode='numeric';field.min='1';field.max=String(row.next_wave);field.value=String(row.next_wave);field.dataset.id='trial-wave-'+row.id;field.setAttribute('aria-label',row.name+'起始波次');field.disabled=ctx.busy||view.running;label.append(field);
  const start=button(active?'试炼进行中':'进入'+row.name,event=>{const value=event.currentTarget.parentNode.querySelector('input').value;return ctx.economyAction('attribute_trial_start',{stat:row.id,wave:Number(value)});},'secondary');start.disabled=ctx.busy||!view.can_start||row.maxed;start.dataset.trialStart=row.id;card.append(label,start);cards.append(card);
 }
 if(view.running||view.battle){
  const fight=el('div','trial-battle');fight.dataset.id='trial-battle';const title=view.rows.find(r=>r.id===view.stat)?.name||'属性试炼';fight.append(el('h3','',`${title} · 第 ${view.wave} 波`));
  if(view.battle){const b=view.battle;fight.append(itemIcon({...ctx.data.presentation?.attribute_trial_enemy,fallback:'other'}),el('p','',`${b.enemy_name} · 生命 ${Math.round(b.enemy_hp)} / ${Math.round(b.enemy_max_hp)}`),el('p','muted',`攻击 ${Math.round(b.enemy_attack)} · 护甲 ${Math.round(b.enemy_armor)} · 第 ${b.step} 回合`),el('p','',`主角生命 ${Math.round(b.player_hp)} / ${Math.round(b.player_max_hp)}`));}
  fight.append(el('p','muted',`本波获胜经验 ${view.xp_per_win} · 最近获得 ${view.latest_xp}`));
  if(view.running){const stop=button('停止属性试炼',()=>ctx.economyAction('attribute_trial_stop',{}),'secondary');stop.disabled=ctx.busy;stop.dataset.trialStop='stop';fight.append(stop);}
  if(view.reason)fight.append(el('p','muted',reasons[view.reason]||view.reason));box.append(fight);
 }
 box.append(cards);
 if(!view.can_start&&!view.running)box.append(el('p','muted','请先停止冒险挂机、结束或领取当前战斗，并完成续算；世界运行时可进入试炼。'));
 box.append(el('p','muted','试炼不掉落装备、材料、修为或功法经验；暂停世界时暂停，离线按相同规则结算。'));
 return box;
}

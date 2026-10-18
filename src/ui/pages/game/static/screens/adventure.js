import {stopReasonName,simulationStamp} from '../components/offline-report.js';
import {el,heading,link,status,button} from '../components/dom.js';
import {itemIcon} from '../components/item-icon.js';
import {featureTab,detailSheet,recipeCard} from '../components/features.js';
const plannedDungeons=[["red_copper_mine", "赤铜废矿"], ["mist_marsh", "雾隐灵泽"], ["cold_jade_cave", "寒玉冰窟"], ["fire_elixir_ruins", "离火丹墟"], ["thunder_sword_tomb", "玄雷剑冢"], ["earth_vein_city", "地脉古城"], ["moon_underworld", "太阴幽府"], ["star_palace", "星陨天宫"], ["xuanhuang_seal", "玄黄封仙台"]];
function dungeonList(ctx,combat){
 const list=el('div','dungeon-list'),rows=combat.dungeons||[combat.dungeon],known=new Set(rows.map(d=>d.id));
 for(const d of rows)list.append(dungeonCard(ctx,combat,d));
 for(const [id,name] of plannedDungeons){if(known.has(id))continue;const card=el('article','dungeon-card dungeon-card--upcoming'),visual=ctx.data.presentation?.system_icons?.['dungeon_'+id]||{};card.dataset.dungeonId=id;card.append(itemIcon({...visual,fallback:'other'}),el('h2','',name),el('p','dungeon-range','1–100层'),status('尚未开放'));list.append(card);}
 return list;
}
function dungeonCard(ctx,combat,d=combat.dungeon){
 const selected=d.id===combat.dungeon.id,paused=ctx.data.view.world?.paused,blocked=!selected&&(paused||ctx.busy||combat.auto?.enabled||['ACTIVE','PLAYER_WIN'].includes(combat.status)),available=d.unlocked!==false;
 const card=available&&!blocked?link('','#battle','dungeon-card'+(selected?' dungeon-card--active':'')):el('article','dungeon-card dungeon-card--upcoming'),icons=ctx.data.presentation?.system_icons||{};
 card.dataset.dungeonId=d.id;card.append(itemIcon({...((icons['dungeon_'+d.id]?.asset?icons['dungeon_'+d.id]:icons.dungeon)||{}),fallback:'other'}),el('h2','',d.name),el('p','dungeon-range',`1–${d.total_floors}层`),el('small','dungeon-progress',`已通关 ${d.cleared_floor} / ${d.total_floors} 层`));
 const previous=(combat.dungeons||[]).find(x=>x.id===d.unlock_condition?.dungeon_id);
 const message=!available?`需通关${previous?.name||'前一副本'}${d.unlock_condition?.cleared_floor||100}层`:paused?'世界暂停':blocked?'结束战斗并停止挂机后可切换':selected&&combat.auto?.enabled?'自动挂机中':'进入副本';card.append(status(message));
 if(available&&!blocked&&!selected)card.addEventListener('click',async event=>{event.preventDefault();const next=await ctx.combatAction('dungeon_select',{dungeon_id:d.id});if(next?.view.combat.dungeon.id===d.id)location.hash='#battle';});
 return card;
}
export function render(ctx){const node=el('section','adventure-screen');node.append(heading('山外寻道','云深处，自有天地。'));const combat=ctx?.data?.view?.combat;
 const reason=ctx.data.view.world?.paused?'WORLD_PAUSED':combat?.stop_reason||combat?.auto?.reason||(combat?.status==='PLAYER_LOSE'?'DEFEATED':null);
 if(['DEFEATED','STORAGE_FULL','WORLD_PAUSED'].includes(reason)){
  const notice=el('div','panel');notice.id='battle-stop-notice';notice.setAttribute('role','status');
  const suggestions={DEFEATED:'更换装备，或退回较低层后重新开启挂机。',STORAGE_FULL:'去万宝库出售、分解装备，或在设置页开启材料折算；腾出空间后领取战利品并重新开启挂机。',WORLD_PAUSED:'战斗与生产已冻结。点击顶栏继续世界后再开启冒险。'};
  notice.append(el('p','',`冒险已停止：${stopReasonName[reason]}。${suggestions[reason]}`),el('p','muted',`停机时间：${simulationStamp(combat?.stop_sim_ms,ctx.data.view.time?.day_length_ms)}`));
  if(reason==='STORAGE_FULL')notice.append(link('去万宝库','#inventory/trade','external-link'),link(' 查看材料折算设置','#settings','external-link'));node.append(notice);
 }
 if(!combat?.dungeon){const gate=link('','#battle','battle-gate');gate.append(el('h2','',combat?combat.encounter.name:'战斗场景'),status(combat?'进入试炼':'系统开发中'));node.append(gate);}
 const tabs=['地图 / 区域','秘境塔','普通副本','Boss','特殊探索','事件','战斗记录'],selected=ctx.ui.adventureTab||tabs[0];node.append(featureTab(tabs.map(k=>[k,k]),selected,key=>{ctx.ui.adventureTab=key;ctx.redraw();}));
 if(selected==='战斗记录'&&combat?.battle_id){node.append(el('p','',combat.encounter.name),el('p','',combat.status==='SETTLED'?'胜利 · 奖励已入库':combat.status==='ACTIVE'?'当前战斗进行中':'当前战斗已结束'));node.append(link('查看当前战斗','#battle','external-link'));}
 else if(combat?.dungeon&&['地图 / 区域','秘境塔','普通副本','Boss'].includes(selected)){node.append(['地图 / 区域','普通副本'].includes(selected)?dungeonList(ctx,combat):dungeonCard(ctx,combat));}
 else node.append(recipeCard(ctx,selected,`${selected}结构已预留。正式规则尚未开放，不产生假探索、掉落或战报。`));
 for(const name of ['探索','特殊事件'])node.append(button(name,()=>detailSheet(ctx,name,'入口和内容结构预留；对应玩法尚未开放。'),'locked-module'));return node;}

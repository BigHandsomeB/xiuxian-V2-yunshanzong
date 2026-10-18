import {el,button,empty,status,link} from '../components/dom.js';
import {featureTab,confirmSheet} from '../components/features.js';
import {resourceIcon} from '../components/item-icon.js';
import {techniqueRules,techniqueIcon} from '../components/technique-slots.js';

const categories=[['all','全部'],['movement','身法'],['defense','防御'],['special','绝技'],['ultimate','终极'],['passive','内功']];
const names={"block_bps":"格挡","spirit_milli":"灵力","dot_reduction_bps":"持续伤害减免","heal_bonus_bps":"回复强化","shield_bonus_bps":"护盾强化","burn_apply_bps":"灼烧概率","burn_bonus_bps":"灼烧强化","chill_bonus_bps":"寒冷强化","wood_damage_bps":"木伤加成","wood_resist_bps":"抗木","earth_damage_bps":"土伤加成","earth_resist_bps":"抗土","metal_damage_bps":"金伤加成","metal_resist_bps":"抗金","water_damage_bps":"水伤加成","water_resist_bps":"抗水","fire_damage_bps":"火伤加成","fire_resist_bps":"抗火","ice_damage_bps":"冰伤加成","ice_resist_bps":"抗冰","yin_damage_bps":"阴伤加成","yin_resist_bps":"抗阴","lightning_damage_bps":"雷伤加成","lightning_resist_bps":"抗雷","poison_damage_bps":"毒伤加成","poison_resist_bps":"抗毒",max_hp_milli:'生命',attack_milli:'攻击',armor_milli:'护甲',pierce_milli:'破甲',speed_bps:'攻速',evasion_bps:'闪避',accuracy_bps:'命中加成',crit_bps:'暴击',crit_resist_bps:'抗暴',crit_damage_bps:'暴伤加成',damage_reduction_bps:'减伤',damage_bonus_bps:'增伤',lifesteal_bps:'吸血',execute_bps:'斩杀增伤',poison_resist_bps:'抗毒',reflect_bps:'反伤'};
function techniqueDetail(ctx,identity){
 const view=ctx.data.view.techniques,owned=view?.instances.find(r=>r.id===identity),row=owned||view?.catalog.find(r=>r.id===identity);if(!row)return;
 const body=el('div','item-detail technique-detail'),title=el('h2','technique-name',row.name);title.dataset.grade=row.grade;
 body.append(techniqueIcon(ctx,row,'detail'),title,el('p','',owned?`Lv ${row.level} / ${row.max_level}`:`尚未习得 · Lv上限 ${row.max_level}`));
 if(owned)body.append(el('p','',row.level===row.max_level?'功法已满级':`功法经验 ${row.progress} / ${row.threshold}`));
 body.append(el('h3','',owned?'当前加成':'满级加成'));
 for(const [key,n]of Object.entries(owned?row.bonus:row.max_bonus))body.append(el('p','',`${names[key]||key} +${Math.round(n/(key.endsWith('_bps')?100:1000))}${key.endsWith('_bps')?'%':''}`));
 body.append(el('p','muted','装备后击杀获得功法经验，Lv提升增加属性；合计加成遵守现有上限。'));
 if(row.effect_rules?.length){body.append(el('h3','','特殊效果'));for(const text of row.effect_rules)body.append(el('p','',text));}
 const actions=el('div','action-grid');
 if(owned){
  for(const slot of techniqueRules.slots.filter(s=>row.category==='passive'?s.id.startsWith('passive_'):s.id===row.category)){
   const action=button('装备至'+slot.name,()=>ctx.economyAction('technique_equip',{technique_id:row.id,slot:slot.id}),'secondary');action.disabled=ctx.busy||!view.can_change||row.equipped_slot===slot.id;actions.append(action);
  }
  if(row.equipped_slot){const remove=button('卸下功法',()=>ctx.economyAction('technique_unequip',{slot:row.equipped_slot}),'secondary');remove.disabled=ctx.busy||!view.can_change;actions.append(remove);}
  if(view.blocking_reason)body.append(el('p','blocking',view.blocking_reason));
 }else{
  for(const quote of row.alternatives||[row.source]){
   const label={buy:'购买功法',claim:'领取首通功法',exchange:'兑换功法'}[quote.kind];
   for(const [id,n]of Object.entries(quote.cost)){const line=el('p','icon-label');line.append(resourceIcon(ctx,id),el('span','',`${ctx.data.view.inventory[id]?.name||id} ×${n}`));body.append(line);}
   if(quote.kind==='claim')body.append(el('p','',`荆棘古道${quote.required_floor}层进度奖励，此品阶只可选一部。`));
   const acquire=button(label,()=>confirmSheet(ctx,label,`${row.name}：${quote.kind==='claim'?'领取后占用此品阶一次性首通选择':Object.entries(quote.cost).map(([id,n])=>`${ctx.data.view.inventory[id]?.name||id} ×${n}`).join('、')}。`,()=>ctx.economyAction('technique_'+quote.kind,{technique_id:row.id})),'primary');acquire.disabled=ctx.busy||!quote.available;actions.append(acquire);
   for(const reason of quote.blocking_reasons)body.append(el('p','blocking',reason));
  }
 }
 body.append(actions);ctx.sheet(row.name,body);
}
export function renderTechniqueLibrary(ctx,{shop=false}={}){
 const state=shop?(ctx.ui.techniqueShop??={category:'all'}):(ctx.ui.techniqueLibrary??={category:'all',mode:'owned'}),mode=shop?'buy':state.mode||'owned';
 const host=el('section','technique-library'),view=ctx.data?.view?.techniques;
 host.append(el('h2','',shop?'功法常驻商店':'功法阁'));
 if(!shop)host.append(featureTab([['owned','已收藏'],['claim','首通传承'],['exchange','灵石兑换'],['catalog','功法图鉴']],mode,key=>{state.mode=key;ctx.redraw();}));
 host.append(featureTab(categories,state.category,key=>{state.category=key;ctx.redraw();}));
 if(mode==='exchange'){const line=el('p','icon-label');line.append(resourceIcon(ctx,'manual_page'),el('span','',`功法残页 ${view?.page_count||0}`));host.append(line,el('p','muted','100层Boss结算固定获得1张；橙阶需极品灵石20＋残页100，红阶需仙品灵石10＋残页400。'));}
 if(mode==='claim')host.append(el('p','muted','荆棘古道30层蓝阶任选一部，60层紫阶任选一部；已通关的旧存档也可领取。'));
 const rows=(mode==='owned'?view?.instances||[]:view?.catalog||[]).filter(r=>(state.category==='all'||r.category===state.category)&&(mode==='owned'||mode==='catalog'||(r.alternatives||[r.source]).some(q=>q?.kind===mode)));
 if(!rows.length)host.append(empty(mode==='owned'?'尚未收藏此类功法':'此类暂无功法'));
 else{const grid=el('div','technique-grid');for(const row of rows){const card=button('',()=>techniqueDetail(ctx,row.id),'technique-slot panel--inset');card.dataset.id=row.id;const name=el('strong','technique-name',row.name);name.dataset.grade=row.grade;card.append(techniqueIcon(ctx,row),name,el('small','technique-level',row.level?`Lv ${row.level} / ${row.max_level}`:`Lv上限 ${row.max_level}`),el('small','',row.equipped_slot?'已装备':row.level||row.owned?'已收藏':'未获得'));grid.append(card);}host.append(grid);}
 host.append(link('查看八个功法槽','#cultivation','external-link'),link('万宝楼购买低阶功法','#building/market','external-link'));
 if(!shop){
  const rules=el('details','technique-rules');rules.append(el('summary','','品阶与等级上限'));const grades=el('div','technique-grade-list');
  for(const grade of techniqueRules.grades){const label=el('span','technique-grade',`${grade.name} · Lv ${grade.max_level}`);label.dataset.grade=grade.id;grades.append(label);}rules.append(grades);host.append(rules);
  for(const [id,title,description,action]of [['technique-training','功法修炼','已装备功法随击杀升级；独立修炼后续开放。','独立修炼功法'],['character-meditation','主角闭关','闭关获得角色修为；世界暂停时冻结。','开始闭关']]){
   const panel=el('section','panel');panel.dataset.id=id;panel.append(el('h2','',title),status('尚未开放'),el('p','muted',description));const control=button(action,null,'primary');control.disabled=true;panel.append(control);host.append(panel);
  }
 }
 return host;
}

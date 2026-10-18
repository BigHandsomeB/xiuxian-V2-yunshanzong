import {el,status,button} from './dom.js';
import {itemIcon} from './item-icon.js';

// Fallback presentation rules when the server has no technique read model.
export const techniqueRules=Object.freeze({
 system_open:false,
 character_kill_xp_requires_equipped:true,
 meditation_open:false,
 slots:Object.freeze([
  {id:'movement',name:'身法功法'},
  {id:'defense',name:'防御功法'},
  {id:'special',name:'绝技功法'},
  {id:'ultimate',name:'终极功法'},
  {id:'passive_1',name:'内功一'},
  {id:'passive_2',name:'内功二'},
  {id:'passive_3',name:'内功三'},
  {id:'passive_4',name:'内功四'}
 ].map(Object.freeze)),
 grades:Object.freeze([
  {id:'white',name:'白色',max_level:10},
  {id:'green',name:'绿色',max_level:15},
  {id:'blue',name:'蓝色',max_level:20},
  {id:'purple',name:'紫色',max_level:25},
  {id:'orange',name:'橙色',max_level:30},
  {id:'red',name:'红色',max_level:40}
 ].map(Object.freeze))
});

function openTechniqueSlot(ctx,slot){
 const view=ctx.data.view.techniques,row=view.instances.find(r=>r.equipped_slot===slot.id),body=el('div','technique-detail');
 body.append(el('p','',row?`当前功法：${row.name} · Lv ${row.level} / ${row.max_level}`:'此槽位尚未装备功法'),el('h3','',row?'更换功法':'装备功法'));
 const choices=view.instances.filter(r=>r.category===(slot.id.startsWith('passive_')?'passive':slot.id));
 if(!choices.length)body.append(el('p','muted','尚未拥有可装备到此槽位的功法。'));
 for(const candidate of choices){
  const current=candidate.equipped_slot===slot.id,action=button('',()=>{
   if(ctx.busy||!ctx.data.view.techniques.can_change)return;
   return ctx.economyAction('technique_equip',{technique_id:candidate.id,slot:slot.id});
  },'secondary');action.dataset.id=candidate.id;action.disabled=ctx.busy||!view.can_change||current;
  const name=el('strong','technique-name',candidate.name);name.dataset.grade=candidate.grade;
  const equipped=techniqueRules.slots.find(s=>s.id===candidate.equipped_slot);
  action.append(techniqueIcon(ctx,candidate),name,el('span','',`Lv ${candidate.level} / ${candidate.max_level} · ${current?'当前已装备':row?'更换功法':'装备功法'}`));
  if(equipped&&!current)action.append(el('small','',`将从${equipped.name}移至此槽`));
  body.append(action);
 }
 if(row){const remove=button('卸下功法',()=>{if(ctx.busy||!ctx.data.view.techniques.can_change)return;return ctx.economyAction('technique_unequip',{slot:slot.id});},'secondary');remove.disabled=ctx.busy||!view.can_change;body.append(remove);}
 if(view.blocking_reason)body.append(el('p','blocking',view.blocking_reason));
 ctx.sheet(slot.name,body);
}

export function renderTechniqueSlots(ctx=null){
 const view=ctx?.data?.view?.techniques;
 const section=el('section','technique-slots');section.setAttribute('aria-label','功法栏');
 const header=el('header','technique-header');header.append(el('h2','','功法'),status(view?.open?'已开放':'尚未开放'));section.append(header);
 const grid=el('div','technique-grid');
 for(const slot of techniqueRules.slots){
  const row=view?.instances?.find(r=>r.equipped_slot===slot.id);
  const card=view?.open?button('',()=>openTechniqueSlot(ctx,slot),'technique-slot panel--inset'):el('div','technique-slot panel--inset');card.dataset.slot='technique:'+slot.id;card.setAttribute('aria-label',slot.name+'，'+(row?row.name+'，Lv '+row.level:view?.open?'未装备':'未装备，尚未开放'));card.setAttribute('aria-disabled',String(!view?.open));
  const icon=row?techniqueIcon(ctx,row):el('span','technique-icon-placeholder','空');icon.setAttribute('aria-hidden','true');
  const name=el('strong','technique-name',row?.name||'未装备');if(row)name.dataset.grade=row.grade;
  card.append(el('small','technique-role',slot.name),icon,name,el('small','technique-level',row?`Lv ${row.level}`:'Lv —'));grid.append(card);
 }
 section.append(grid);
 const rules=el('details','technique-rules');rules.append(el('summary','','功法品阶与修炼规则'));
 const grades=el('div','technique-grade-list');
 for(const grade of techniqueRules.grades){const label=el('span','technique-grade',`${grade.name} · Lv ${grade.max_level}`);label.dataset.grade=grade.id;grades.append(label);}
 rules.append(grades,el('p','muted',view?.open?'装备至少一部功法才可获得击杀修为；装备中的功法同时获得经验。闭关修炼后续开放。':'功法开放后，主角需装备至少一部功法，击杀才可获得修为。闭关修炼后续开放。'));section.append(rules);
 return section;
}

export function techniqueIcon(ctx,row,profile='compact'){
 const binding=ctx.data.presentation?.technique_icons?.[row.id]||{};
 return itemIcon({asset_id:row.asset_id,asset:binding.asset,fallback:'other',profile});
}

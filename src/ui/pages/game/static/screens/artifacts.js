// Artifact definitions and legal actions come from the authoritative read model.
import {el,button,empty,link} from '../components/dom.js';
import {confirmSheet} from '../components/features.js';
import {itemIcon,resourceIcon} from '../components/item-icon.js';

function artifactIcon(ctx,id){return itemIcon({...ctx.data.presentation?.artifact_icons?.[id],fallback:'equipment',profile:'detail'});}

function requirements(ctx,rows){
 const host=el('div');
 for(const row of rows){const line=el('p','icon-label');line.dataset.resourceId=row.resource_id;line.append(resourceIcon(ctx,row.resource_id),el('span','',`${row.name} ×${row.quantity}（持有${row.current}，保留${row.reserved}）`));host.append(line);}
 return host;
}
function detail(ctx,id){
 const view=ctx.data.view.artifacts,row=view.catalog.find(r=>r.id===id),body=el('div');
 body.append(artifactIcon(ctx,id));
 body.append(el('p','',`${row.source_name} · 100层Boss材料炼制`),el('p','',row.effect_description),el('p','muted',`等级上限 ${row.max_level} · 强化上限 +${row.max_enhancement}`));
 for(const [key,n]of Object.entries(row.stats))body.append(el('p','',`${{attack_milli:'攻击',armor_milli:'护甲',max_hp_milli:'生命'}[key]} +${Math.round(n/1000)}`));
 const send=(name,payload)=>ctx.economyAction(name,payload);
 if(!row.owned){
  body.append(el('h3','','炼制材料'),requirements(ctx,row.requirements),el('p','',`炼制时间 ${row.duration_ms/3600000} 小时，离线继续；开工即扣材料，完成自动入藏。每种法宝仅炼制一件。`));
  for(const reason of row.craft_reasons)body.append(el('p','blocking',reason));
  const start=button('开始炼制',()=>confirmSheet(ctx,'炼制'+row.name,`消耗所列材料，炼制${row.duration_ms/3600000}小时；开工后不可取消。`,()=>send('artifact_craft',{artifact_id:id})),'primary');start.disabled=ctx.busy||!row.can_craft;body.append(start);
 }else{
  body.append(el('p','',`Lv ${row.level} · 强化 +${row.enhancement} · ${row.next_xp===null?'已满级':`经验 ${row.xp} / ${row.next_xp}`}`));
  const equip=button(row.equipped?'卸下法宝':'装备法宝',()=>send(row.equipped?'artifact_unequip':'artifact_equip',row.equipped?{}:{artifact_id:id}),'primary');equip.disabled=ctx.busy||!view.can_change;body.append(equip);
  body.append(el('h3','','投喂升级'),el('p','muted','只消耗超过材料保留量的库存；已开工的配方材料已扣除。满级不消耗，达到满级所需数量以外的材料保留。'));
  const material=el('select'),count=el('input'),preview=el('p','muted');material.setAttribute('aria-label','投喂材料');count.type='number';count.min='1';count.max='10000';count.value='1';count.setAttribute('aria-label','投喂数量');
  for(const row of view.feed){const option=el('option','',`${row.name}（可用${row.available}，每个${row.xp}经验）`);option.value=row.resource_id;material.append(option);}material.value=view.feed[0]?.resource_id||'';
  const selected=()=>view.feed.find(r=>r.resource_id===material.value);
  const feed=button('投喂材料',()=>{const value=selected(),quantity=Number(count.value);if(!value)return;confirmSheet(ctx,'投喂'+row.name,`${value.name} ×${quantity}，最多获得${value.xp*quantity}经验（达到满级时自动减少消耗）。`,()=>send('artifact_feed',{artifact_id:id,resource_id:value.resource_id,quantity}));},'secondary');
  const update=()=>{const value=selected(),n=Number(count.value);preview.textContent=value?`预计获得 ${value.xp*n} 经验；材料可用 ${value.available}。`:'';feed.disabled=ctx.busy||!view.can_change||row.next_xp===null||!value||!Number.isInteger(n)||n<1||n>10000||n>value.available;};
  material.addEventListener('change',update);count.addEventListener('input',update);update();
  const controls=el('div','policy-field');controls.append(material,count);body.append(controls,preview,feed);
  body.append(el('h3','','法宝强化'),requirements(ctx,row.enhance_cost));const enhance=button(row.enhancement>=row.max_enhancement?'强化已满级':'强化至 +'+(row.enhancement+1),()=>confirmSheet(ctx,'强化'+row.name,'消耗所列材料，提升法宝基础属性。',()=>send('artifact_enhance',{artifact_id:id})),'secondary');enhance.disabled=ctx.busy||!row.can_enhance;body.append(enhance);
  if(!view.can_change)body.append(el('p','blocking','请先恢复世界、完成续算、停止挂机，并结束或领取当前战斗，再更换或培养法宝。'));
 }
 body.append(link('前往来源副本','#adventure','external-link'));ctx.sheet(row.name,body);
}
export function renderArtifactLibrary(ctx){
 const host=el('section','artifact-library'),view=ctx.data.view.artifacts;host.dataset.id='artifact-library';host.append(el('h2','','法宝'));
 if(!view){host.append(empty('法宝尚未开放'));return host;}
 host.append(el('p','muted','Boss核心、大量材料与长时炼制凝成法宝。可装备一件，随击杀或投喂升级；强化提升基础属性。'));
 if(view.job){const job=el('section','panel--inset');job.dataset.id='artifact-crafting';job.append(el('h3','',view.job.name+' · 炼制中'),el('p','',`剩余 ${Math.ceil(view.job.remaining_ms/60000)} 分钟`));host.append(job);}
 const cards=el('div','recipe-grid artifact-grid');cards.dataset.id='forge-artifacts-grid';
 for(const row of view.catalog){const card=button('',()=>detail(ctx,row.id),'panel artifact-card');card.dataset.id='artifact-'+row.id;card.append(artifactIcon(ctx,row.id),el('strong','artifact-card-name',row.name),el('small','artifact-card-status',row.owned?`Lv ${row.level} · +${row.enhancement}${row.equipped?' · 已装备':''}`:'尚未炼成'),el('small','muted artifact-card-effect',row.effect_description));cards.append(card);}
 host.append(cards);
 return host;
}

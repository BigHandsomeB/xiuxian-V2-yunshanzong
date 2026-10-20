// Immortal-stone enclosures and spirit pools share layout, not their artwork.
import {el,button,facts,link} from '../components/dom.js';
import {resourceIcon,systemIcon} from '../components/item-icon.js';
import {confirmSheet} from '../components/features.js';
import {workerControls,renderProduction} from './economy.js';
import {renderFacility} from './sect-management.js';

const habitat=(ctx,bid)=>ctx.data.view.ecology?.habitats?.find(row=>row.building_id===bid);
const usable=ctx=>!ctx.busy&&ctx.data.view.ecology?.available;
const title=kind=>kind==='pasture'?'仙石灵兽苑':'清涟灵池';
const cellName=kind=>kind==='pasture'?'兽栏':'灵池';
const batches=ctx=>ctx.data.view.ecology?.batches||[];

function stockDetail(ctx,bid,index,speciesId){
 const h=habitat(ctx,bid),row=ctx.data.view.ecology.species.find(r=>r.id===speciesId);if(!h||!row)return;
 const free=h.cells.slice(index,index+row.slots),room=free.length===row.slots&&free.every(c=>!c.batch_id),can=usable(ctx)&&room&&h.free_workers>0&&row.max_purchase>0;
 const body=el('section','habitat-detail');body.append(resourceIcon(ctx,row.id,null,'detail'),el('h3','',row.name),facts([['购入费用',`${row.purchase_coins} 灵钱`],['占用格子',`${row.slots} 格`],['照料弟子','1 人'],['成熟时间',`${row.days} 游戏日`],['周期饲料',`${row.feed_name} ×${row.feed_quantity}`]]));
 body.append(el('p','muted',Object.keys(row.periodic_outputs).length?'成熟后自动采集周期产物，保留灵兽或水产继续生产。':'成熟后自动收获，并按原价购入幼体或鱼苗续养。'),el('p','muted','缺饲料暂停成长；缺补栏灵钱或仓容时保留成熟存栏。可在格子详情关闭自动续养。'));
 if(!room)body.append(el('p','blocking',`此品种需要从所选位置起连续 ${row.slots} 格空位。`));
 if(!h.free_workers)body.append(el('p','blocking','请先安排空闲照料弟子。'));
 for(const reason of row.blocking_reasons)body.append(el('p','blocking',reason));
 const buy=button(h.kind==='pasture'?'购入并安置':'投苗并安置',()=>{if(usable(ctx))ctx.economyAction('habitat_stock',{building_id:bid,slot_index:index,species_id:row.id});},'primary block');buy.disabled=!can;body.append(buy,button('返回选择',()=>openCell(ctx,bid,index),'secondary block'));ctx.sheet('安置'+row.name,body);
}

function batchDetail(ctx,bid,batchId){
 const row=batches(ctx).find(r=>r.batch_id===batchId);if(!row)return;
 const h=habitat(ctx,bid),body=el('section','habitat-detail'),inventory=ctx.data.view.inventory;
 body.append(resourceIcon(ctx,row.species_id,null,'detail'),el('h3','',row.name),facts([['状态',row.reason],['生长进度',`${row.progress_percent}%`],['存栏',`${row.count} 只`],['照料',row.count===1?'每只一名弟子':'原有批次，进度与数量保留']]));
 const repeat=button(row.repeat?'停止自动续养':'开启自动续养',()=>ctx.economyAction('habitat_repeat',{batch_id:batchId,enabled:!row.repeat}),'secondary block');repeat.disabled=!usable(ctx);body.append(repeat);
 const output=(values)=>Object.entries(values).map(([id,n])=>`${inventory[id]?.name||id} ×${n}`).join('、');
 if(Object.keys(row.periodic_outputs).length){body.append(el('p','','周期产物：'+output(row.periodic_outputs)));const collect=button('采集产物',()=>ctx.economyAction('ecology_collect',{batch_id:batchId,mode:'periodic',count:1}),'primary block');collect.disabled=!usable(ctx)||!row.can_collect;body.append(collect);}
 body.append(el('p','','一次性收获：'+output(row.harvest_outputs)));
 const harvest=button(h.kind==='pasture'?'屠宰收获':'捕捞收获',()=>confirmSheet(ctx,'确认收获',`收获一只${row.name}，该个体将移出存栏；这次手动收获后不会自动补栏。`,()=>ctx.economyAction('ecology_collect',{batch_id:batchId,mode:'harvest',count:1})),'secondary block');harvest.disabled=!usable(ctx)||!row.can_harvest;body.append(harvest,el('p','muted','每个新安置的个体由一名弟子照料。大型品种占用相邻多格，同栏格指向同一个体。'));ctx.sheet(row.name,body);
}

function openCell(ctx,bid,index){
 const h=habitat(ctx,bid),cell=h?.cells.find(c=>c.index===index);if(!cell)return;
 if(cell.batch_id){batchDetail(ctx,bid,cell.batch_id);return;}
 const body=el('section','habitat-detail'),grid=el('div','recipe-grid');body.append(el('p','muted',`选择安置在第 ${index+1} 格${cellName(h.kind)}的品种。`));
 for(const row of ctx.data.view.ecology.species.filter(r=>r.building_id===bid)){
  const pick=button('',()=>stockDetail(ctx,bid,index,row.id),'panel recipe-card habitat-choice');pick.dataset.id='habitat-species-'+row.id;pick.append(resourceIcon(ctx,row.id),el('strong','recipe-card-name',row.name),el('span','recipe-meta',`${row.slots} 格 · 1 名弟子`));grid.append(pick);
 }
 body.append(grid);ctx.sheet(h.kind==='pasture'?'选择灵兽':'选择水产',body);
}

export function renderHabitats(ctx,kind){
 const h=ctx.data.view.ecology?.habitats?.find(row=>row.kind===kind);if(!h){
  const preview=el('section','habitat-panel');preview.dataset.id='unbuilt-habitat-'+kind;preview.append(el('h2','',title(kind)));const grid=el('div','garden-grid habitat-grid');grid.setAttribute('aria-label','未建设的格子预览');for(let n=0;n<5;n++){const tile=el('span','garden-plot habitat-cell habitat-preview');const art=systemIcon(ctx,kind==='pasture'?'habitat_enclosure':'habitat_pool');art.classList.add('garden-ground');tile.append(art,el('span','garden-lock','锁'));grid.append(tile);}preview.append(grid,el('p','muted','先建设设施，建成后按实际容量开放格子。'),renderFacility(ctx,kind));return preview;
 }
 const bid=h.building_id,host=el('section','habitat-panel habitat-panel--'+kind);host.dataset.id='habitats-'+bid;
 const head=el('header','garden-heading');head.append(systemIcon(ctx,kind==='pasture'?'ecology-pasture':'ecology-spring'),el('h2','',title(kind)),el('span','garden-caption',`${h.cells.filter(c=>c.batch_id).length} / ${h.capacity} 格`));host.append(head);
 const grid=el('div','garden-grid habitat-grid');grid.setAttribute('aria-label',title(kind)+'，每行五格');
 for(const cell of h.cells){
  const row=batches(ctx).find(b=>b.batch_id===cell.batch_id),tile=button('',()=>openCell(ctx,bid,cell.index),'garden-plot habitat-cell'+(row?' habitat-cell--occupied':''));tile.dataset.id=`habitat-${bid}-${cell.index}`;tile.dataset.habitatIndex=String(cell.index);tile.setAttribute('aria-label',`第 ${cell.index+1} 格${cellName(kind)}，${row?row.name+'，'+row.reason:'空闲，点击选择品种'}`);
  const background=systemIcon(ctx,kind==='pasture'?'habitat_enclosure':'habitat_pool');background.classList.add('garden-ground');background.setAttribute('aria-hidden','true');tile.append(background);
  if(!row){const plus=el('span','garden-plus','+');plus.setAttribute('aria-hidden','true');tile.append(plus);}
  else if(cell.primary){const animal=resourceIcon(ctx,row.species_id);animal.classList.add('habitat-animal');tile.append(animal,el('span','garden-growth',row.stage==='READY'?'待采集':row.stage==='MATURE'?'已成熟':`${row.progress_percent}%`));}
  else tile.append(el('span','habitat-linked','同栏'));
  grid.append(tile);
 }
 if(h.expandable){for(let i=0;i<5-h.capacity%5;i++){const locked=el('span','garden-plot garden-plot--locked');locked.dataset.id=`habitat-lock-${bid}-${i}`;locked.append(el('span','garden-lock','锁'));locked.setAttribute('aria-label','升级后解锁');grid.append(locked);}}
 host.append(grid,el('p','garden-hint',kind==='pasture'?'仙石为栏，灵兽栖养。点击空栏选择灵兽。':'灵泉入池，水族涵养。点击空池选择水产。'),workerControls(ctx,bid),link('升级与扩容','#building/construction','external-link'),el('p','muted','新安置个体自动采集或收获续养；每轮照常消耗饲料，补栏照常扣灵钱。'));
 const details=el('details','feature-rules');details.dataset.id='habitat-processing-'+bid;details.append(el('summary','','饲料加工与设施营造'),renderProduction(ctx,[kind]));host.append(details);return host;
}

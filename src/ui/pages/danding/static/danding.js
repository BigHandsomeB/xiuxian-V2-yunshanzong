// UI is an HTTP client. No local inventory, timers, rewards or eligibility rules.
import {SliceClient} from './session.js';
const $=id=>document.getElementById(id);
const reasons={WRONG_BUILDING:'建筑类型不符',BUILDING_NOT_READY:'丹鼎阁尚未建成',NO_ASSIGNED_WORKERS:'请安排一名炼丹弟子',BUILDING_BUSY:'丹炉正在使用中',PENDING_SETTLEMENT:'正在续算离线进度',PROGRESSION_DEFERRED:'尚未开放该条件',INSUFFICIENT_INPUTS:'灵草不足',INVENTORY_CAPACITY:'预计产物超出仓容'};
let data=null,timer=null,busy=false;
const client=new SliceClient({fetcher:fetch.bind(window),storage:sessionStorage,uuid:()=>crypto.randomUUID(),notify:message=>{$('notice').textContent=message;}});
const names=amounts=>Object.entries(amounts).map(([key,n])=>`${data.view.inventory[key]?.name||key} × ${n}`).join('、');
const seconds=ms=>`${Math.ceil(ms/1000)} 秒`;
function image(id,row,fallback){const el=$(id);el.onerror=()=>{el.hidden=true;if(fallback)$(fallback).hidden=false;};el.hidden=!row;if(fallback)$(fallback).hidden=!!row;if(row&&el.getAttribute('src')!==row.url)el.src=row.url;}
function pair(list,key,value){const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=key;dd.textContent=value;list.append(dt,dd);}
function metrics(){const list=$('visual-metrics');list.replaceChildren();pair(list,'手机 DPR',String(devicePixelRatio));for(const [id,label] of [['scene-image','场景'],['pill-icon','丹药']]){const el=$(id);const r=el.getBoundingClientRect();pair(list,label,el.hidden?'未发布 / 占位':`Runtime ${el.naturalWidth}×${el.naturalHeight} · 显示 ${Math.round(r.width)}×${Math.round(r.height)} CSS px`);}}
function render(){if(!data)return;const v=data.view,a=v.alchemy,c=a.current,r=a.recipes[0],scene=data.presentation.scene;
$('building-name').textContent=v.building.name;$('scene-label').textContent=scene.label;
$('entry-state').textContent=c.status==='WORKING'?'炉中丹火正盛':c.status==='OUTPUT_READY'?'丹已成，等候入库':c.status==='COMPLETE'?'上一炉已成，可再开炉':'弟子与丹炉已备';
image('scene-image',scene.asset,'scene-fallback');image('entry-image',scene.asset,'entry-fallback');image('pill-icon',data.presentation.icons.pill,'pill-fallback');
$('scene-caption').textContent=scene.asset?(scene.mode==='static'?'静态内景 · 炼制进度以文字为准':scene.fallback?'使用当前已发布的内景；炼制状态以文字为准':''):'';
$('recipe-name').textContent=r?.display_name_zh||'暂无可用丹方';
const inputs=r?.batch_inputs&&Object.keys(r.batch_inputs).length?r.batch_inputs:r?.inputs_per_worker||{};
const outputs=r?.batch_outputs&&Object.keys(r.batch_outputs).length?r.batch_outputs:r?.outputs_per_base_worker||{};
$('recipe-summary').textContent=r?`${names(inputs)} → ${names(outputs)} · ${seconds(r.duration_ms)}`:'';
$('work-summary').textContent=`已安排 ${v.work.assigned_count} 人 · 炉内工作 ${v.work.working_count} 人`;
$('inventory').replaceChildren();for(const row of Object.values(v.inventory)){const el=document.createElement('span');el.textContent=`${row.name} ${row.quantity}`;$('inventory').append(el);}
$('blocking').textContent=(r?.blocking_reasons||[]).filter(x=>x!=='BUILDING_BUSY').map(x=>reasons[x]||'当前条件未满足').join(' · ');
$('start').hidden=['WORKING','OUTPUT_READY'].includes(c.status);$('start').disabled=busy||!r?.can_start;
$('start').textContent=busy?'正在处理…':c.status==='COMPLETE'?'再炼一炉':'开始炼丹';
$('retry-output').hidden=c.status!=='OUTPUT_READY';$('retry-output').disabled=busy;
$('progress').hidden=c.status!=='WORKING';$('remaining').hidden=c.status!=='WORKING';
if(c.status==='WORKING'){$('progress').value=Math.min(1,c.job.progress_milli/(r.duration_ms*1000));$('remaining').textContent=`余下 ${seconds(c.remaining_ms)} · 关闭页面后仍可继续`;$('job-message').textContent=scene.label+'，静候丹成。';}
else if(c.status==='COMPLETE')$('job-message').textContent=`炼制完成 · ${names(c.expected_outputs)} 已入库`;
else if(c.status==='OUTPUT_READY')$('job-message').textContent=`炼制已完成 · 仓库空间不足，${names(c.expected_outputs)} 等待入库`;
else $('job-message').textContent='丹炉静候下一炉灵药。';
$('assign').disabled=busy||!v.work.can_assign;$('unassign').disabled=busy||!v.work.can_unassign;
$('slots').textContent=`丹鼎阁 Lv${v.building.level} · 岗位 ${v.work.occupied_count} / ${v.work.slot_capacity} · 工作占用 ${v.work.working_count} 人`;
const list=$('requirements');list.replaceChildren();if(r){pair(list,'投入灵草',names(inputs));pair(list,'预计产出',names(outputs));pair(list,'炼制时长',seconds(r.duration_ms));pair(list,'劳动力',`至少 ${r.minimum_assigned_workers} 人 · 当前 ${v.work.assigned_count} 人`);pair(list,'建筑要求',`丹鼎阁 Lv${r.required_building_level}`);pair(list,'仓容',`${v.capacity.used} / ${v.capacity.effective}`);pair(list,'游戏节奏',`${v.time.day_length_ms/1000} 秒 / 游戏日`);}
metrics();route();}
function route(){const inside=location.hash==='#danding';$('sect').hidden=inside;$('danding').hidden=!inside;$('back').hidden=!inside;$('details').hidden=!inside;}
function schedule(){clearTimeout(timer);if(document.hidden||!data)return;if(data.view.alchemy.current.status==='WORKING'||data.view.time.pending)timer=setTimeout(()=>sync(false),2000);}
async function sync(advance=true){if(busy)return;busy=true;render();try{data=await client.sync(advance);$('notice').textContent='已读取正式存档';}catch(e){$('notice').textContent=e.message;if(e.login)location.href='/play/login'+location.hash;}finally{busy=false;render();schedule();}}
async function action(name){if(busy)return;busy=true;clearTimeout(timer);render();try{data=await client.action(name);$('notice').textContent=name==='start'?'已开炉，灵草投入丹炉':name==='assign'?'炼丹弟子已就位':'岗位配置已更新';}catch(e){$('notice').textContent=e.message;if(e.login)location.href='/play/login'+location.hash;try{data=await client.read();}catch{}}finally{busy=false;render();schedule();}}
$('start').addEventListener('click',()=>action('start'));$('assign').addEventListener('click',()=>action('assign'));$('unassign').addEventListener('click',()=>action('unassign'));$('retry-output').addEventListener('click',()=>sync(true));$('refresh').addEventListener('click',()=>sync(true));
function open(){metrics();$('sheet').showModal();} $('details').addEventListener('click',open);$('recipe-details').addEventListener('click',open);$('close-sheet').addEventListener('click',()=>$('sheet').close());
window.addEventListener('hashchange',route);document.addEventListener('visibilitychange',()=>{if(document.hidden)clearTimeout(timer);else sync(true);});window.addEventListener('pageshow',event=>{if(event.persisted)sync(true);});$('scene-image').addEventListener('load',metrics);$('pill-icon').addEventListener('load',metrics);route();sync(true);

import {offlineReportPresenter,settlementMessage} from './components/offline-report.js';
import {startIconDebug} from './components/icon-debug.js';
import {pageCache} from './components/page-cache.js';
import {retainScreen} from './components/retained-screen.js';
import {decorateControls,decorateShell} from './components/approved-controls.js';
import {themePreference} from './theme.js';
import {updateWorldControl} from './components/world-control.js';
import {connectionState} from './connection.js';
import {screenLifecycle,needsSimulationPoll} from './lifecycle.js';
import {gameView} from './adapters.js';
import {GameClient} from './api-client.js';
import {SaveStorage} from './save/storage.js';
import {SaveOwnership} from './save/ownership.js';
import {SaveCoordinator} from './save/sync.js';
import {ReviewClient} from './review-client.js';
import {parseRoute,mainTab,routeKey} from './router.js';
import {screens} from './screen-registry.js';
import {el,button} from './components/dom.js';
const $=id=>document.getElementById(id),host=$('screen'),connection=$('connection');
startIconDebug(window,host);
const localDesktop=window.desktopTransport===true;
const previewMode=document.body?.dataset?.uiReview==='true';
const client=previewMode?new ReviewClient({fetcher:fetch.bind(window),search:location.search}):new GameClient({local:localDesktop,fetcher:fetch.bind(window),storage:sessionStorage,uuid:()=>crypto.randomUUID(),notify:toast});
let saves=null,lastSavedRevision='',starting=!previewMode;
if(!previewMode)client.canWrite=()=>!starting&&!!saves?.canWrite;
const pages=pageCache(6);let context=null,lastRenderSignature=null,lastAssetManifest=null;const theme=themePreference(window);const health=connectionState();const lifetime=screenLifecycle();const ui={inventoryCategory:'all'},scroll=new Map();let data=null,busy=false,timer=null,cleanup=null,currentRoute=null,currentKey='',toastTimer=null,foregroundRefresh=false,syncFlight=null,syncing=false;
function toast(message){$('toast').textContent=message;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,3500);}
function text(node,value){if(node.textContent!==value)node.textContent=value;}
function showConnection(message='',mode=''){text(connection,message);connection.hidden=!message;connection.dataset.mode=mode;}
function connectionHealth(){const settling=health.state==='CONNECTED'?reportStatus():'';showConnection(settling?settling+'；补算完成前，出售、分解和穿脱装备等操作暂不可用，可切换页面浏览。':health.message(),settling?'settling':health.state.toLowerCase());if(health.state==='AUTH_REQUIRED'){const login=el('a','','重新登录');login.href='/game/login';connection.append(login);}}
function connected(){health.connected();connectionHealth();}
function closeSheet(){reportPresenter.dismiss();if($('sheet').open)$('sheet').close();}
function sheet(title,content){$('sheet-title').textContent=title;if(data)decorateControls(content,data);$('sheet-content').replaceChildren(content);if(!$('sheet').open)$('sheet').showModal();}
let reportStorage=null;try{reportStorage=window.localStorage;}catch{}
const reportPresenter=offlineReportPresenter({sheet,isOpen:()=>$('sheet').open,isCurrent:node=>$('sheet-content').children[0]===node,close:closeSheet,canPresent:()=>!previewMode&&!busy&&!document.hidden&&(!!data?.view.latest_battle_report||saves?.canWrite),acknowledge:acceptReport,loadReport:id=>client.api('offline-report/'+encodeURIComponent(id)),storage:reportStorage});
$('sheet').addEventListener('close',()=>reportPresenter.dismiss());
async function acceptReport(report_id){if(syncFlight)await syncFlight;if(busy)throw new Error('正在结算，请稍后收下。');busy=true;clearTimeout(timer);try{data=gameView(await client.acknowledgeReport(report_id));closeSheet();connected();}catch(error){if(client.current)data=gameView(client.current);throw error;}finally{busy=false;syncBusy(false);render();schedule();}}
function reportStatus(){const progress=client.settlementProgress||(data?.view.time?.pending&&data.view.time.offline_duration_ms!==undefined?{phase:'catchup',duration_ms:data.view.time.offline_duration_ms,percent:Math.max(0,Math.min(99,Math.floor(100*((data.view.time.simulation_time_ms??data.view.time.sim_time_ms)-data.view.time.from_sim_ms)/Math.max(1,data.view.time.target_sim_ms-data.view.time.from_sim_ms))))}:null);return settlementMessage(progress);}
function discardCurrent(){lifetime.detach();pages.delete(currentKey);cleanup=null;context=null;}
function render(routeChange=false){
 const route=parseRoute(location.hash),key=routeKey(route),changed=key!==currentKey,controlBusy=starting||(busy&&!syncing)||!!data?.view.time?.pending||(!previewMode&&!saves?.canWrite);
 if(changed&&cleanup){lifetime.detach();cleanup=null;context=null;}
 if(changed&&currentKey)scroll.set(currentKey,window.scrollY);if(changed)closeSheet();
 currentRoute=route;currentKey=key;for(const link of $('main-nav').querySelectorAll('[data-tab]')){if(link.dataset.tab===mainTab(route)){if(link.getAttribute('aria-current')!=='page')link.setAttribute('aria-current','page');}else if(link.getAttribute('aria-current'))link.removeAttribute('aria-current');}
 host.setAttribute('aria-busy',String(controlBusy));if(!data)return;decorateShell(data);const world=data.view.world;updateWorldControl($('world-toggle'),data,controlBusy);const pauseNotice=$('world-paused-notice');if(pauseNotice)pauseNotice.hidden=!world?.paused;text($('world-status'),reportStatus()||(world?.paused?'世界已暂停':'世界运行中'));reportPresenter.update(data);$('world-bar').dataset.paused=String(!!world?.paused);host.dataset.worldPaused=String(!!world?.paused);
 // Status updates preserve the current screen and active interaction state.
 if(context){context.data={...data,assetManifest:client.assetManifest};context.busy=controlBusy;if($('sheet').open)$('sheet-content').children[0]?.__refresh?.();context.combatReceipt=client.combatReceipt;context.cultivationReceipt=client.cultivationReceipt;context.combatProgress=client.combatProgress;}
 const renderData=data.view.time?.pending?{...data,view:{...data.view,revision:'pending',time:{pending:true}}}:data;
 const signature=JSON.stringify([renderData,controlBusy,key,ui,client.combatReceipt,client.cultivationReceipt,client.combatProgress,client.economyReceipt,currentRoute.name==='settings'?saves?.uiStamp:null]);
 if(!changed&&!routeChange&&cleanup?.update&&signature===lastRenderSignature&&client.assetManifest===lastAssetManifest)return;
 lastRenderSignature=signature;lastAssetManifest=client.assetManifest;
 if(!changed&&!routeChange&&cleanup?.update){cleanup.update({...data,assetManifest:client.assetManifest},controlBusy,client.combatReceipt,client.combatProgress);decorateControls(host,data);return;}
 const y=changed?(scroll.get(key)||0):window.scrollY;
 const cached=changed?pages.get(key):null;
 if(cached){host.replaceChildren(cached.node);cleanup=cached.controller;context=cached.ctx;context.combatReceipt=client.combatReceipt;context.cultivationReceipt=client.cultivationReceipt;context.combatProgress=client.combatProgress;lifetime.mount(cleanup);cleanup.update?.({...data,assetManifest:client.assetManifest},controlBusy,client.combatReceipt,client.combatProgress);decorateControls(host,data);if(document.hidden||world?.paused)lifetime.suspend();else lifetime.resume();window.scrollTo(0,y);host.focus({preventScroll:true});return;}
 if(!changed)discardCurrent();
 const ctx={theme,saves,data:{...data,assetManifest:client.assetManifest},route,ui,busy:controlBusy,sheet,sync,action,combatAction,cultivationAction,economyAction,cultivationReceipt:client.cultivationReceipt,combatReceipt:client.combatReceipt,combatProgress:client.combatProgress,redraw:()=>render(true),reloadAssets,afterMount:null};host.replaceChildren(screens[route.name].render(ctx));decorateControls(host,data);cleanup=ctx.afterMount?ctx.afterMount():retainScreen(host.children[0],ctx,screens[route.name].render,fresh=>decorateControls(fresh,data));context=ctx;pages.put(key,{node:host.children[0],controller:cleanup,ctx});lifetime.mount(cleanup);if(document.hidden||data.view.world?.paused)lifetime.suspend();
 window.scrollTo(0,y);if(changed)host.focus({preventScroll:true});
}
function schedule(){clearTimeout(timer);if(previewMode)return;if(foregroundRefresh&&!document.hidden&&!busy){foregroundRefresh=false;timer=setTimeout(()=>sync(true,'前台恢复'),0);return;}if(document.hidden||!navigator.onLine||busy||health.state==='AUTH_REQUIRED')return;
 if(health.state==='DEGRADED'||health.state==='RECONNECTING'){const delay=health.retryDelay();if(delay!==null)timer=setTimeout(()=>sync(false,'轮询'),delay);return;}
 if(!data||data.view.world?.paused||(!localDesktop&&['battle','cultivation'].includes(currentRoute?.name)&&!data.view.combat?.auto?.enabled))return;if(localDesktop||needsSimulationPoll(currentRoute,data.view))timer=setTimeout(()=>sync(false,'轮询'),localDesktop?1000:data.view.combat?.auto?.enabled?2000:4000);
}
function failed(error){if(error.cancelled||error.name==='AbortError')return;health.failed(error,navigator.onLine);if(error.transport||error.login||!navigator.onLine){connectionHealth();lifetime.suspend();}else showConnection(error.message,error.status===409?'stale':'error');
 if(!data&&!error.transport&&!error.login){const box=el('div','error-state');box.append(el('p','',error.message),button('更新状态',()=>sync(true),'primary'));host.replaceChildren(box);}
}
const busyControls=new Map();
function syncBusy(pending){
 const readOnly=!previewMode&&!saves?.canWrite;host.setAttribute('aria-busy',String(pending||readOnly));if(context)context.busy=pending||readOnly;
 if(pending){for(const root of [host,$('sheet-content')])for(const node of root.querySelectorAll('button')){busyControls.set(node,node.disabled);node.disabled=true;}}
 else{for(const [node,disabled]of busyControls)node.disabled=disabled;busyControls.clear();}
 $('refresh').disabled=pending;if(data)updateWorldControl($('world-toggle'),data,pending||readOnly);
}
// Background synchronization shares the request lane without locking mounted controls.
// Mutation handlers wait for that lane, so a click during a slow read is not dropped.
function sync(advance=true,source='用户操作'){if(busy)return syncFlight;const flight=runSync(advance,source);syncFlight=flight;flight.then(()=>{if(syncFlight===flight)syncFlight=null;},()=>{if(syncFlight===flight)syncFlight=null;});return flight;}
async function runSync(advance,source){syncing=true;busy=true;health.begin(!!data);connectionHealth();if(!data)syncBusy(true);try{data=gameView(await (advance?client.sync(true,source):client.poll(localDesktop||(currentRoute?.name==='building'&&currentRoute.id==='market'),source)));connected();}catch(error){failed(error);}finally{busy=false;syncing=false;syncBusy(false);render();if(!document.hidden&&!data?.view.world?.paused&&health.state==='CONNECTED')lifetime.resume();schedule();if(currentRoute?.name==='inventory'&&currentRoute.id==='catalog'&&!client.assetManifest&&!document.hidden)reloadAssets();}}
async function action(name){if(syncFlight)await syncFlight;if(busy)return;busy=true;clearTimeout(timer);syncBusy(true);try{data=gameView(await client.action(name));connected();toast(name==='start'?'已开炉，材料已投入丹炉。':name==='assign'?'炼丹弟子已就位。':'岗位已更新。');}catch(error){failed(error);if(!document.hidden)try{data=gameView(await client.read());connected();if(!error.login){toast(error.message);if(!error.transport)showConnection(error.message,error.status===409?'stale':'error');}}catch(retryError){failed(retryError);}}finally{busy=false;syncBusy(false);render();schedule();}}
async function combatAction(name,payload){if(syncFlight)await syncFlight;if(busy)return;busy=true;clearTimeout(timer);syncBusy(true);try{data=gameView(await client.combat(name,payload));connected();}catch(error){failed(error);if(!document.hidden)try{data=gameView(await client.read());connected();if(!error.login){toast(error.message);if(!error.transport)showConnection(error.message,error.status===409?'stale':'error');}}catch(retryError){failed(retryError);}}finally{busy=false;syncBusy(false);render();schedule();}return data;}
async function cultivationAction(name,payload={}){if(syncFlight)await syncFlight;if(busy)return;busy=true;clearTimeout(timer);syncBusy(true);try{data=gameView(await client.cultivation(name,payload));closeSheet();connected();toast(name==='cultivation_breakthrough'?'境界突破成功。':name==='cultivation_use_pill'?'修炼丹已使用，筑基修为已更新。':'凝气丹已使用，修为已更新。');}catch(error){failed(error);if(!document.hidden)try{data=gameView(await client.read());connected();if(!error.login){toast(error.message);if(!error.transport)showConnection(error.message,error.status===409?'stale':'error');}}catch(retryError){failed(retryError);}}finally{busy=false;syncBusy(false);render();schedule();}}
async function economyAction(name,payload){if(syncFlight)await syncFlight;if(busy)return;busy=true;clearTimeout(timer);syncBusy(true);try{data=gameView(await client.economy(name,payload));closeSheet();connected();toast((['equipment_equip','equipment_unequip','technique_equip','technique_unequip'].includes(name)?(data.view.combat?.status==='ACTIVE'?'配装已更换；当前战斗保持开战快照，下一场生效。':'配装已更换。'):null)||({building_upgrade:'建筑升级成功，已即时完成。',equipment_craft:'装备打造成功，已按战利品管家规则入库。',material_overflow:'材料折算设置已更新。'})[name]||'宗门经营状态已更新。');}catch(error){failed(error);if(!document.hidden)try{data=gameView(await client.read());connected();if(!error.login){toast(error.message);if(!error.transport)showConnection(error.message,error.status===409?'stale':'error');}}catch(retryError){failed(retryError);}}finally{busy=false;syncBusy(false);render();schedule();}}
async function worldAction(){if(syncFlight)await syncFlight;if(busy)return;busy=true;clearTimeout(timer);syncBusy(true);try{data=gameView(await client.world(data.view.world?.paused?'world_resume':'world_pause'));connected();toast(data.view.world.paused?'世界已暂停，生产时间已冻结。':'世界继续运行。');}catch(error){failed(error);if(!document.hidden)try{data=gameView(await client.read());connected();if(!error.login){toast(error.message);if(!error.transport)showConnection(error.message,error.status===409?'stale':'error');}}catch(retryError){failed(retryError);}}finally{busy=false;syncBusy(false);render();if(!document.hidden&&!data?.view.world?.paused&&health.state==='CONNECTED')lifetime.resume();else lifetime.suspend();schedule();}}
$('world-toggle')?.addEventListener('click',worldAction);
async function reloadAssets(){if(syncFlight)await syncFlight;if(busy)return;busy=true;render();try{client.assetManifest=(await client.api('assets')).presentation;data=gameView(await client.read());toast('已重新加载素材。');}catch(error){failed(error);}finally{busy=false;pages.clearExcept(currentKey);render(true);schedule();}}
$('refresh').addEventListener('click',()=>sync(true));$('close-sheet').addEventListener('click',closeSheet);$('sheet').addEventListener('click',event=>{if(event.target===$('sheet')){const rect=$('sheet').getBoundingClientRect();if(event.clientY<rect.top||event.clientX<rect.left||event.clientX>rect.right)closeSheet();}});
window.addEventListener('hashchange',()=>{clearTimeout(timer);render(true);schedule();if(currentRoute.name==='inventory'&&currentRoute.id==='catalog'){reloadAssets();return;}if((['battle','inventory','adventure','building','settings','sect'].includes(currentRoute.name)&&data?.view.combat)||(currentRoute.name==='cultivation'&&data?.view.cultivation))sync(false);});window.addEventListener('offline',()=>{clearTimeout(timer);client.cancelRead();health.offline();connectionHealth();lifetime.suspend();});window.addEventListener('online',()=>sync(true));
document.addEventListener('visibilitychange',()=>{host.dataset.backgroundHidden=String(document.hidden);if(document.hidden){saves?.flush({hidden:true});clearTimeout(timer);clearTimeout(toastTimer);client.cancelRead();lifetime.suspend();}else{saves?.refreshServer().then(()=>saves.flush());if(busy)foregroundRefresh=true;else sync(true,'前台恢复');}});
window.addEventListener('pagehide',()=>{saves?.flush({hidden:true});saves?.suspend();});
window.addEventListener('pageshow',event=>{if(event.persisted)saves?.resume().then(()=>sync(true,'前台恢复'));});
function saveChanged(){const notice=$('save-notice');if(notice){text(notice.firstChild,saves?.describe()||'正在连接存档');notice.hidden=!!saves?.canWrite&&!saves?.row.conflict&&saves?.row.current?.source!=='import';}if(data&&!busy)render();}
async function start(){render();if(previewMode){sync(true,'前台恢复');return;}try{
 await client.read();data=gameView(client.current);
 let local;try{local=window.localStorage;}catch{local=null;}
 const storage=new SaveStorage({indexedDB:window.indexedDB,localStorage:local}),uuid=()=>crypto.randomUUID();
 const owner=new SaveOwnership({navigator,Channel:window.BroadcastChannel,storage,uuid});
 saves=new SaveCoordinator({client,storage,owner,navigator,uuid,onChange:saveChanged,setInterval:window.setInterval?.bind(window),clearInterval:window.clearInterval?.bind(window)});
 const notice=el('div','panel');notice.id='save-notice';notice.setAttribute('role','status');notice.append(el('span','','正在连接存档'),el('a','',' 查看存档'));notice.lastChild.href='#settings';host.parentNode.insertBefore(notice,host);
 client.onCommitted=path=>{if(path==='command')client.backupCritical=true;};
 client.onSettlementProgress=()=>{if(data){text($('world-status'),reportStatus()||(data.view.world?.paused?'世界已暂停':'世界运行中'));connectionHealth();}};
 client.onCombatProgress=()=>{if(busy&&client.current){data=gameView(client.current);render();}};
 let backupTimer=null;
 function captureBackup(critical=false){clearTimeout(backupTimer);backupTimer=null;return saves.refreshServer(critical);}
 window.addEventListener('pagehide',()=>{if(backupTimer!==null)captureBackup().then(()=>saves.flush({hidden:true}));});
 client.onSnapshot=view=>{const signature=[view.save_id,view.generation,view.revision].join(':');if(signature!==lastSavedRevision||client.backupCritical){lastSavedRevision=signature;const critical=!!client.backupCritical;client.backupCritical=false;if(localDesktop&&!critical){if(backupTimer===null)backupTimer=setTimeout(()=>captureBackup(),5000);}else captureBackup(critical);}};
 render(); // Show the validated read model while local backup ownership initializes.
 await saves.start(client.current.view.save_id);starting=false;render();sync(true,'前台恢复');
 }catch(error){failed(error);render();}}
start();

import {el,button} from './dom.js';
import {resourceIcon} from './item-icon.js';

// Browser-only presentation preference, independent of settlement and report receipts.
export function offlineBattlePreference(storage=null){
 const key='xianxia-offline-battle-popup-v1';let enabled=true;
 try{enabled=storage?.getItem(key)!=='off';}catch{}
 return {get enabled(){return enabled;},set(value){enabled=!!value;try{storage?.setItem(key,enabled?'on':'off');}catch{}}};
}
export const EQUIPMENT_PAGE_SIZE=50;
const qualityNames={white:'凡品',green:'灵品',blue:'玄品',rare:'稀有'};
const signed=n=>n>0?'+'+n:String(n);
export function offlineHours(ms){return (ms/3600000).toFixed(ms<3600000?2:1);}
export function settlementMessage(progress){return progress?.phase==='catchup'?`正在补算离线进度 ${progress.percent}% · 升了 ${progress.levels_gained||0} 级` : '';}

export const stopReasonName={NORMAL:'正常结束',COMPLETED:'正常结束（已通关）',DEFEATED:'战败',STORAGE_FULL:'满仓',WORLD_PAUSED:'世界暂停',LEGACY_BATTLE:'需处理原有战斗'};
export function simulationStamp(ms,dayLength){
 if(!Number.isFinite(ms)||ms<0||!Number.isFinite(dayLength)||dayLength<=0)return '时间未记录';
 const watches=['子','丑','寅','卯','辰','巳','午','未','申','酉','戌','亥'];
 return `第${Math.floor(ms/dayLength)+1}日 · ${watches[Math.floor(ms%dayLength/dayLength*12)]}时`;
}
export function offlineBattleContent(data,report,onClose){
 const root=el('div','offline-report'),body=el('div','offline-report-body');root.append(body);
 body.append(el('p','',`离线时长 ${offlineHours(report.duration_ms)} 小时`),el('p','',`共 ${report.battles} 场 · 胜 ${report.wins} 场 · 胜率 ${(report.win_rate_bps/100).toFixed(1)}%`));
 if(report.duration_ms>report.end_sim_ms-report.from_sim_ms)body.append(el('p','offline-report-cap',`已按计算时的离线上限结算；当前上限 ${(data.view?.time?.offline_cap_ms??86400000)/3600000} 小时`));
 const coins=el('div','row offline-material-row');coins.append(resourceIcon({data},'coins'),el('span','',`灵钱 +${report.coins}（含材料溢出折算 ${report.overflow_coins}）`));body.append(coins,el('p','',`获得装备 ${report.equipment_count} 件（含生产产出，自动处理前）`),el('h3','','入库材料 / 物品'));
 const names=data.view.offline_report_names?.items||{};
 for(const [id,n]of Object.entries(report.materials).sort((a,b)=>a[0].localeCompare(b[0]))){const row=el('div','row offline-material-row');row.dataset.resourceId=id;row.append(resourceIcon({data},id),el('span','',`${names[id]||data.view.inventory?.[id]?.name||id} +${n}`));body.append(row);}
 if(!Object.keys(report.materials).length)body.append(el('p','muted','无新增入库物品'));
 for(const [id,n]of Object.entries(report.converted_materials))body.append(el('p','muted',`${names[id]||data.view.inventory?.[id]?.name||id} ${n} 份已折算为灵钱`));
 body.append(el('p','',`停机原因：${stopReasonName[report.stop_reason]||report.stop_reason}`),el('p','muted',`停机时间：${simulationStamp(report.stop_sim_ms,data.view.time?.day_length_ms)}`));
 const footer=el('div','offline-report-footer');footer.append(button('关闭战报',onClose,'primary block'));root.append(footer);return root;
}

export function offlineReportContent(data,report,onAccept,loadReport=null){
 const root=el('div','offline-report'),body=el('div','offline-report-body');root.append(body);
 const v=data.view,names=v.offline_report_names||{},name=id=>names.items?.[id]||v.inventory?.[id]?.name||v.holdings?.[id]?.name||id;
 const section=(title,rows)=>{const box=el('section','detail-module');box.append(el('h3','',title));for(const text of rows)box.append(el('p','row',text));body.append(box);return box;};
 body.append(el('p','',`离线时长 ${offlineHours(report.duration.actual_ms)} 小时`));
 if(report.summary_count>1)body.append(el('p','',`已合并 ${report.summary_count} 份离线报告，时长与收益为累计值。`));
 if(report.duration.capped)body.append(el('p','offline-report-cap',`已按计算时的离线上限结算；当前上限 ${(data.view?.time?.offline_cap_ms??86400000)/3600000} 小时`));
 const changes=Object.entries(report.items).sort((a,b)=>Math.abs(b[1])-Math.abs(a[1])||a[0].localeCompare(b[0]));
 const materials=section('材料 / 物品变化',changes.length?[]:['无变化']);
 for(const [id,n]of changes){const row=el('div','row offline-material-row');row.append(resourceIcon({data},id),el('span','',`${name(id)} ${signed(n)}`));materials.append(row);}
 const e=report.equipment,box=section('装备',Object.entries(e.quality_counts).map(([q,n])=>`${qualityNames[q]||q}：获得 ${n.gained}，减少 ${n.removed}（出售 ${n.sold} / 分解 ${n.salvaged}）`));
 if(!Object.keys(e.quality_counts).length)box.append(el('p','','无变化'));
 let ids=[...new Set([...e.added_ids,...e.removed_ids])];
 if(ids.length){
  const details=el('div','offline-equipment-details');details.hidden=true;let page=0;
  // Index existing instances once. Missing instances use IDs/status, never reconstructed stats.
  const instances=new Map((v.equipment?.instances||[]).map(row=>[row.instance_id,row]));
  const sold=new Set(e.sold_ids),salvaged=new Set(e.salvaged_ids),removed=new Set(e.removed_ids);
  let pages=Math.ceil(ids.length/EQUIPMENT_PAGE_SIZE),loaded=!e.ids_truncated;
  function draw(){const list=el('div','offline-equipment-page');for(const id of ids.slice(page*EQUIPMENT_PAGE_SIZE,(page+1)*EQUIPMENT_PAGE_SIZE)){
    const row=instances.get(id),status=sold.has(id)?'已出售':salvaged.has(id)?'已分解':removed.has(id)?'已不在仓库':row?'已入库':'已不在仓库';
    const item=el('p','row',`${row?.name||id} · ${row?qualityNames[row.quality]||row.quality:'实例'} · ${status}`);item.dataset.reportEquipmentId=id;list.append(item);
   }
   const nav=el('div','offline-report-pages'),prev=button('上一页',()=>{page--;draw();}),next=button('下一页',()=>{page++;draw();});prev.disabled=page===0;next.disabled=page===pages-1;nav.append(prev,el('span','',`${page+1} / ${pages}`),next);details.replaceChildren(list,nav);
  }
  const total=Math.max(ids.length,Object.values(e.quality_counts).reduce((n,row)=>n+row.gained,0));
  const loadError=el('p','offline-report-error');loadError.setAttribute('role','status');box.append(loadError);
  const toggle=button(`展开装备列表（${total}）`,async()=>{
    if(details.hidden&&!loaded){toggle.disabled=true;loadError.textContent='';try{
      if(!loadReport)throw Error('请刷新页面后查看完整装备记录。');
      const full=await loadReport(report.report_id);ids=[...new Set([...full.equipment.added_ids,...full.equipment.removed_ids])];pages=Math.ceil(ids.length/EQUIPMENT_PAGE_SIZE);
      for(const [set,key]of [[sold,'sold_ids'],[salvaged,'salvaged_ids'],[removed,'removed_ids']]){set.clear();for(const id of full.equipment[key])set.add(id);}loaded=true;
    }catch(error){loadError.textContent=error.message||'记录读取失败，请重试。';return;}finally{toggle.disabled=false;}}
    details.hidden=!details.hidden;toggle.textContent=details.hidden?`展开装备列表（${total}）`:'收起装备列表';if(!details.hidden)draw();else details.replaceChildren();});toggle.setAttribute('aria-expanded','false');toggle.addEventListener('click',()=>toggle.setAttribute('aria-expanded',String(!details.hidden)));box.append(toggle,details);
 }
 const recipes=v.economy?.recipes||[];
 section('炼丹 / 生产',Object.entries(report.production).length?Object.entries(report.production).map(([id,r])=>`${names.recipes?.[id]||recipes.find(row=>row.recipe_id===id||row.id===id)?.name||id}：完成 ${r.completed_count} 次；产出 ${[...Object.entries(r.outputs).map(([rid,n])=>`${name(rid)} ×${n}`),...(r.equipment_count?[`装备 ×${r.equipment_count}`]:[])].join('、')||'无'}`):['无完成记录']);
 section('战斗',[`胜 ${report.combat.wins} 场 / 负 ${report.combat.losses} 场`,...Object.entries(report.combat.floors).map(([id,r])=>`${names.dungeons?.[id]||id}：${r.before} → ${r.after} 层（${signed(r.after-r.before)}）`)]);
 const r=report.recruitment,c=report.cultivation;
 section('招募 / 修炼',[`招募完成 ${r.completed_count} 次；弟子 ${r.before} → ${r.after}（${signed(r.after-r.before)}）`,`境界 ${names.realms?.[c.realm_before]||c.realm_before||'无变化'} → ${names.realms?.[c.realm_after]||c.realm_after||'无变化'}；升了 ${c.levels_gained||0} 级`]);
 section('拍卖 / 寄卖',report.commerce.length?report.commerce.map(row=>`${row.kind==='auction'?'拍卖':'寄卖'} ${name(row.resource_id)}：${row.success?'成功':'未成交'}，待领取${row.coins?`（灵钱 ${row.coins}）`:''}`):['无新增结算结果']);
 const footer=el('div','offline-report-footer'),error=el('p','offline-report-error');error.setAttribute('role','status');
 const accept=button('收下',async()=>{accept.disabled=true;error.textContent='';try{await onAccept(report.report_id);}catch(cause){error.textContent=cause.message||'确认失败，请重试。';}finally{accept.disabled=false;}},'primary block');footer.append(error,accept);root.append(footer);return root;
}

// Opening/dismissing never acknowledges. A fresh page can present the persisted unread queue.
export function offlineReportPresenter({sheet,isOpen,canPresent,acknowledge,isCurrent=()=>false,close=()=>{},loadReport=null,storage=null,battleEnabled=()=>true}){
 const presented=new Set();let identity='',current=null;
 function dismiss(){if(!current?.war||current.dismissed)return;current.dismissed=true;try{storage?.setItem('xianxia-offline-battle-read-v1:'+identity,current.id);}catch{}}
 function show(data,report){presented.add(report.report_id);const war=Number.isSafeInteger(report.battles);const content=war?offlineBattleContent(data,report,()=>{dismiss();close();}):offlineReportContent(data,report,acknowledge,loadReport);current={id:report.report_id,content,war};sheet(war?'离线战报':'离线收益报告',content);}
 return {dismiss,update(data){const v=data.view,key=`${v.save_id}:${v.generation}`;if(identity!==key){if(current&&isCurrent(current.content))close();presented.clear();current=null;identity=key;}
   if(!canPresent()||v.time?.pending)return;
   const allowBattle=battleEnabled();
   if(!allowBattle&&current?.war){if(isCurrent(current.content))close();current=null;}
   const report=(allowBattle?v.latest_battle_report:null)||v.offline_reports?.[0];
   if(report&&report===v.latest_battle_report){try{if(storage?.getItem('xianxia-offline-battle-read-v1:'+identity)===report.report_id)return;}catch{}}
   // A queue merge or another tab's acknowledgement can replace the displayed ID.
   if(current&&isOpen()&&isCurrent(current.content)&&!(v.latest_battle_report?.report_id===current.id||v.offline_reports?.some(r=>r.report_id===current.id))){
    if(report)show(data,report);else{close();current=null;}return;
   }
   if(isOpen()||!report||presented.has(report.report_id))return;
   show(data,report);
 }};
}

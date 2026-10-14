// Native DOM/client checks; not a browser layout or real-device performance claim.
async function testOfflineReportUI({dom,report,client,game,css}){
 let checks=0;const check=(value,message)=>{if(!value)throw Error(message);checks++;};
 function node(tag){return {tagName:tag.toUpperCase(),children:[],dataset:{},attrs:{},textContent:'',hidden:false,disabled:false,events:{},append(...nodes){this.children.push(...nodes);},replaceChildren(...nodes){this.children=[...nodes];},setAttribute(key,value){this.attrs[key]=value;},addEventListener(type,callback){(this.events[type]??=[]).push(callback);},async click(){for(const callback of this.events.click||[])await callback({});}};}
 const document={createElement:node};
 const d=new Function('document',dom.replace(/^export /gm,'')+';return {el,button};')(document);
 const r=new Function('el','button','resourceIcon',report.replace(/^import .*$/gm,'').replace(/^export /gm,'')+';return {offlineReportContent,offlineReportPresenter,settlementMessage};')(d.el,d.button,(_,id)=>d.el('span','item-icon',id));
 const all=root=>[root,...root.children.flatMap(all)],texts=root=>all(root).map(n=>n.textContent).join('\n');
 const ids=Array.from({length:503},(_,i)=>'save:1:i:'+i);
 const fixture={report_id:'save:1:r:1',summary_count:1,duration:{actual_ms:80*3600000,settled_ms:72*3600000,capped:true},items:{wood:-20,grain:50,coins:3},equipment:{added_ids:ids,removed_ids:ids,sold_ids:ids.slice(0,250),salvaged_ids:ids.slice(250),quality_counts:{green:{gained:503,removed:503,sold:250,salvaged:253}}},production:{grain:{completed_count:4,outputs:{grain:50},equipment_count:0}},combat:{wins:20,losses:1,floors:{thorn_path:{before:1,after:4}}},recruitment:{completed_count:1,before:2,after:3},cultivation:{realm_before:'realm_0',realm_after:'realm_0',before:0,after:0},commerce:[]};
 const data={view:{save_id:'save',generation:1,time:{pending:false},offline_reports:[fixture],equipment:{instances:[]},offline_report_names:{items:{wood:'灵木',grain:'灵谷',coins:'灵钱'},recipes:{grain:'灵谷采集'},dungeons:{thorn_path:'荆棘古道'},realms:{realm_0:'炼气'}}}};
 for(const width of [320,390,430])for(const theme of ['light','dark']){
  document.documentElement=node('html');document.documentElement.setAttribute('data-theme',theme);document.documentElement.clientWidth=width;
  const layout=r.offlineReportContent(data,fixture,async()=>{});
  check(texts(layout).includes('收下')&&texts(layout).includes('已按 72 小时上限结算'),`Report controls and cap content exist at ${width}px/${theme}`);
  check(!all(layout).some(n=>n.dataset.reportEquipmentId),`Equipment remains collapsed at ${width}px/${theme}`);
 }
 const start=Date.now();let accepted=[];let root=r.offlineReportContent(data,fixture,async id=>accepted.push(id));
 check(!all(root).some(n=>n.dataset.reportEquipmentId),'Equipment collapsed renders zero instance rows');
 check(texts(root).includes('已按 72 小时上限结算')&&texts(root).includes('80.0'),'Actual duration and cap text');
 const strings=all(root).map(n=>n.textContent);check(strings.indexOf('灵谷 +50')<strings.indexOf('灵木 -20'),'Signed deltas sorted by absolute quantity');
 check(texts(root).includes('获得 503')&&texts(root).includes('出售 250 / 分解 253'),'Quality summary independent of missing instances');
 const toggle=all(root).find(n=>n.textContent.startsWith('展开装备列表'));await toggle.click();
 const visited=[];for(let page=0;page<11;page++){
  const rows=all(root).filter(n=>n.dataset.reportEquipmentId);check(rows.length<=50,'At most 50 rows mounted on page '+page);visited.push(...rows.map(n=>n.dataset.reportEquipmentId));
  check(rows.every(n=>n.textContent.includes('已出售')||n.textContent.includes('已分解')),'Deleted instances keep disposition on page '+page);
  const next=all(root).find(n=>n.textContent==='下一页');if(page===10)check(next.disabled,'Last page disabled');else await next.click();
 }
 check(visited.length===503&&new Set(visited).size===503,'All equipment IDs reachable without duplicate/missing rows');
 await toggle.click();check(!all(root).some(n=>n.dataset.reportEquipmentId),'Collapsing releases equipment DOM');
 await all(root).find(n=>n.textContent==='收下').click();check(accepted[0]===fixture.report_id,'Only accept submits report identity');
 root=r.offlineReportContent(data,fixture,async()=>{throw Error('fixture offline');});await all(root).find(n=>n.textContent==='收下').click();check(texts(root).includes('fixture offline')&&!all(root).find(n=>n.textContent==='收下').disabled,'Failed acknowledgement stays readable and retryable');
 let detailLoads=0;const small={...fixture,equipment:{...fixture.equipment,ids_truncated:true,...Object.fromEntries(['added_ids','removed_ids','sold_ids','salvaged_ids'].map(k=>[k,fixture.equipment[k].slice(0,50)]))}};
 const bounded=r.offlineReportContent(data,small,async()=>{},async id=>{check(id===fixture.report_id,'Details requested for committed report identity');detailLoads++;return fixture;});
 const expand=all(bounded).find(n=>n.textContent.startsWith('展开装备列表'));await expand.click();
 check(detailLoads===1&&all(bounded).filter(n=>n.dataset.reportEquipmentId).length===50,'Truncated projection lazily loads complete IDs and mounts one page');
 check(texts(bounded).includes('1 / 11'),'Full on-demand result has all pages');await expand.click();await expand.click();check(detailLoads===1,'Re-expanding retains fetched report details');
 const noLoader=r.offlineReportContent(data,small,async()=>{});await all(noLoader).find(n=>n.textContent.startsWith('展开装备列表')).click();check(texts(noLoader).includes('请刷新页面'),'Missing loader has an explicit recovery message');
 check(r.settlementMessage({phase:'catchup',duration_ms:80*3600000,percent:42}).includes('正在补算离线进度 42%'),'Progress uses the catch-up percentage label');
 let opened=0,open=false,can=true;const options={sheet(){opened++;open=true;},isOpen:()=>open,canPresent:()=>can,acknowledge:async()=>{}};
 const presenter=r.offlineReportPresenter(options);presenter.update(data);check(opened===1,'Unread report presented');open=false;presenter.update(data);check(opened===1,'Dismiss does not immediately reopen during same page session');
 r.offlineReportPresenter(options).update(data);check(opened===2,'Fresh page presents persisted unread report');open=false;
 presenter.update({...data,view:{...data.view,generation:2}});check(opened===3,'Generation change resets presentation session');open=false;
 r.offlineReportPresenter(options).update({...data,view:{...data.view,time:{pending:true}}});check(opened===3,'Pending settlement delays popup');
 r.offlineReportPresenter(options).update({...data,view:{...data.view,offline_reports:[]}});check(opened===3,'Read report absent after refresh');
 let shownRoot=null,shownIds=[];open=false;
 const live=r.offlineReportPresenter({sheet(title,content){shownRoot=content;open=true;shownIds.push(title);},isOpen:()=>open,isCurrent:content=>content===shownRoot,close(){open=false;shownRoot=null;},canPresent:()=>true,acknowledge:async()=>{}});
 const second={...fixture,report_id:'save:1:r:2'};live.update({...data,view:{...data.view,offline_reports:[fixture,second]}});open=false;
 live.update({...data,view:{...data.view,offline_reports:[fixture,second]}});check(shownIds.length===1,'Dismissing oldest does not expose an unacknowledgeable later report');
 open=true;const summary={...fixture,report_id:'save:1:r:5',summary_count:5};live.update({...data,view:{...data.view,offline_reports:[summary]}});
 check(shownIds.length===2&&texts(shownRoot).includes('已合并 5 份'),'Merge updates a currently open obsolete report');
 live.update({...data,view:{...data.view,offline_reports:[]}});check(!open,'Another acknowledgement closes the obsolete report sheet');
 const Client=new Function(client.replace(/^export /gm,'')+';return GameClient;')();
 let revision=1,left=3,sim=0,queue=[],serial=0,paused=true,loseAck=true;const memory=new Map(),calls=[];
 const snapshot=()=>({protocol_version:1,csrf:'test',view:{save_id:'save',generation:1,revision,world:{paused},time:{simulation_time_ms:sim,pending:!!left,continuation:left?{save_id:'save',generation:1,revision,target_sim_ms:120000,state_fingerprint:'a'.repeat(64)}:null},offline_reports:queue,equipment:{instances:[]}}});
 const receipts=new Map();const fetcher=async(url,options={})=>{
  if(!options.body)return {ok:true,status:200,json:async()=>snapshot()};const body=JSON.parse(options.body);calls.push(body);
  let payload=receipts.get(body.request_id);
  if(!payload){if(url.endsWith('/settle')){left--;sim+=40000;revision++;if(!left)queue=[fixture];payload={protocol_version:1,save_id:'save',generation:1,revision,receipt:{request_id:body.request_id,committed_revision:revision,result:{offline_report:left?null:fixture}},time:{simulation_time_ms:sim,pending:!!left,target_sim_ms:120000,from_sim_ms:0,remaining_ms:120000-sim,offline_duration_ms:120000,settlement_duration_ms:120000,continuation:left?{save_id:'save',generation:1,revision,target_sim_ms:120000,state_fingerprint:'a'.repeat(64)}:null}};}else{check(body.command.name==='offline_report_ack'&&body.command.payload.report_id===fixture.report_id,'Acknowledgement sends only matching report identity');queue=[];revision++;payload={receipt:{request_id:body.request_id}};}receipts.set(body.request_id,payload);}
  if(url.endsWith('/command')&&loseAck){loseAck=false;throw Error('network lost after commit');}
  return {ok:true,status:200,json:async()=>payload};
 };
 const storage={getItem:k=>memory.get(k)||null,setItem:(k,v)=>memory.set(k,v),removeItem:k=>memory.delete(k)};
 const c=new Client({fetcher,storage,uuid:()=>String(++serial)});const progress=[];c.onSettlementProgress=p=>progress.push(p);await c.read();
 for(let n=0;n<3;n++)await c.settle(true);
 check(progress[0].percent===33&&progress[1].percent===66&&progress[2]===null,'Fixed window progresses across multiple lightweight rounds');
 await c.read();check(c.current.view.offline_reports.length===1,'Completed report available after authoritative refresh');
 try{await c.acknowledgeReport(fixture.report_id);}catch(error){check(error.transport,'Response loss retains pending acknowledgement');}
 check(!!c.pending(),'Uncertain acknowledgement intent is retained');
 await c.acknowledgeReport(fixture.report_id);check(!c.pending()&&c.current.view.offline_reports.length===0,'Replay and refresh clear already read report');
 const commands=calls.filter(b=>b.command);check(commands.length===2&&commands[0].request_id===commands[1].request_id,'Acknowledgement replay uses same request ID');
 check(c.current.view.world.paused,'Report acceptance works in paused world');
 check(game.includes('reportPresenter.update(data)')&&game.includes('client.onSettlementProgress='),'Actual shell wired for popup and progress');
 check(css.includes('var(--surface)')&&css.includes('var(--warn-bg)')&&css.includes('overflow-wrap:anywhere'),'Sheet uses theme tokens and wraps narrow-screen content');
 return {checks,status:'PASS',equipment_count:503,max_mounted_rows:50,native_render_and_paging_ms:Date.now()-start};
}

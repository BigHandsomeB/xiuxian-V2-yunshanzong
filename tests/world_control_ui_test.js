function testWorldControl(updateWorldControl){
 let checks=0;const check=(v,m)=>{if(!v)throw Error(m);checks++;};
 const control={attrs:{},dataset:{},replaceChildren(icon){this.children=[icon];},setAttribute(k,v){this.attrs[k]=v;}},data={view:{world:{paused:false,can_pause:true,can_resume:false}},presentation:{system_icons:{pause:{asset_id:'pause.official'},resume:{asset_id:'resume.official'}}}};
 updateWorldControl(control,data,false);check(control.attrs['aria-label']==='暂停世界','Running action label');check(control.children.length===1&&control.children[0].dataset.assetId==='pause.official','Official icon is inside actual control');check(!control.disabled,'Running control enabled');const icon=control.__stateIcon;
 updateWorldControl(control,data,true);check(control.disabled,'Pending command disables control');check(control.__stateIcon===icon,'Pending does not recreate icon');
 data.view.world={paused:true,can_pause:false,can_resume:true};updateWorldControl(control,data,false);check(control.attrs['aria-label']==='继续运行'&&control.dataset.paused==='true','Paused resume action');check(!control.disabled,'Resume enabled');
 check(control.children[0].dataset.assetId==='resume.official','Approved resume replaces pause icon');
 data.view.world={paused:false,can_pause:false,can_resume:false};data.view.time={pending:{}};updateWorldControl(control,data,false);check(!control.disabled,'Pending catch-up allows explicit pause workflow');updateWorldControl(control,data,true);check(control.disabled,'Catch-up cannot submit twice');data.view.time.pending=null;updateWorldControl(control,data,false);check(control.disabled,'No pending still respects domain denial');
 data.view.world={paused:true,can_pause:false,can_resume:false};updateWorldControl(control,data,false);check(control.disabled,'Domain availability respected');return {tests:checks,status:'PASS'};
}


// Exercise the actual GameClient HTTP/replay lane with deterministic chunked authority.
async function testWorldClient(source){
 const Client=new Function(source.replace(/^export /gm,'')+';return GameClient;')();
 let checks=0;const check=(v,m)=>{if(!v)throw Error(m);checks++;};
 function fixture({chunks=8,pending=true,stall=false,conflicts=0}={}){
  let revision=1,left=chunks,processed=0,paused=false,serial=0,fail=null;
  const memory=new Map(),receipts=new Map(),requests=[],storage={getItem:k=>memory.get(k)||null,setItem:(k,v)=>memory.set(k,v),removeItem:k=>memory.delete(k)};
  const snapshot=()=>({protocol_version:1,csrf:'fixture-csrf',view:{save_id:'fixture-save',generation:1,revision,time:{sim_time_ms:processed,pending:pending?{target_sim_ms:chunks,processed_total:processed}:null,continuation:pending?{revision}:null},world:{paused}}});
  const fetcher=async(url,options={})=>{
   const body=options.body?JSON.parse(options.body):null;if(!body)return {ok:true,status:200,json:async()=>snapshot()};
   requests.push({path:url.split('/').pop(),body});
   if(receipts.has(body.request_id))return {ok:true,status:200,json:async()=>receipts.get(body.request_id)};
   if(body.expected_revision!==revision)return {ok:false,status:409,json:async()=>({code:'STALE',error:'fixture stale'})};
   let result={receipt:{request_id:body.request_id}};
   if(url.endsWith('/settle')){
    if(!stall){left=Math.max(0,left-1);processed++;revision++;pending=left>0;}
   }else if(body.command.name==='world_pause'){
    if(pending||left>0||conflicts-->0)return {ok:false,status:409,json:async()=>({code:'STALE',error:'fixture catch-up'})};
    paused=true;revision++;
   }else if(body.command.name==='world_resume'){paused=false;revision++;}else revision++;
   receipts.set(body.request_id,result);
   if(fail===body.command?.name||fail==='settle'&&url.endsWith('/settle')){fail=null;throw Error('fixture lost response');}
   return {ok:true,status:200,json:async()=>result};
  };
  const client=new Client({fetcher,storage,uuid:()=>`fixture-${++serial}`});
  return {client,requests,receipts,snapshot,setFail:name=>fail=name,storage};
 }
 const settles=f=>f.requests.filter(r=>r.path==='settle'),pauses=f=>f.requests.filter(r=>r.body.command?.name==='world_pause');
 let f=fixture();await f.client.world('world_pause');check(f.snapshot().view.world.paused,'One pause click must finish >3 pending chunks and pause');check(settles(f).length===8&&pauses(f).length===1,'All pending chunks then exactly one pause');
 f=fixture({chunks:5,pending:false});await f.client.world('world_pause');check(f.snapshot().view.world.paused,'Fresh wall backlog must settle before pause even without a pending cursor');
 f=fixture({chunks:70});await f.client.world('world_pause');check(f.snapshot().view.world.paused&&settles(f).length===70,'A longer backlog must not have another arbitrary chunk cutoff');
 f=fixture({chunks:2,conflicts:1});let commandConflict=false;try{await f.client.world('world_pause');}catch(e){commandConflict=e.status===409;}check(commandConflict&&!f.snapshot().view.world.paused&&pauses(f).length===1,'409 pause command reads latest and remains visible without automatic resubmit');
 f=fixture({stall:true});let stalled=false;try{await f.client.world('world_pause');}catch(e){stalled=e.message.includes('续算');}check(stalled&&!f.client.active&&settles(f).length===1,'No progress exits without a tight endless request loop');
 f=fixture({chunks:0,pending:false});await f.client.world('world_pause');const count=settles(f).length;await f.client.world('world_resume');check(!f.snapshot().view.world.paused&&settles(f).length===count,'Resume never settles a paused world');
 f=fixture({chunks:5});f.setFail('settle');let lost=false;try{await f.client.world('world_pause');}catch(e){lost=!!e.transport;}const saved=f.client.pending();check(lost&&saved?.path==='settle','Lost chunk response retains original idempotent intent');await f.client.world('world_pause');check(f.snapshot().view.world.paused&&settles(f)[0].body.request_id===settles(f)[1].body.request_id,'Replayed chunk then continuation reaches pause without duplicate mutation');
 f=fixture({chunks:1});f.setFail('world_pause');try{await f.client.world('world_pause');}catch{}const pauseIntent=f.client.pending();await f.client.world('world_pause');check(f.snapshot().view.world.paused&&pauses(f).length===2&&pauses(f)[0].body.request_id===pauses(f)[1].body.request_id,'Lost pause response safely replays same request without another pause');check(pauseIntent?.body.command.name==='world_pause','Pending pause intent retained');
 f=fixture({chunks:1});await f.client.read();f.storage.setItem(f.client.key,JSON.stringify({path:'command',save_id:'fixture-save',body:{request_id:'unrelated',generation:1,expected_revision:1,command:{name:'equipment_lock',version:1,payload:{}}}}));await f.client.world('world_pause');check(f.snapshot().view.world.paused,'An unrelated replayed command must not swallow the new pause click');
 f=fixture({chunks:5});const flight=f.client.world('world_pause');let locked=false;try{await f.client.world('world_pause');}catch(e){locked=e.message.includes('尚未完成');}await flight;check(locked&&pauses(f).length===1,'Single-flight guard prevents double submission');
 f=fixture({chunks:3});const fetch=f.client.fetcher;let recovered=false;f.client.fetcher=async(url,options={})=>{if(options.body&&url.endsWith('/settle')){recovered=true;return {ok:false,status:409,json:async()=>({code:'STALE',error:'fixture restore'})};}const response=await fetch(url,options);if(recovered&&!options.body){const data=await response.json();data.view.generation=2;return {ok:true,status:200,json:async()=>data};}return response;};let restored=false;try{await f.client.world('world_pause');}catch(e){restored=e.message.includes('恢复换代');}check(restored&&settles(f).length===0&&!pauses(f).length,'Restore during continuation refuses any mutation of the replacement generation');
 return {tests:checks,status:'PASS'};
}

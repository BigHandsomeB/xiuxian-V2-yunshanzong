// Real HTTP client path used by the battle screen's stop-auto button.
async function testDungeonAutoClient(source){
 const Client=new Function(source.replace(/^export /gm,'')+';return GameClient;')();
 let checks=0;const check=(v,m)=>{checks++;if(!v)throw Error(m);};
 function fixture({chunks=8,stall=false,settleConflicts=0,commandConflict=false,restore=false,sameTimestamp=false}={}){
  let left=chunks,revision=1,processed=0,enabled=true,serial=0,generation=1;
  const requests=[],memory=new Map();
  const snapshot=()=>({protocol_version:1,csrf:'fixture',view:{save_id:'fixture',generation,revision,world:{paused:false},time:{simulation_time_ms:sameTimestamp?0:processed,pending:!!left,continuation:left?{revision,target_sim_ms:chunks}:null},combat:{auto:{enabled}}}});
  const client=new Client({uuid:()=>String(++serial),storage:{getItem:k=>memory.get(k)||null,setItem:(k,v)=>memory.set(k,v),removeItem:k=>memory.delete(k)},fetcher:async(url,options={})=>{
   if(!options.body)return {ok:true,status:200,json:async()=>snapshot()};
   const body=JSON.parse(options.body);requests.push({url,body});
   if(url.endsWith('/settle')){
    if(settleConflicts-->0){revision++;return {ok:false,status:409,json:async()=>({code:'STALE',error:'fixture settle conflict'})};}
    if(restore){generation++;restore=false;return {ok:false,status:409,json:async()=>({code:'STALE',error:'fixture restore'})};}
    if(!stall){left=Math.max(0,left-1);processed++;revision++;}
   }else{
    if(left||commandConflict)return {ok:false,status:409,json:async()=>({code:'STALE',error:'进度正在续算，请更新后操作'})};
    enabled=body.command.payload.enabled;revision++;
   }
   return {ok:true,status:200,json:async()=>({receipt:{request_id:body.request_id}})};
  }});return {client,requests,snapshot};
 }
 const stop=f=>f.client.combat('dungeon_auto',{enabled:false,mode:'push',floor:1,floor_count:1});
 const commands=f=>f.requests.filter(r=>r.url.endsWith('/command'));
 for(const chunks of [8,70]){const f=fixture({chunks});let error;try{await stop(f);}catch(e){error=e;}check(!error&&!f.snapshot().view.combat.auto.enabled,`Stopping auto must finish ${chunks} chunks without asking to update state (received: ${error?.message})`);check(commands(f).length===1,'Stop command submitted exactly once');}
 const conflict=fixture({chunks:8,settleConflicts:1});await stop(conflict);check(!conflict.snapshot().view.combat.auto.enabled,'Settlement 409 rereads then continues catch-up');
 const rejected=fixture({chunks:1,commandConflict:true});let error;try{await stop(rejected);}catch(e){error=e;}check(error?.status===409&&commands(rejected).length===1&&!rejected.client.pending(),'Command 409 stays visible and is never resubmitted');
 const stalled=fixture({stall:true});error=null;try{await stop(stalled);}catch(e){error=e;}check(!!error&&!stalled.client.active&&stalled.requests.length===1&&!commands(stalled).length,'Stalled settlement stops without an endless loop or a stop command');
 const restored=fixture({restore:true});error=null;try{await stop(restored);}catch(e){error=e;}check(!!error&&!commands(restored).length,'Restore during catch-up refuses to stop another generation');
 const progress=fixture({chunks:8}),updates=[];progress.client.onCombatProgress=p=>updates.push(p);await stop(progress);
 check(updates.some(p=>p?.phase==='catchup'&&p.percent===50),'Stop workflow reports actual halfway catch-up progress');
 check(updates.some(p=>p?.phase==='command')&&updates.at(-1)===null&&!progress.client.combatProgress,'Submission phase and final progress cleanup are reported');
 const failed=fixture({stall:true}),failedUpdates=[];failed.client.onCombatProgress=p=>failedUpdates.push(p);try{await stop(failed);}catch{}
 check(failedUpdates.at(-1)===null&&!failed.client.combatProgress,'Failed catch-up clears progress and releases the button');
 const sharedTime=fixture({sameTimestamp:true});await stop(sharedTime);check(!sharedTime.snapshot().view.combat.auto.enabled,'Real boolean pending projection allows multiple committed events at the same simulation timestamp');
 return {tests:checks,status:'PASS'};
}

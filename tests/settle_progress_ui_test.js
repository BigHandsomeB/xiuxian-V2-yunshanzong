// Runs the production client, including command submission and legacy-server fallback.
async function testSettleProgress(source){
 const Client=new Function(source.replace(/^export /gm,'')+';return GameClient;')();let checks=0;
 const check=(v,m)=>{if(!v)throw Error(m);checks++;};
 function fixture({legacy=false,bad=false,conflict=false}={}){
  let left=5,revision=1,serial=0,sim=0,enabled=true,paused=false;const calls=[],memory=new Map(),commits=[],snapshots=[];
  const continuation=()=>left?{save_id:'fixture',generation:1,revision,target_sim_ms:50,state_fingerprint:'a'.repeat(64)}:null;
  const snapshot=()=>({protocol_version:1,csrf:'fixture',view:{save_id:'fixture',generation:1,revision,world:{paused},time:{simulation_time_ms:sim,pending:!!left,continuation:continuation()},combat:{auto:{enabled}},equipment:{instances:[]}}});
  const client=new Client({uuid:()=>String(++serial),storage:{getItem:k=>memory.get(k)||null,setItem:(k,v)=>memory.set(k,v),removeItem:k=>memory.delete(k)},fetcher:async(url,options={})=>{
   calls.push(url);if(!options.body)return {ok:true,status:200,json:async()=>snapshot()};const body=JSON.parse(options.body);
   if(url.endsWith('/settle')){
    if(conflict){conflict=false;revision++;return {ok:false,status:409,json:async()=>({error:'fixture stale',code:'STALE'})};}
    left--;sim+=10;revision++;
    const reply={protocol_version:1,save_id:'fixture',generation:1,revision,receipt:{request_id:body.request_id,committed_revision:revision},time:{simulation_time_ms:sim,target_sim_ms:50,remaining_ms:50-sim,pending:!!left,continuation:continuation()}};
    if(bad)reply.time.continuation=left?{...continuation(),generation:2}:undefined;
    return {ok:true,status:200,json:async()=>legacy?{receipt:reply.receipt}:reply};
   }
   check(!left,'Command waits for complete fixed target');
   check(body.expected_revision===revision,'Command uses receipt committed revision');
   enabled=false;paused=body.command.name==='world_pause';revision++;
   return {ok:true,status:200,json:async()=>({receipt:{request_id:body.request_id}})};
  }});client.onCommitted=p=>commits.push(p);client.onSnapshot=v=>snapshots.push(v);return {client,calls,commits,snapshots,memory,snapshot};
 }
 for(const action of ['combat','world']){
  const f=fixture();if(action==='combat')await f.client.combat('dungeon_auto',{enabled:false,mode:'push',floor:1,floor_count:1});else await f.client.world('world_pause');
  check(f.calls.filter(x=>x.endsWith('/view')).length===2,'Only startup and final view during catch-up: '+action);
  check(f.calls.filter(x=>x.endsWith('/settle')).length===5,'All chunks resume without view');
  check(f.commits.length===1&&f.commits[0]==='command','Partial progress does not fetch a full save backup each round');
  check(f.snapshots.length===2&&f.snapshots[0].revision===1&&f.snapshots[1].revision===7,'Only complete views reach save observer');
  check(!f.client.pending()&&!f.client.active,'Pending intent and lock cleared');
 }
 for(const options of [{legacy:true},{bad:true},{conflict:true}]){
  const f=fixture(options);await f.client.combat('dungeon_auto',{enabled:false,mode:'push',floor:1,floor_count:1});
  check(!f.snapshot().view.combat.auto.enabled,'Fallback/409 catches up safely');check(f.calls.filter(x=>x.endsWith('/command')).length===1,'Fallback never repeats command');check(f.calls.filter(x=>x.endsWith('/view')).length>2,'Old or invalid response uses authoritative view');
 }
 return {checks,status:'PASS'};
}

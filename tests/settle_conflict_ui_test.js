async function testSettleConflict(source){
 const logs=[],Client=new Function('console',source.replace(/^export /gm,'')+';return GameClient;')({warn:(...args)=>logs.push(args)});
 let checks=0;const failures=[];const check=(v,m)=>{checks++;if(!v)failures.push(m);};
 function fixture({settleConflict=true,commandConflict=false,code='STALE',status=409}={}){
  let revision=1,serial=0,conflict=settleConflict;const requests=[],memory=new Map();
  const snapshot=()=>({protocol_version:1,csrf:'fixture',view:{save_id:'fixture',generation:1,revision,world:{paused:false},time:{pending:null,continuation:null},alchemy:{current:{status:'WORKING'}},economy:{needs_settlement:true}}});
  const client=new Client({storage:{getItem:k=>memory.get(k)||null,setItem:(k,v)=>memory.set(k,v),removeItem:k=>memory.delete(k)},uuid:()=>String(++serial),fetcher:async(url,options={})=>{
   const body=options.body?JSON.parse(options.body):null;requests.push({url,body});
   if(!body)return {ok:true,status:200,json:async()=>snapshot()};
   if(url.endsWith('/settle')&&conflict){conflict=false;revision++;return {ok:false,status,json:async()=>({code,current_revision:revision,error:'conflict'})};}
   if(url.endsWith('/command')&&commandConflict){revision++;return {ok:false,status:409,json:async()=>({code:'STALE',current_revision:revision,error:'command conflict'})};}
   revision++;return {ok:true,status:200,json:async()=>({receipt:{request_id:body.request_id}})};
  }});return {client,requests};
 }
 for(const [name,run]of [['sync',c=>c.sync(true,'前台恢复')],['poll',c=>c.poll()],['action',c=>c.action('assign')],['combat',c=>c.combat('dungeon_select',{})],['world',c=>c.world('world_pause')],['cultivation',c=>c.cultivation('cultivation_train',{})],['economy',c=>c.economy('automation_equipment',{})]]){
  const f=fixture();let error=null;try{await run(f.client);}catch(e){error=e;}
  check(!error,name+': settlement 409 must read and continue');
  check(f.client.current?.view.revision>=2,name+': adopts newer revision');
  check(!f.client.pending()&&!f.client.active,name+': releases lane and rejected intent');
 }
 for(const [name,run]of [['action',c=>c.action('assign')],['combat',c=>c.combat('combat_start',{})],['world',c=>c.world('world_pause')],['cultivation',c=>c.cultivation('cultivation_train',{})],['economy',c=>c.economy('equipment_lock',{})]]){
  const f=fixture({settleConflict:false,commandConflict:true});let error=null;try{await run(f.client);}catch(e){error=e;}
  check(error?.status===409,name+': command 409 remains visible');check(f.requests.filter(r=>r.url.endsWith('/command')).length===1,name+': command never auto resubmits');
  check(f.requests.at(-1).url.endsWith('/view'),name+': reads latest after rejected command');
 }
 for(const options of [{code:'CSRF',status:409},{status:500}]){const f=fixture(options);let error=null;try{await f.client.sync();}catch(e){error=e;}check(error?.status===options.status,'Login/transport failures still propagate');}
 check(logs.some(([tag,d])=>tag==='[game:409]'&&d.local_revision===1&&d.server_revision===2&&d.source==='前台恢复'&&typeof d.time==='string'),'409 log has time/local/server/source');
 check(logs.some(([,d])=>d.source==='轮询')&&logs.some(([,d])=>d.source==='用户操作'),'409 log distinguishes origins');
 if(failures.length)throw Error(failures.join('; '));return {tests:checks,status:'PASS'};
}

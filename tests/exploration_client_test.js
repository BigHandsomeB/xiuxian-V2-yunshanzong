// Shipping GameClient through its real economy/send/read paths; fake HTTP only.
async function testExplorationClient(source) {
 const GameClient=new Function('setTimeout','clearTimeout',source.replace(/export\s+/g,'')+';return GameClient;')(()=>1,()=>{});
 let checks=0;const check=(v,m)=>{if(!v)throw Error(m);checks++;};
 const intents=[['exploration_start',{region_id:'thorn_outskirts'}],['exploration_choose',{journey_id:'explore:1',choice_id:'leave'}]];
 for(const paused of [true,false])for(const [name,payload]of intents){
  const state={protocol_version:1,csrf:'fixture',view:{save_id:'fixture',generation:1,revision:7,world:{paused},time:{pending:false}}},requests=[],storage=new Map();
  const client=new GameClient({uuid:()=> 'request-fixture',storage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},fetcher:async(path,opt)=>{
   const body=opt.body?JSON.parse(opt.body):null;requests.push({path,body});
   if(path.endsWith('/command')){state.view.revision++;return {ok:true,status:200,json:async()=>({receipt:{committed_revision:state.view.revision}})};}
   return {ok:true,status:200,json:async()=>JSON.parse(JSON.stringify(state))};
  }});
  await client.economy(name,payload);
  const sent=requests.filter(r=>r.path.endsWith('/command'));check(sent.length===1,'one actual command '+name);check(sent[0].body.command.name===name,'accepted client command '+name);check(JSON.stringify(sent[0].body.command.payload)===JSON.stringify(payload),'unchanged intent '+name);check(sent[0].body.expected_revision===7,'current revision '+name);check(!storage.size,'committed intent cleared');check(client.current.view.revision===8,'updated view');check(requests.some(r=>r.path.endsWith('/settle'))===!paused,'pause preserves settlement behavior');
  state.view.time.pending=true;const count=requests.length;let error;try{await client.economy(name,payload);}catch(e){error=e;}
  check(error?.message.includes('续算'),'pending guard '+name);check(!requests.slice(count).some(r=>r.path.endsWith('/command')),'pending no mutation '+name);
 }
 return {checks,scope:'shipping GameClient, paused/running, actual transport envelope; mock HTTP'};
}

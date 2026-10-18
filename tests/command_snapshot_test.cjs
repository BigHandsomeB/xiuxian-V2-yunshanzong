// Exercise the shipping transport: reuse valid snapshots, reject stale/wrong receipts,
// and replay the same request after a lost response without duplicate submission IDs.
const fs=require('fs'),assert=require('node:assert/strict');
const source=fs.readFileSync('src/ui/pages/game/static/api-client.js','utf8');
const Client=new Function(source.replace(/^export /gm,'')+';return GameClient;')();
const state=revision=>({protocol_version:1,csrf:'fixture',save_id:'save',generation:1,revision,view:{save_id:'save',generation:1,revision,world:{paused:true},time:{pending:false}},presentation:{icons:{}}});
async function run(){
 for(const mode of ['valid','legacy','stale','wrong-receipt','lost-response']){
  let revision=1,lost=false;const requests=[],memory=new Map();
  const client=new Client({uuid:()=> 'same-intent',storage:{getItem:k=>memory.get(k)||null,setItem:(k,v)=>memory.set(k,v),removeItem:k=>memory.delete(k)},fetcher:async(url,opt)=>{
   const body=opt.body&&JSON.parse(opt.body);requests.push({url,body});
   if(!body)return {ok:true,status:200,json:async()=>state(revision)};
   revision=2;
   if(mode==='lost-response'&&!lost){lost=true;throw Error('lost response');}
   let reply={...state(mode==='stale'?0:revision),receipt:{request_id:mode==='wrong-receipt'?'other':body.request_id,committed_revision:revision}};
   if(mode==='legacy')reply={receipt:reply.receipt};
   return {ok:true,status:200,json:async()=>reply};
  }});
  if(mode==='lost-response'){
   await assert.rejects(()=>client.economy('sect_recruit',{}));assert(client.pending());
   await client.read();await client.replay();
   assert.deepEqual(requests.filter(r=>r.body).map(r=>r.body.request_id),['same-intent','same-intent']);
  }else{
   await client.economy('sect_recruit',{});
   assert.equal(requests.filter(r=>!r.body).length,mode==='valid'?1:2,mode);
  }
  assert.equal(client.current.view.revision,2);assert.equal(client.pending(),null);
 }
 for(const name of ['equipment_equip','equipment_unequip','technique_equip','technique_unequip']){
  const requests=[],memory=new Map();
  const client=new Client({uuid:()=> 'loadout',storage:{getItem:k=>memory.get(k)||null,setItem:(k,v)=>memory.set(k,v),removeItem:k=>memory.delete(k)},fetcher:async(url,opt)=>{
   requests.push(url);return {ok:true,status:200,json:async()=>({...state(2),receipt:{request_id:'loadout',committed_revision:2}})};
  }});
  client.current=state(1);await client.economy(name,{});
  assert.deepEqual(requests,['/game/api/command'],name+' skips redundant reads and retains command lane');
  assert.equal(client.current.view.revision,2);assert.equal(client.pending(),null);
 }
 for(const name of ['equipment_equip','equipment_unequip','technique_equip','technique_unequip']){
  const requests=[],memory=new Map();let unblock;
  const client=new Client({local:true,uuid:()=> 'native-intent',storage:{getItem:k=>memory.get(k)||null,setItem:(k,v)=>memory.set(k,v),removeItem:k=>memory.delete(k)},fetcher:async(url,opt)=>{
   requests.push(url);await new Promise(resolve=>unblock=resolve);
   return {ok:true,status:200,json:async()=>({...state(2),receipt:{request_id:'native-intent',committed_revision:2}})};
  }});
  client.current=state(1);client.current.view.world.paused=false;
  const first=client.economy(name,{});await assert.rejects(()=>client.economy(name,{}),/尚未完成/);
  while(!unblock)await Promise.resolve();unblock();await first;
  assert.deepEqual(requests,['/game/api/command'],name+' native running world uses one command without pre-settlement');
 }
 console.log('command snapshots: valid reuse, fallback, stale, receipt mismatch, lost-response replay PASS');
}
run().catch(e=>{console.error(e);process.exitCode=1;});

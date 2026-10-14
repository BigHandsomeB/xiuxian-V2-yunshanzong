// The actual bulk control explains each disabled state; no frontend reward simulation.
function testBulkAvailability(source){
 let checks=0;const check=(v,m)=>{if(!v)throw Error(m);checks++;};
 const el=(tag,cls='',text='')=>({tagName:tag,className:cls,textContent:text,children:[],append(...nodes){this.children.push(...nodes);}}),button=(text,click,cls)=>({...el('button',cls,text),click});
 const factory=new Function('el','button','document','confirmSheet',source.replace(/^import .*$/gm,'').replace(/export /g,'')+';return allEquipmentControls;');
 const render=factory(el,button,{getElementById:()=>null},()=>{});
 for(const [bulk,busy,paused,expected]of [[undefined,false,false,'尚未就绪'],[{count:2,can_process:true},true,false,'上一次操作'],[{count:2,can_process:false},false,false,'正在补算'],[{count:0,can_process:true},false,false,'没有可处理']]){
  const host=render({busy,data:{view:{world:{paused},equipment:{bulk}}}});check(host.children.filter(n=>n.tagName==='button').every(n=>n.disabled),'Unavailable actions stay disabled');check(host.children.some(n=>n.textContent.includes(expected)),'Unavailable actions show reason: '+expected);
 }
 const available=render({busy:false,data:{view:{world:{paused:false},equipment:{bulk:{count:2,can_process:true}}}}});check(available.children.filter(n=>n.tagName==='button').every(n=>!n.disabled),'Committed preview enables both actions');
 const paused=render({busy:false,data:{view:{world:{paused:true},equipment:{bulk:{count:2,can_process:true}}}}});check(paused.children.filter(n=>n.tagName==='button').every(n=>!n.disabled),'Paused committed preview enables both actions');
 return {checks,status:'PASS'};
}

// Click the shipped control, confirm, then execute through the shipped HTTP client.
async function testBulkExecution(equipmentSource,clientSource){
 let checks=0;const check=(v,m)=>{if(!v)throw Error(m);checks++;};
 const Client=new Function(clientSource.replace(/^export /gm,'')+';return GameClient;')();
 const el=(tag,cls='',text='')=>({tagName:tag,className:cls,textContent:text,children:[],append(...nodes){this.children.push(...nodes);}}),button=(text,click,cls)=>({...el('button',cls,text),click});
 let sheet;const control=new Function('el','button','document','confirmSheet',equipmentSource.replace(/^import .*$/gm,'').replace(/export /g,'')+';return allEquipmentControls;')(el,button,{getElementById:()=>({close(){}})},(ctx,title,description,submit)=>{sheet={title,description,submit};});
 for(const mode of ['sell','salvage']){
  const calls=[],commands=[],memory=new Map();let revision=1,count=2,pending=false,conflict=false;
  const digest='a'.repeat(64),preview=()=>({count,protected_count:4,can_process:!pending,selection_digest:digest,sell:{coins:10},salvage:{ore:2}});
  const snapshot=()=>({protocol_version:1,csrf:'fixture',view:{save_id:'fixture',generation:1,revision,world:{paused:false},time:{pending,continuation:null},inventory:{coins:{name:'灵钱'},ore:{name:'矿石'}},equipment:{bulk:preview()}}});
  const client=new Client({uuid:()=>String(revision),storage:{getItem:k=>memory.get(k)||null,setItem:(k,v)=>memory.set(k,v),removeItem:k=>memory.delete(k)},fetcher:async(url,options={})=>{
   calls.push(url);if(!options.body)return {ok:true,status:200,json:async()=>snapshot()};
   check(url.endsWith('/command'),'Bulk confirmation never settles before submitting');const body=JSON.parse(options.body);commands.push(body);
   check(body.command.name==='equipment_'+mode+'_all','Actual client submits the selected bulk command');
   check(Object.keys(body.command.payload).join(',')==='selection_digest'&&body.command.payload.selection_digest===digest,'Entire bag uses confirmed digest, not a filtered ID list');
   check(body.expected_revision===revision,'Actual client uses latest CAS revision');check(options.body.length<4096,'Bulk payload stays below command limit');
   if(conflict){conflict=false;revision++;return {ok:false,status:409,json:async()=>({error:'装备列表已变化，请重新确认',code:'STALE'})};}
   revision++;count=0;return {ok:true,status:200,json:async()=>({receipt:{result:{count:2}}})};
  }});
  await client.read();const ctx={busy:false,data:client.current,ui:{inventorySearch:'irrelevant filter'},economyAction:(name,payload)=>client.economy(name,payload)};
  const host=control(ctx),open=host.children.find(n=>n.textContent===(mode==='sell'?'一键出售':'一键分解'));check(open&&!open.disabled,'Usable inventory enables the action');
  open.click();check(commands.length===0,'Click requires explicit confirmation');check(sheet.description.includes('全部 2 件')&&sheet.description.includes('强化')&&sheet.description.includes('搜索和分类不限制'),'Confirmation shows scope and protection');
  await sheet.submit();check(commands.length===1&&client.current.view.equipment.bulk.count===0,'Confirm commits and refreshes the visible preview');check(!client.pending()&&!client.active,'Request and busy lock clear after success');
  check(control({...ctx,data:client.current}).children.filter(n=>n.tagName==='button').every(n=>n.disabled),'Empty bag disables further processing');
  count=2;conflict=true;let error;try{await client.economy('equipment_'+mode+'_all',{selection_digest:digest});}catch(e){error=e;}
  check(error?.status===409&&commands.length===2,'Selection conflict refreshes without resubmitting');check(count===2&&!client.pending(),'Conflict leaves equipment and pending intent intact/cleared respectively');
  pending=true;const submitted=commands.length;try{await client.economy('equipment_'+mode+'_all',{selection_digest:digest});}catch{}
  check(commands.length===submitted,'Pending catch-up prevents an unsafe bulk command');check(!calls.some(url=>url.endsWith('/settle')),'Bulk client never changes the confirmed bag through pre-settlement');
 }
 return {checks,status:'PASS'};
}

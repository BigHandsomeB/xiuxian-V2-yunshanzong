// Execute the shipped ES module in a native JS isolate; no Node/browser installation.
async function testDandingSession(source,fixture){
 const SliceClient=new Function(source.replace('export class SliceClient','class SliceClient')+';return SliceClient;')();
 const assert=(value,message)=>{if(!value)throw Error(message);};
 const clone=x=>JSON.parse(JSON.stringify(x));
 function setup(handler=()=>({ok:true,status:200,json:async()=>clone(fixture)}),saved=null){
  const values=new Map(saved?[['xianxia-danding-pending-v1',JSON.stringify(saved)]]:[]),calls=[];
  const storage={getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)};
  let counter=0;
  const client=new SliceClient({fetcher:async(url,options)=>{const call={url,body:options.body?JSON.parse(options.body):null};calls.push(call);return handler(call);},storage,uuid:()=>`request-${++counter}`});
  return {client,calls,values,storage};
 }
 let t=setup();await t.client.read();assert(t.calls.length===1&&!t.calls[0].body,'GET must stay pure');
 t=setup();await t.client.sync(true);assert(t.calls.map(x=>x.url.split('/').pop()).join(',')==='view,settle,view','Opening must explicitly settle then query');
 t=setup();await t.client.sync(false);assert(t.calls.length===1,'Idle polling must not settle');
 const working=clone(fixture);working.view.alchemy.current.status='WORKING';
 t=setup(()=>({ok:true,status:200,json:async()=>clone(working)}));await t.client.sync(false);assert(t.calls.some(c=>c.url.endsWith('settle')),'Working poll must use settlement');
 t=setup();await t.client.action('start');assert(t.calls.map(x=>x.url.split('/').pop()).join(',')==='view,settle,view,command,view','Start settles old elapsed time before creating Job');
 assert(t.calls[3].body.expected_revision===fixture.view.revision,'Command uses read model revision');assert(!t.values.size,'Committed request cleared');
 let release;t=setup(()=>new Promise(r=>release=r));const active=t.client.sync(false);let rejected=false;try{await t.client.action('start');}catch{rejected=true;}assert(rejected,'Concurrent actions must be locked');release({ok:true,status:200,json:async()=>clone(fixture)});await active;
 let first=true;t=setup(call=>{if(call.url.endsWith('command')&&first){first=false;throw Error('lost response');}return {ok:true,status:200,json:async()=>clone(fixture)};});
 try{await t.client.action('start');}catch{}const pending=JSON.parse([...t.values.values()][0]);assert(pending.path==='command','Uncertain commit intent retained');
 await t.client.action('start');const posts=t.calls.filter(c=>c.url.endsWith('command'));assert(posts.length===2&&posts[0].body.request_id===posts[1].body.request_id,'Retry must replay same request, not start a second batch');
 const pendingRecord={path:'command',save_id:fixture.view.save_id,body:{request_id:'persisted',generation:fixture.view.generation,expected_revision:fixture.view.revision,action:'start'}};
 t=setup(undefined,pendingRecord);await t.client.sync(true);assert(t.calls.find(c=>c.url.endsWith('command')).body.request_id==='persisted','Refresh must preserve replay identity');
 const old=clone(pendingRecord);old.body.generation--;t=setup(undefined,old);await t.client.sync(false);assert(!t.calls.some(c=>c.url.endsWith('command'))&&!t.values.size,'Recovery must stop old-generation replay');
 t=setup(call=>({ok:!call.body,status:call.body?409:200,json:async()=>call.body?{error:'过期',code:'STALE'}:clone(fixture)}));try{await t.client.action('start');}catch{}assert(!t.values.size,'Rejected stale intent cleared');
 t=setup(call=>({ok:!call.body,status:call.body?503:200,json:async()=>call.body?{error:'暂不可用',code:'SERVER'}:clone(fixture)}));try{await t.client.action('start');}catch{}assert(t.values.size===1,'Uncertain server failure stays retryable');
 t=setup(()=>({ok:false,status:401,json:async()=>({error:'请登录'})}));let login=false;try{await t.client.read();}catch(e){login=e.login;}assert(login,'Login expiry must be actionable');
 const resumed=clone(fixture);resumed.view.time.pending=true;resumed.view.time.continuation={save_id:'continuation'};
 t=setup(()=>({ok:true,status:200,json:async()=>clone(resumed)}));await t.client.sync(false);assert(t.calls.find(c=>c.body).body.continuation.save_id==='continuation','Resume passes server continuation without guessing');
 const older=clone(fixture);older.view.revision=0;t=setup(()=>({ok:true,status:200,json:async()=>clone(older)}));t.client.current=clone(fixture);t.client.current.view.revision=1;let stale=false;try{await t.client.read();}catch{stale=true;}assert(stale&&t.client.current.view.revision===1,'Older query must not roll UI back');
 const unsupported=clone(fixture);unsupported.protocol_version=2;t=setup(()=>({ok:true,status:200,json:async()=>clone(unsupported)}));let version=false;try{await t.client.read();}catch{version=true;}assert(version,'Unsupported protocol must be explicit');
 return {tests:14,status:'PASS'};
}

async function testDandingPage(source,sessionSource,html,fixture){
 const SliceClient=new Function(sessionSource.replace('export class SliceClient','class SliceClient')+';return SliceClient;')();
 const nodes=new Map(),timers=new Map(),listeners=new Map();let tick=0;
 function node(){return {hidden:false,disabled:false,textContent:'',children:[],attrs:{},listeners:{},naturalWidth:48,naturalHeight:48,value:0,
  addEventListener(k,f){this.listeners[k]=f;},append(...n){this.children.push(...n);},replaceChildren(...n){this.children=n;},getAttribute(k){return this.attrs[k]||null;},getBoundingClientRect(){return {width:48,height:48};},showModal(){this.open=true;},close(){this.open=false;},set src(v){this.attrs.src=v;},get src(){return this.attrs.src;}};}
 for(const id of [...html.matchAll(/id="([^"]+)"/g)].map(m=>m[1]))nodes.set(id,node());
 const document={hidden:false,getElementById:id=>nodes.get(id)||null,createElement:node,addEventListener:(k,f)=>listeners.set(k,f)};
 const window={addEventListener:(k,f)=>listeners.set(k,f)};const location={hash:'#danding'};const values=new Map();
 const storage={getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)};
 const fetched=[];const fetch=async(url,options)=>{fetched.push({url,options});return {ok:true,status:200,json:async()=>JSON.parse(JSON.stringify(fixture))};};
 const body=source.replace(/^import[^\n]+\n/m,'')+';return {sync,action,route,getData:()=>data};';
 const ui=new Function('SliceClient','document','window','location','sessionStorage','devicePixelRatio','crypto','fetch','setTimeout','clearTimeout',body)(SliceClient,document,window,location,storage,3,{randomUUID:()=>String(++tick)},fetch,(f,ms)=>{timers.set(++tick,{f,ms});return tick;},id=>timers.delete(id));
 for(let i=0;i<30;i++)await Promise.resolve();
 if(!ui.getData())throw Error('Startup did not load view');if(nodes.get('danding').hidden||!nodes.get('sect').hidden)throw Error('Danding route visibility wrong');
 if(nodes.get('recipe-name').textContent!==fixture.view.alchemy.recipes[0].display_name_zh)throw Error('Recipe not read from server');
 nodes.get('details').listeners.click();if(!nodes.get('sheet').open)throw Error('Details sheet did not open');nodes.get('close-sheet').listeners.click();if(nodes.get('sheet').open)throw Error('Sheet did not close');
 location.hash='#sect';listeners.get('hashchange')();if(nodes.get('sect').hidden||!nodes.get('danding').hidden)throw Error('Back navigation failed');
 document.hidden=true;listeners.get('visibilitychange')();if(timers.size)throw Error('Hidden tab continued polling');
 return {tests:4,status:'PASS'};
}

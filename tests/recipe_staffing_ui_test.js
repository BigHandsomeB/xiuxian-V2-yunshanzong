// Run shipped native ES modules in a V8 isolate. DOM harness tests behavior,
// not Safari layout, painting, or device performance.
async function testRecipeStaffingUI(sources,fixture,styles) {
 const assert=(v,m)=>{if(!v)throw Error(m);};const clone=v=>JSON.parse(JSON.stringify(v));let checks=0;
 const listeners=new Map(),timers=new Map(),fetches=[],storageValues=new Map();let serial=0;
 const store={getItem:k=>storageValues.get(k)||null,setItem:(k,v)=>storageValues.set(k,v),removeItem:k=>storageValues.delete(k)};
 const eventTarget=()=>({events:{},addEventListener(k,f){(this.events[k]??=[]).push(f);},removeEventListener(k,f){this.events[k]=(this.events[k]||[]).filter(x=>x!==f);},emit(k,e={}){for(const f of this.events[k]||[])f(e);}});
 let doc;
 function node(tag='div'){const n={...eventTarget(),tagName:tag.toUpperCase(),children:[],dataset:{},attrs:{},style:{},hidden:false,disabled:false,open:false,value:'',textContent:'',ownerDocument:doc,
 prepend(...children){for(const x of children)x.parentNode=this;this.children.unshift(...children);},append(...children){for(const x of children){x.parentNode=this;this.children.push(x);}},replaceChildren(...children){this.children=[];this.append(...children);},remove(){if(this.parentNode)this.parentNode.children=this.parentNode.children.filter(x=>x!==this);},setAttribute(k,v){this.attrs[k]=String(v);},getAttribute(k){return this.attrs[k]??null;},removeAttribute(k){delete this.attrs[k];},focus(){this.focused=true;},showModal(){this.open=true;},close(){this.open=false;},getBoundingClientRect(){return {width:390,height:500,top:0,left:0,right:390,bottom:500};},querySelectorAll(selector){return all(this).filter(x=>selector==='[data-tab]'?!!x.dataset.tab:false);},set src(v){this.attrs.src=v;},get src(){return this.attrs.src;}};
 n.querySelector=selector=>all(n).find(x=>selector==='input[type=number]'?x.tagName==='INPUT'&&x.type==='number':selector==='button.primary'?x.tagName==='BUTTON'&&x.classList.contains('primary'):false)||null;n.dispatchEvent=event=>{n.emit(event.type,event);return true;};n.classList={add(...keys){n.className=(n.className||'')+' '+keys.join(' ');},contains(k){return (n.className||'').split(' ').includes(k);}};return n;}
 function all(n){return [n,...n.children.flatMap(all)];}
 const nodes=new Map(['world-bar','world-status','world-toggle','screen','connection','main-nav','sheet','sheet-title','sheet-content','close-sheet','refresh','toast'].map(id=>[id,node()]));
 const win={...eventTarget(),scrollY:0,innerHeight:844,innerWidth:390,scrollTo(x,y){this.scrollY=y;},matchMedia:()=>({...eventTarget(),matches:false}),requestAnimationFrame:f=>{timers.set(++serial,f);return serial;},cancelAnimationFrame:id=>timers.delete(id)};
 doc={...eventTarget(),hidden:false,defaultView:win,createElement:tag=>node(tag),getElementById:id=>nodes.get(id)};for(const n of nodes.values())n.ownerDocument=doc;
 for(const name of ['sect','disciples','cultivation','inventory','adventure']){const a=node('a');a.dataset.tab=name;nodes.get('main-nav').append(a);}
 const location={hash:'',href:''},navigator={onLine:true};let current={};
 const fetch=async(url,options={})=>{fetches.push({url,body:options.body?JSON.parse(options.body):null});if(url.endsWith('/assets'))return {ok:true,status:200,json:async()=>({protocol_version:1,presentation:current.presentation})};return {ok:true,status:200,json:async()=>clone(current)};};
 const globals={Event:class {constructor(type){this.type=type;}},document:doc,window:win,location,navigator,fetch,sessionStorage:store,crypto:{randomUUID:()=>`00000000-0000-4000-8000-${String(++serial).padStart(12,"0")}`},setTimeout:(f,ms)=>{timers.set(++serial,{f,ms});return serial;},clearTimeout:id=>timers.delete(id)};
 const modules=new Map();
 function load(path){if(modules.has(path))return modules.get(path);let source=sources[path];assert(source!==undefined,`Missing module ${path}`);const imports={};source=source.replace(/^import\s+(.+?)\s+from\s+['"](.+?)['"];?\s*$/gm,(_,bindings,target)=>{let parts=path.split('/');parts.pop();for(const p of target.split('/')){if(p==='..')parts.pop();else if(p!=='.')parts.push(p);}const dependency=load(parts.join('/'));if(bindings.startsWith('* as '))imports[bindings.slice(5)]=dependency;else for(const entry of bindings.replace(/[{}]/g,'').split(',')){const [key,alias]=entry.trim().split(/\s+as\s+/);imports[alias||key]=dependency[key];}return '';});
 const exports=[...source.matchAll(/export\s+(?:async\s+)?(?:function|class|const)\s+(\w+)/g)].map(m=>m[1]);source=source.replace(/export\s+/g,'');const args={...globals,...imports};const output=new Function(...Object.keys(args),source+`;return {${exports.join(',')}};`)(...Object.values(args));modules.set(path,output);return output;}

 const check=(v,m)=>{assert(v,m);checks++;},base='src/ui/pages/game/static/';




 const detail=load(base+'screens/disciple-detail.js'),overview=load(base+'screens/disciples.js'),patch=load(base+'components/patch.js'),lifecycle=load(base+'lifecycle.js');
 const data=fixture,commands=[];const ctx={data,ui:{},busy:false,route:{id:fixture.selectedBuilding},economyAction:(name,payload)=>commands.push({name,payload}),sheet(){}};
 const byId=(host,id)=>all(host).find(n=>n.dataset.id===id),text=host=>[host.textContent,...host.children.map(text)].join(' ');
 for(const width of [320,390,430])for(const theme of ['LIGHT','DARK']){
  win.innerWidth=width;ctx.data=clone(data);ctx.busy=false;
  const building=ctx.data.view.recipe_staffing.buildings.find(b=>b.building_id===data.selectedBuilding),target=building.rows.find(r=>r.recipe_id==='pill');
  ctx.route.id='pool';let host=detail.render(ctx);
  check(all(host).some(n=>n.tagName==='A'&&n.href==='#disciple_detail/'+encodeURIComponent(building.building_id)),'pool lists buildings');
  check(!byId(host,'recipe-work-list'),'pool does not flatten every recipe onto first level');
  ctx.route.id=building.building_id;host=detail.render(ctx);const list=byId(host,'recipe-work-list');
  check(list.children.length===building.rows.length,'second level has exact authoritative recipe rows');
  check(text(host).includes('安排 2 人'),'correct recipe count');
  const minus=byId(host,`work-step:${building.building_id}:pill:-1`),plus=byId(host,`work-step:${building.building_id}:pill:1`);
  check(!minus.disabled&&!plus.disabled,'eligible controls enabled');
  check(plus.getAttribute('aria-label').includes('增加'),'plus accessible label');
  plus.emit('click');check(commands.at(-1).name==='work_recipe_adjust'&&commands.at(-1).payload.delta===1,'plus real intent');
  minus.emit('click');check(commands.at(-1).payload.delta===-1&&commands.at(-1).payload.recipe_id==='pill'&&commands.at(-1).payload.building_id===building.building_id,'minus targets exact recipe and building');
  const zero=building.rows.find(r=>r.count===0&&r.recipe_id);check(byId(host,`work-step:${building.building_id}:${zero.recipe_id}:-1`).disabled,'zero cannot decrease');
  target.can_add=false;host=detail.render(ctx);check(byId(host,`work-step:${building.building_id}:pill:1`).disabled,'capacity or idle shortage disables plus');target.can_add=true;
  target.pending_release=1;target.working=3;building.pending_release=1;host=detail.render(ctx);check(text(host).includes('本轮完成后释放 1 人'),'pending people explained');
  ctx.busy=true;host=detail.render(ctx);const before=commands.length;byId(host,`work-step:${building.building_id}:pill:1`).emit('click');
  check(all(byId(host,'recipe-work-list')).filter(n=>n.tagName==='BUTTON').every(n=>n.disabled),'busy disables all steppers');check(commands.length===before,'busy callback does not send');ctx.busy=false;
  ctx.data.view.recipe_staffing.blocked=true;host=detail.render(ctx);check(all(byId(host,'recipe-work-list')).filter(n=>n.tagName==='BUTTON').every(n=>n.disabled),'pending or paused blocks controls');
  ctx.data.view.recipe_staffing.blocked=false;
  const first=overview.render(ctx),image=all(first).find(n=>n.tagName==='IMG');
  check(text(first).includes('查看配方'),'overview building link explains next layer');
  const fresh=overview.render(ctx);patch.patchPanel(first,fresh);check(!image||all(first).includes(image),'unchanged building image retained');
  const old=detail.render(ctx),oldRow=byId(old,`recipe-work:${building.building_id}:pill`);target.count=3;const next=detail.render(ctx);patch.patchPanel(old,next);
  check(byId(old,`recipe-work:${building.building_id}:pill`)===oldRow,'recipe row identity retained');check(text(oldRow).includes('安排 3 人'),'count updates on retained row');
 }
 const workerControls=load(base+'screens/economy.js').workerControls(ctx,data.selectedBuilding);
 check(all(workerControls).some(n=>n.tagName==='A'&&n.href==='#disciple_detail/'+encodeURIComponent(data.selectedBuilding)),'building controls route to same recipe workforce');
 check(!all(workerControls).some(n=>n.tagName==='BUTTON'),'normal production does not expose conflicting generic workforce UI');
 const live={world:{paused:false},time:{pending:false},economy:{needs_poll:true}};
 for(const name of ['disciples','disciple_detail']){
  check(lifecycle.needsSimulationPoll({name},live),'staffing page uses existing simulation polling');
  check(!lifecycle.needsSimulationPoll({name},{...live,world:{paused:true}}),'pause stops polling');
  check(!lifecycle.needsSimulationPoll({name},{...live,economy:{needs_poll:false}}),'idle page does not poll');
 }
 check(styles.game.includes('.work-stepper-button{min-width:44px;min-height:44px;'),'touch dimensions');
 check(styles.game.includes('grid-template-columns:minmax(0,1fr) auto'),'long names wrap alongside controls');
 check(!sources[base+'screens/disciple-detail.js'].includes('setInterval'),'no new per-page timer');
 return {checks,phone_visual_verified:false};
}

async function testRecipeStaffingClient(source){
 const GameClient=new Function('setTimeout','clearTimeout',source.replace(/export\s+/g,'')+';return GameClient;')(()=>1,()=>{});
 let checks=0;const check=(value,label)=>{if(!value)throw Error(label);checks++;};
 for(const interrupt of [false,true]){
  const state={protocol_version:1,csrf:'refinement-fixture',view:{save_id:'refine-save',generation:1,revision:7,world:{paused:false},time:{pending:false}}};
  const requests=[],storage=new Map();let counter=0,failed=false;
  const client=new GameClient({uuid:()=>`refine-request-${++counter}`,storage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},fetcher:async(path,options)=>{
   const body=options.body?JSON.parse(options.body):null;requests.push({path,body});
   if(path.endsWith('/command')){
    if(interrupt&&!failed){failed=true;throw Error('fixture transport interruption');}
    state.view.revision++;return {ok:true,status:200,json:async()=>({receipt:{committed_revision:state.view.revision}})};
   }
   return {ok:true,status:200,json:async()=>JSON.parse(JSON.stringify(state))};
  }});
  const payload={building_id:'staff-building',recipe_id:'pill',delta:1};
  if(interrupt){let error;try{await client.economy('work_recipe_adjust',payload);}catch(e){error=e;}
   check(error?.transport,'interruption retained as transport error');check(storage.size===1,'pending refinement retained');}
  await client.economy('work_recipe_adjust',payload);
  const sent=requests.filter(r=>r.path.endsWith('/command'));
  check(sent.length===(interrupt?2:1),'one committed intent');
  check(sent.every(r=>r.body.command.name==='work_recipe_adjust'&&JSON.stringify(r.body.command.payload)===JSON.stringify(payload)),'exact slot payload reaches HTTP');
  check(new Set(sent.map(r=>r.body.request_id)).size===1,'transport retry reuses request identity');
  check(!storage.size,'committed intent cleared');check(client.current.view.revision===8,'authoritative view refreshed');
  state.view.time.pending=true;const before=requests.length;let pending;
  try{await client.economy('work_recipe_adjust',payload);}catch(e){pending=e;}
  check(pending?.message.includes('续算'),'pending blocks new refinement');
  check(!requests.slice(before).some(r=>r.path.endsWith('/command')),'pending does not send command');
 }
 return {checks};
}

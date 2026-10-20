// Run shipped native ES modules in a V8 isolate. DOM harness tests behavior,
// not Safari layout, painting, or device performance.
async function testRefinementUI(sources,fixture,styles) {
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



 const screen=load(base+'screens/refinement.js'),icons=load(base+'components/item-icon.js'),equipment=load(base+'screens/equipment.js'),patch=load(base+'components/patch.js');
 const data=load(base+'adapters.js').gameView(fixture),commands=[];let shown=null;
 const ctx={data,ui:{},busy:false,route:{name:'building',id:'forge'},sheet:(title,content)=>shown={title,content},redraw(){},economyAction:(name,payload)=>commands.push({name,payload})};
 const find=(host,id)=>all(host).find(n=>n.dataset.id===id),text=n=>[n.textContent,...n.children.map(text)].join(' ');
 const click=(host,label)=>{const b=all(host).find(n=>n.tagName==='BUTTON'&&n.textContent===label);check(!!b,'button '+label);b.emit('click');};
 const target=data.view.equipment.instances[0];
 for(const width of [320,390,430])for(const theme of ['LIGHT','DARK']){
  win.innerWidth=width;ctx.ui={};ctx.busy=false;let host=screen.renderRefinement(ctx);
  check(find(host,'refinement-slots').children.length===4,'one equipment plus three materials');
  check(find(host,'refinement-equipment').classList.contains('refinement-slot--equipment'),'equipment slot larger');
  check(find(host,'refinement-submit').disabled,'empty selection blocked');
  find(host,'refinement-equipment').emit('click');check(shown.title==='选择精炼装备','equipment picker');
  all(shown.content).find(n=>n.dataset.equipmentId===target.instance_id).emit('click');
  check(ctx.ui.refinement.instanceId===target.instance_id,'exact equipment selected');
  host=screen.renderRefinement(ctx);find(host,'refinement-material-0').emit('click');
  const ore=all(shown.content).find(n=>n.dataset.resourceId==='ore');check(!ore.disabled,'owned ore selectable');
  ore.emit('click');host=screen.renderRefinement(ctx);
  check(ctx.ui.refinement.materials[0]==='ore','material slot selected');check(!find(host,'refinement-submit').disabled,'one material is sufficient');
  check(text(host).includes('精炼前 → 精炼后'),'stat preview exists');
  check(text(host).includes('攻击 +0.5'),'server contribution uses fractional value');
  find(host,'refinement-submit').emit('click');check(shown.title==='确认精炼','confirmation before spending');click(shown.content,'确认');
  check(commands.at(-1).name==='equipment_refine','real command');check(JSON.stringify(commands.at(-1).payload.materials)==='["ore",null,null]','exact three-slot payload');
  ctx.ui.refinement.materials=['ore','ore','ore'];const material=data.view.refinement.materials.find(r=>r.resource_id==='ore'),before=material.available;
  material.available=14;host=screen.renderRefinement(ctx);check(find(host,'refinement-submit').disabled,'duplicate quantity aggregate shortage');material.available=before;
  host=screen.renderRefinement(ctx);check(text(host).includes('凡铁矿 ×15'),'duplicates displayed as summed cost');
  ctx.busy=true;host=screen.renderRefinement(ctx);check(find(host,'refinement-submit').disabled&&find(host,'refinement-equipment').disabled,'busy disables edits and submit');ctx.busy=false;
  target.refinement={materials:['ore','ore','ore'],stats:{attack_milli:1100,armor_milli:440},element:'metal'};
  host=screen.renderRefinement(ctx);check(find(host,'refinement-submit').disabled,'same combination blocked');
  check(all(host).some(n=>n.classList.contains('refined-metal')),'selected equipment halo');
  delete target.refinement;
  ctx.ui.refinement.materials=[null,null,null];host=screen.renderRefinement(ctx);check(find(host,'refinement-submit').disabled,'cleared materials blocked');
 }
 // Retained icon keeps the same loaded image across refinement color changes.
 const old=icons.itemIcon({fallback:'equipment',asset_id:'sword',asset:{url:'/sword.png'}}),image=old.children.find(n=>n.tagName==='IMG');
 for(const element of ['fire','ice','wood','metal']){
  patch.patchPanel(old,icons.itemIcon({fallback:'equipment',asset_id:'sword',asset:{url:'/sword.png'},refinement_element:element}));
  check(old.children.includes(image),'halo does not recreate artwork');check(old.classList.contains('refined-'+element),'halo updates on patch');
 }
 check(sources[base+'building-adapters.js'].includes("['refinement','精炼']")&&sources[base+'building-adapters.js'].includes("host.append(renderRefinement(ctx))"),'forge tab invokes real refinement renderer');
 const refined={...target,refinement:{materials:['ore',null,null],stats:{attack_milli:500},element:'metal'}};
 ctx.data.view.equipment.instances=[refined];ctx.data.view.equipment.slots=[{id:'left',name:'武器',instance_id:refined.instance_id}];
 for(const page of [equipment.equipmentGrid(ctx),equipment.equipmentSlots(ctx),equipment.equipmentDetail(ctx,refined)])check(all(page).some(n=>n.classList.contains('refined-metal')),'halo in inventory, equipment and details');
 check(styles.game.includes('repeat(3,minmax(44px,1fr))'),'small slots have touch width');
 check(!sources[base+'screens/refinement.js'].includes('setInterval')&&!sources[base+'screens/refinement.js'].includes('requestAnimationFrame'),'no timers or animation loop');
 check(styles.game.includes('--refinement-glow:var(--q-rare)'),'halo shares themed semantic palette');
 check(sources[base+'api-client.js'].includes("'equipment_refine'"),'client command allowlist');
 return {checks,device_visual_verified:false};
}

// Exercise the actual pending-intent protocol as well as the screen callback.
async function testRefinementClient(source){
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
  const payload={instance_id:'refine-item',materials:['ore',null,'ore']};
  if(interrupt){let error;try{await client.economy('equipment_refine',payload);}catch(e){error=e;}
   check(error?.transport,'interruption retained as transport error');check(storage.size===1,'pending refinement retained');}
  await client.economy('equipment_refine',payload);
  const sent=requests.filter(r=>r.path.endsWith('/command'));
  check(sent.length===(interrupt?2:1),'one committed intent');
  check(sent.every(r=>r.body.command.name==='equipment_refine'&&JSON.stringify(r.body.command.payload)===JSON.stringify(payload)),'exact slot payload reaches HTTP');
  check(new Set(sent.map(r=>r.body.request_id)).size===1,'transport retry reuses request identity');
  check(!storage.size,'committed intent cleared');check(client.current.view.revision===8,'authoritative view refreshed');
  state.view.time.pending=true;const before=requests.length;let pending;
  try{await client.economy('equipment_refine',payload);}catch(e){pending=e;}
  check(pending?.message.includes('续算'),'pending blocks new refinement');
  check(!requests.slice(before).some(r=>r.path.endsWith('/command')),'pending does not send command');
 }
 return {checks};
}

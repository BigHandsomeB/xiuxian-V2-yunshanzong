// Run shipped native ES modules in a V8 isolate. DOM harness tests behavior,
// not Safari layout, painting, or device performance.
async function testFormalTechniqueUI(sources,fixture,styles) {
 const assert=(v,m)=>{if(!v)throw Error(m);};const clone=v=>JSON.parse(JSON.stringify(v));let checks=0;
 const listeners=new Map(),timers=new Map(),fetches=[],storageValues=new Map();let serial=0;
 const store={getItem:k=>storageValues.get(k)||null,setItem:(k,v)=>storageValues.set(k,v),removeItem:k=>storageValues.delete(k)};
 const eventTarget=()=>({events:{},addEventListener(k,f){(this.events[k]??=[]).push(f);},removeEventListener(k,f){this.events[k]=(this.events[k]||[]).filter(x=>x!==f);},emit(k,e={}){for(const f of this.events[k]||[])f(e);}});
 let doc;
 function node(tag='div'){const n={...eventTarget(),tagName:tag.toUpperCase(),children:[],dataset:{},attrs:{},style:{},hidden:false,disabled:false,open:false,textContent:'',ownerDocument:doc,
 prepend(...children){for(const x of children)x.parentNode=this;this.children.unshift(...children);},append(...children){for(const x of children){x.parentNode=this;this.children.push(x);}},replaceChildren(...children){this.children=[];this.append(...children);},remove(){if(this.parentNode)this.parentNode.children=this.parentNode.children.filter(x=>x!==this);},setAttribute(k,v){this.attrs[k]=String(v);},getAttribute(k){return this.attrs[k]??null;},removeAttribute(k){delete this.attrs[k];},focus(){this.focused=true;},showModal(){this.open=true;},close(){this.open=false;},getBoundingClientRect(){return {width:390,height:500,top:0,left:0,right:390,bottom:500};},querySelectorAll(selector){return all(this).filter(x=>selector==='[data-tab]'?!!x.dataset.tab:false);},set src(v){this.attrs.src=v;},get src(){return this.attrs.src;}};
 n.querySelector=selector=>all(n).find(x=>selector==='input[type=number]'?x.tagName==='INPUT'&&x.type==='number':selector==='button.primary'?x.tagName==='BUTTON'&&x.classList.contains('primary'):false)||null;n.dispatchEvent=event=>{n.emit(event.type,event);return true;};n.classList={add(k){n.className=(n.className||'')+' '+k;},contains(k){return (n.className||'').split(' ').includes(k);}};return n;}
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


 const slots=load(base+'components/technique-slots.js'),library=load(base+'screens/techniques.js'),patch=load(base+'components/patch.js'),client=load(base+'api-client.js');
 for(const name of ['technique_buy','technique_claim','technique_exchange']){let accepted=false;await client.GameClient.prototype.economy.call({lock(){accepted=true;return Promise.resolve();}},name,{});check(accepted,'HTTP lane '+name);}
 for(const width of [320,390,430])for(const theme of ['LIGHT','DARK']){
  win.innerWidth=width;let sheet=null,commands=[];const ctx={data:clone(fixture),ui:{},busy:false,redraw(){},sheet(title,body){sheet=body;},economyAction(name,payload){commands.push({name,payload});}};
  const page=slots.renderTechniqueSlots(ctx),grid=all(page).find(n=>n.className==='technique-grid');
  check(grid.children.length===8,'8 slots');check(all(grid).some(n=>n.textContent==='内功一'),'internal slot names');check(all(grid).filter(n=>n.tagName==='IMG').length===2,'real starter art');
  const image=all(grid).find(n=>n.tagName==='IMG');patch.patchPanel(page,slots.renderTechniqueSlots(ctx));check(all(page).includes(image),'icon survives refresh');
  let collection=library.renderTechniqueLibrary(ctx);check(all(collection).filter(n=>n.dataset.id?.startsWith('manual_')).length===2,'owned starters');
  all(collection).find(n=>n.textContent==='功法图鉴').emit('click');collection=library.renderTechniqueLibrary(ctx);check(all(collection).filter(n=>n.dataset.id?.startsWith('manual_')).length===fixture.view.techniques.catalog.length,'catalog cards');
  const unowned=fixture.view.techniques.catalog.find(r=>r.grade==='green'&&!r.owned);all(collection).find(n=>n.dataset.id===unowned.id).emit('click');
  const buy=all(sheet).find(n=>n.textContent==='购买功法');check(!buy.disabled,'affordable buy');buy.emit('click');all(sheet).find(n=>n.textContent==='确认').emit('click');check(commands.at(-1).name==='technique_buy','purchase intent');
  collection=library.renderTechniqueLibrary(ctx);const red=fixture.view.techniques.catalog.find(r=>r.grade==='red');all(collection).find(n=>n.dataset.id===red.id).emit('click');check(all(sheet).some(n=>n.textContent.includes('仙品灵石')),'stone cost');check(all(sheet).some(n=>n.textContent.includes('功法残页')),'page cost');
  const shop=library.renderTechniqueLibrary(ctx,{shop:true});check(all(shop).filter(n=>n.dataset.id?.startsWith('manual_')).every(n=>fixture.view.techniques.catalog.find(r=>r.id===n.dataset.id).grade==='green'||fixture.view.techniques.catalog.find(r=>r.id===n.dataset.id).grade==='white'),'low grade shop');
 }
 return {checks,device_visual_verified:false};
}

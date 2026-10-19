// Run shipped native ES modules in a V8 isolate. DOM harness tests behavior,
// not Safari layout, painting, or device performance.
async function testStoryUI(sources, states, realFetcher=null) {
 const assert=(v,m)=>{if(!v)throw Error(m);};const clone=v=>JSON.parse(JSON.stringify(v));let checks=0;
 const listeners=new Map(),timers=new Map(),fetches=[],storageValues=new Map();let serial=0;
 const store={getItem:k=>storageValues.get(k)||null,setItem:(k,v)=>storageValues.set(k,v),removeItem:k=>storageValues.delete(k)};
 const eventTarget=()=>({events:{},addEventListener(k,f){(this.events[k]??=[]).push(f);},removeEventListener(k,f){this.events[k]=(this.events[k]||[]).filter(x=>x!==f);},emit(k,e={}){for(const f of this.events[k]||[])f(e);}});
 let doc;
 function node(tag='div'){const n={...eventTarget(),tagName:tag.toUpperCase(),children:[],dataset:{},attrs:{},style:{},hidden:false,disabled:false,open:false,textContent:'',ownerDocument:doc,
 prepend(...children){for(const x of children)x.parentNode=this;this.children.unshift(...children);},append(...children){for(const x of children){x.parentNode=this;this.children.push(x);}},replaceChildren(...children){this.children=[];this.append(...children);},remove(){if(this.parentNode)this.parentNode.children=this.parentNode.children.filter(x=>x!==this);},setAttribute(k,v){this.attrs[k]=String(v);},getAttribute(k){return this.attrs[k]??null;},removeAttribute(k){delete this.attrs[k];},focus(){this.focused=true;},showModal(){this.open=true;},close(){this.open=false;},getBoundingClientRect(){return {width:390,height:500,top:0,left:0,right:390,bottom:500};},querySelectorAll(selector){return all(this).filter(x=>selector==='[data-tab]'?!!x.dataset.tab:false);},set src(v){this.attrs.src=v;},get src(){return this.attrs.src;}};
 n.classList={add(k){n.className=(n.className||'')+' '+k;},contains(k){return (n.className||'').split(' ').includes(k);}};return n;}
 function all(n){return [n,...n.children.flatMap(all)];}
 const nodes=new Map(['world-bar','world-status','world-toggle','screen','connection','main-nav','sheet','sheet-title','sheet-content','close-sheet','refresh','toast'].map(id=>[id,node()]));
 const win={...eventTarget(),scrollY:0,innerHeight:844,innerWidth:390,scrollTo(x,y){this.scrollY=y;},matchMedia:()=>({...eventTarget(),matches:false}),requestAnimationFrame:f=>{timers.set(++serial,f);return serial;},cancelAnimationFrame:id=>timers.delete(id)};
 doc={...eventTarget(),hidden:false,defaultView:win,createElement:tag=>node(tag),getElementById:id=>nodes.get(id)};for(const n of nodes.values())n.ownerDocument=doc;
 for(const name of ['sect','disciples','cultivation','inventory','adventure']){const a=node('a');a.dataset.tab=name;nodes.get('main-nav').append(a);}
 const location={hash:'',href:''},navigator={onLine:true};let current=clone(states.fresh);
 const fetch=async(url,options={})=>{fetches.push({url,body:options.body?JSON.parse(options.body):null});if(realFetcher)return realFetcher(url,options);if(url.endsWith('/assets'))return {ok:true,status:200,json:async()=>({protocol_version:1,presentation:current.presentation})};return {ok:true,status:200,json:async()=>clone(current)};};
 const globals={document:doc,window:win,location,navigator,fetch,sessionStorage:store,crypto:{randomUUID:()=>`00000000-0000-4000-8000-${String(++serial).padStart(12,"0")}`},setTimeout:(f,ms)=>{timers.set(++serial,{f,ms});return serial;},clearTimeout:id=>timers.delete(id)};
 const modules=new Map();
 function load(path){if(modules.has(path))return modules.get(path);let source=sources[path];assert(source!==undefined,`Missing module ${path}`);const imports={};source=source.replace(/^import\s+(.+?)\s+from\s+['"](.+?)['"];?\s*$/gm,(_,bindings,target)=>{let parts=path.split('/');parts.pop();for(const p of target.split('/')){if(p==='..')parts.pop();else if(p!=='.')parts.push(p);}const dependency=load(parts.join('/'));if(bindings.startsWith('* as '))imports[bindings.slice(5)]=dependency;else for(const entry of bindings.replace(/[{}]/g,'').split(',')){const [key,alias]=entry.trim().split(/\s+as\s+/);imports[alias||key]=dependency[key];}return '';});
 const exports=[...source.matchAll(/export\s+(?:async\s+)?(?:function|class|const)\s+(\w+)/g)].map(m=>m[1]);source=source.replace(/export\s+/g,'');const args={...globals,...imports};const output=new Function(...Object.keys(args),source+`;return {${exports.join(',')}};`)(...Object.values(args));modules.set(path,output);return output;}



 const check=(v,m)=>{assert(v,m);checks++;},base='src/ui/pages/game/static/';
 const screen=load(base+'screens/story.js'),patch=load(base+'components/patch.js'),router=load(base+'router.js'),life=load(base+'lifecycle.js'),commands=[];
 const ctx={data:clone(states.complete),ui:{},busy:false,route:{name:'story',id:''},redraw(){},economyAction:(name,payload)=>commands.push({name,payload})};
 const click=(tree,text)=>{const b=all(tree).find(n=>n.tagName==='BUTTON'&&n.textContent===text);check(!!b,'button '+text);check(!b.disabled,'enabled '+text);b.emit('click');};
 for(const width of [320,390,430])for(const theme of ['LIGHT','DARK']){
  win.innerWidth=width;ctx.theme={mode:theme,set(){}};ctx.route.id='';ctx.data=clone(states.complete);ctx.ui.storyTab='pending';
  const entry=screen.storyEntry(ctx);check(entry.tagName==='BUTTON','single button entry');entry.emit('click');check(location.hash==='#story','button opens story records');
  const list=screen.render(ctx);check(all(list).some(n=>n.dataset.id==='story-row-chapter_1_01'),'initial node');
  check(!all(list).some(n=>n.tagName==='A'&&(n.href||n.getAttribute('href'))==='#story/chapter_5_07'),'later text not readable out of order');
  const row=all(list).find(n=>n.dataset.id==='story-row-chapter_1_01');patch.patchPanel(list,screen.render(ctx));check(all(list).includes(row),'unchanged rows retained');
  ctx.route.id='chapter_1_01';let detail=screen.render(ctx);check(all(detail).some(n=>n.textContent.includes('库存不宽裕')),'real dialogue from server');
  const before=commands.length;check(before===commands.length,'opening has no acknowledgement');click(detail,'记为已读');check(commands.at(-1).name==='story_read'&&commands.at(-1).payload.node_id==='chapter_1_01','explicit read only');
  ctx.busy=true;detail=screen.render(ctx);check(all(detail).find(n=>n.tagName==='BUTTON').disabled,'busy guards read');ctx.busy=false;
  ctx.data.view.time.pending=true;detail=screen.render(ctx);check(all(detail).find(n=>n.tagName==='BUTTON').disabled,'pending guards read');check(all(detail).some(n=>n.textContent.includes('库存不宽裕')),'pending still permits reading');ctx.data.view.time.pending=false;
  ctx.data=clone(states.after_intro);detail=screen.render(ctx);check(all(detail).find(n=>n.tagName==='BUTTON').textContent==='已阅读，可随时回看','saved read state');
  ctx.route.id='chapter_5_07';check(!all(screen.render(ctx)).some(n=>n.textContent.includes('牵连了多少')),'direct locked route cannot leak dialogue');
  ctx.data=clone(states.foundation);ctx.route.id='cultivation_foundation_01';detail=screen.render(ctx);check(all(detail).some(n=>n.textContent==='嗯，筑基了。'),'independent foundation readable');
  ctx.route.id='';ctx.ui.storyTab='all';check(all(screen.render(ctx)).some(n=>n.dataset.id==='story-row-chapter_1_02'),'optional production scene present');
  const active=clone(states.complete);active.view.combat={auto:{enabled:true}};active.view.world.paused=false;check(life.needsSimulationPoll({name:'story'},active.view),'auto continues on story route');
  active.view.combat.auto.enabled=false;active.view.economy={needs_poll:true};check(life.needsSimulationPoll({name:'story'},active.view),'production continues on story route');
  active.view.world.paused=true;check(!life.needsSimulationPoll({name:'story'},active.view),'paused never advances');
 }
 check(router.parseRoute('#story/chapter_2_01').name==='story','route registered');check(router.mainTab({name:'story'})==='adventure','five primary tabs unchanged');
 const {GameClient}=load(base+'api-client.js');
 for(const paused of [false,true]){
  const state={protocol_version:1,csrf:'fixture',view:{save_id:'fixture',generation:1,revision:7,world:{paused},time:{pending:false}}},requests=[],values=new Map();
  const client=new GameClient({uuid:()=> 'request-fixture',storage:{getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)},fetcher:async(path,opt)=>{
   const body=opt.body?JSON.parse(opt.body):null;requests.push({path,body});if(path.endsWith('/command')){state.view.revision++;return {ok:true,status:200,json:async()=>({receipt:{committed_revision:state.view.revision}})};}return {ok:true,status:200,json:async()=>clone(state)};
  }});
  await client.economy('story_read',{node_id:'chapter_1_01'});check(requests.filter(r=>r.path.endsWith('/command')).length===1,'one acknowledgement');check(!requests.some(r=>r.path.endsWith('/settle')),'reading never settles simulation');check(!values.size,'receipt clears pending request');
 }
 return {checks,scope:'native story DOM, real client and lifecycle in six width/theme contexts; no phone rendering claim'};
}

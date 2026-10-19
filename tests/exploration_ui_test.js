// Run shipped native ES modules in a V8 isolate. DOM harness tests behavior,
// not Safari layout, painting, or device performance.
async function testExplorationUI(sources, states, realFetcher=null) {
 const fixture=states.idle;
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
 const location={hash:'',href:''},navigator={onLine:true};let current=clone(fixture);
 const fetch=async(url,options={})=>{fetches.push({url,body:options.body?JSON.parse(options.body):null});if(realFetcher)return realFetcher(url,options);if(url.endsWith('/assets'))return {ok:true,status:200,json:async()=>({protocol_version:1,presentation:current.presentation})};return {ok:true,status:200,json:async()=>clone(current)};};
 const globals={document:doc,window:win,location,navigator,fetch,sessionStorage:store,crypto:{randomUUID:()=>`00000000-0000-4000-8000-${String(++serial).padStart(12,"0")}`},setTimeout:(f,ms)=>{timers.set(++serial,{f,ms});return serial;},clearTimeout:id=>timers.delete(id)};
 const modules=new Map();
 function load(path){if(modules.has(path))return modules.get(path);let source=sources[path];assert(source!==undefined,`Missing module ${path}`);const imports={};source=source.replace(/^import\s+(.+?)\s+from\s+['"](.+?)['"];?\s*$/gm,(_,bindings,target)=>{let parts=path.split('/');parts.pop();for(const p of target.split('/')){if(p==='..')parts.pop();else if(p!=='.')parts.push(p);}const dependency=load(parts.join('/'));if(bindings.startsWith('* as '))imports[bindings.slice(5)]=dependency;else for(const entry of bindings.replace(/[{}]/g,'').split(',')){const [key,alias]=entry.trim().split(/\s+as\s+/);imports[alias||key]=dependency[key];}return '';});
 const exports=[...source.matchAll(/export\s+(?:async\s+)?(?:function|class|const)\s+(\w+)/g)].map(m=>m[1]);source=source.replace(/export\s+/g,'');const args={...globals,...imports};const output=new Function(...Object.keys(args),source+`;return {${exports.join(',')}};`)(...Object.values(args));modules.set(path,output);return output;}

 const check=(v,m)=>{assert(v,m);checks++;},base='src/ui/pages/game/static/';



 const data=load(base+'adapters.js').gameView(fixture),commands=[];let shown=null;
 const ctx={data,ui:{},busy:false,route:{name:'building',id:'hall'},sheet:(title,content)=>shown={title,content},redraw(){},sync(){},economyAction:(name,payload)=>commands.push({name,payload})};

 const screen=load(base+'screens/exploration.js'),adventure=load(base+'screens/adventure.js'),patch=load(base+'components/patch.js');
 const click=(tree,text)=>{const n=all(tree).find(n=>n.tagName==='BUTTON'&&n.textContent===text);check(!!n,'button '+text);check(!n.disabled,'enabled '+text);n.emit('click');};
 const use=(key)=>{ctx.data=load(base+'adapters.js').gameView(states[key]);};
 for(const width of [320,390,430])for(const theme of ['LIGHT','DARK']){
  win.innerWidth=width;ctx.theme={mode:theme,set(){}};use('idle');
  let tree=screen.renderExploration(ctx);check(all(tree).filter(n=>n.dataset.id?.startsWith('exploration-region:')).length===4,'four real regions');
  check(all(tree).filter(n=>n.tagName==='BUTTON'&&!n.disabled).length===1,'only unlocked region starts');
  let count=commands.length;click(tree,'开始探索');check(count===commands.length,'start confirms');click(shown.content,'确认');check(commands.at(-1).name==='exploration_start'&&commands.at(-1).payload.region_id==='thorn_outskirts','start carries actual region');
  const icons=all(tree).filter(n=>n.classList?.contains('item-icon'));patch.patchPanel(tree,screen.renderExploration(ctx));check(icons.every(n=>all(tree).includes(n)),'refresh retains unchanged resource icons');
  use('travelling');tree=screen.renderExploration(ctx);check(all(tree).some(n=>n.tagName==='PROGRESS'&&n.value<n.max),'server progress in flight');
  check(all(tree).filter(n=>n.tagName==='BUTTON'&&n.textContent==='开始探索').every(n=>n.disabled),'one journey at a time');
  check(!all(screen.renderEvents(ctx)).some(n=>n.dataset.id?.startsWith('exploration-choice:')),'no choices before due');
  use('ready');tree=screen.renderEvents(ctx);const event=ctx.data.view.exploration.active.event;check(all(tree).filter(n=>n.dataset.id?.startsWith('exploration-choice:')).length===3,'three real choices');
  count=commands.length;click(tree,'选择谨慎离开');check(commands.length===count,'choice confirms');click(shown.content,'确认');
  check(commands.at(-1).name==='exploration_choose'&&commands.at(-1).payload.journey_id===ctx.data.view.exploration.active.id&&commands.at(-1).payload.choice_id==='leave','frozen journey and explicit choice');
  ctx.busy=true;check(all(screen.renderEvents(ctx)).filter(n=>n.tagName==='BUTTON').every(n=>n.disabled),'busy choices disabled');ctx.busy=false;
  ctx.data.view.exploration.blocked=true;check(all(screen.renderEvents(ctx)).filter(n=>n.tagName==='BUTTON').every(n=>n.disabled),'pending/paused choices disabled');ctx.data.view.exploration.blocked=false;
  const blockedChoice=ctx.data.view.exploration.active.event.choices[0];blockedChoice.can_choose=false;blockedChoice.blocking_reason='仓库空间不足，探索与事件继续保留';
  tree=screen.renderEvents(ctx);check(all(tree).find(n=>n.tagName==='BUTTON'&&n.textContent==='选择'+blockedChoice.name).disabled,'server warehouse block respected');check(all(tree).some(n=>n.textContent===blockedChoice.blocking_reason),'warehouse block explained');
  use('resolved');tree=screen.renderEvents(ctx);check(all(tree).filter(n=>n.dataset.id?.startsWith('exploration-history:')).length===1,'actual saved result visible');
  const details=all(tree).find(n=>n.tagName==='DETAILS');details.open=true;patch.patchPanel(tree,screen.renderEvents(ctx));check(details.open,'expanded history retained');
  use('paused');check(all(screen.renderExploration(ctx)).filter(n=>n.tagName==='BUTTON').every(n=>n.disabled),'pause prevents start');
  use('idle');ctx.ui.adventureTab='地图 / 区域';tree=adventure.render(ctx);
  const nav=tree.children.find(n=>n.attrs?.role==='tablist');check(!!nav,'navigation above content');
  check(nav.children.map(n=>n.textContent).join('|')==='地图 / 区域|探索|特殊事件|战斗记录','four useful navigation tabs');
  check(tree.children.indexOf(nav)<tree.children.findIndex(n=>n.className==='dungeon-list'),'navigation before map cards');
  check(all(tree).filter(n=>n.tagName==='BUTTON'&&n.textContent==='探索').length===1,'one exploration entry');
  check(all(tree).filter(n=>n.tagName==='BUTTON'&&n.textContent==='特殊事件').length===1,'one event entry');
  check(!all(tree).some(n=>n.tagName==='BUTTON'&&['秘境塔','普通副本','Boss'].includes(n.textContent)),'redundant categories removed');
  for(const old of ['秘境塔','普通副本','Boss']){ctx.ui.adventureTab=old;check(all(adventure.render(ctx)).some(n=>n.className==='dungeon-list'),'removed saved selection falls back to map');}
  ctx.ui.adventureTab='地图 / 区域';click(tree,'探索');check(ctx.ui.adventureTab==='特殊探索','explore shortcut opens real tab');
  tree=adventure.render(ctx);check(all(tree).some(n=>n.dataset.id==='exploration-panel'),'adventure mounts exploration');click(tree,'特殊事件');check(ctx.ui.adventureTab==='事件','event shortcut opens real tab');
  check(all(adventure.render(ctx)).some(n=>n.dataset.id==='exploration-events'),'adventure mounts events');
 }
 return {checks,context:'shipping modules / server projections / native DOM in six width/theme contexts; not browser layout'};
}

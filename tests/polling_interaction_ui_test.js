// Run shipped native ES modules in a V8 isolate. DOM harness tests behavior,
// not Safari layout, painting, or device performance.
async function testPollingInteraction(sources, fixture, realFetcher=null, saveFixture=null) {
 const assert=(v,m)=>{if(!v)throw Error(m);};const clone=v=>JSON.parse(JSON.stringify(v));let checks=0;
 const listeners=new Map(),timers=new Map(),fetches=[],storageValues=new Map();let serial=0;
 const store={getItem:k=>storageValues.get(k)||null,setItem:(k,v)=>storageValues.set(k,v),removeItem:k=>storageValues.delete(k)};
 const eventTarget=()=>({events:{},addEventListener(k,f){(this.events[k]??=[]).push(f);},removeEventListener(k,f){this.events[k]=(this.events[k]||[]).filter(x=>x!==f);},emit(k,e={}){for(const f of this.events[k]||[])f(e);}});
 let doc;
 function node(tag='div'){const n={...eventTarget(),tagName:tag.toUpperCase(),children:[],dataset:{},attrs:{},style:{},hidden:false,disabled:false,open:false,textContent:'',ownerDocument:doc,
 get childNodes(){return this.children;},get firstChild(){return this.children[0];},get lastChild(){return this.children.at(-1);},insertBefore(child,before){if(child.parentNode)child.parentNode.children=child.parentNode.children.filter(n=>n!==child);child.parentNode=this;const index=this.children.indexOf(before);if(index<0)this.children.push(child);else this.children.splice(index,0,child);},prepend(...children){for(const x of children)x.parentNode=this;this.children.unshift(...children);},append(...children){for(const x of children){x.parentNode=this;this.children.push(x);}},replaceChildren(...children){this.children=[];this.append(...children);},remove(){if(this.parentNode)this.parentNode.children=this.parentNode.children.filter(x=>x!==this);},setAttribute(k,v){this.attrs[k]=String(v);},getAttribute(k){return this.attrs[k]??null;},removeAttribute(k){delete this.attrs[k];},focus(){this.focused=true;},showModal(){this.open=true;},close(){this.open=false;},getBoundingClientRect(){return {width:390,height:500,top:0,left:0,right:390,bottom:500};},querySelectorAll(selector){return all(this).filter(x=>selector==='[data-tab]'?!!x.dataset.tab:selector==='button'?x.tagName==='BUTTON':false);},set src(v){this.attrs.src=v;},get src(){return this.attrs.src;}};
 n.classList={add(k){n.className=(n.className||'')+' '+k;},contains(k){return (n.className||'').split(' ').includes(k);}};return n;}
 function all(n){return [n,...n.children.flatMap(all)];}
 const nodes=new Map(['world-bar','world-status','world-toggle','screen','connection','main-nav','sheet','sheet-title','sheet-content','close-sheet','refresh','toast'].map(id=>[id,node()]));
 const shell=node();shell.append(nodes.get('screen'));
 const win={localStorage:store,setInterval:(f,ms)=>{timers.set(++serial,{f,ms});return serial;},clearInterval:id=>timers.delete(id),...eventTarget(),scrollY:0,innerHeight:844,innerWidth:390,scrollTo(x,y){this.scrollY=y;},matchMedia:()=>({...eventTarget(),matches:false}),requestAnimationFrame:f=>{timers.set(++serial,f);return serial;},cancelAnimationFrame:id=>timers.delete(id)};
 doc={...eventTarget(),hidden:false,defaultView:win,createElement:tag=>node(tag),getElementById:id=>nodes.get(id)||all(shell).find(n=>n.id===id),querySelector:()=>null};for(const n of nodes.values())n.ownerDocument=doc;
 for(const name of ['sect','disciples','cultivation','inventory','adventure']){const a=node('a');a.dataset.tab=name;nodes.get('main-nav').append(a);}
 const location={hash:'',href:''},navigator={onLine:true,storage:{persist:async()=>false},locks:{request:async(name,options,callback)=>callback({name})}};let backup=null,catchupLeft=null,holdCatchup=false,releaseCatchup=null;let current={protocol_version:1,...clone(fixture)},blocked=false,release=null;
 const fetch=async(url,options={})=>{fetches.push({url,body:options.body?JSON.parse(options.body):null});if(blocked&&url.endsWith('/view'))await new Promise(resolve=>release=resolve);if(options.body&&url.endsWith('/command')){const name=JSON.parse(options.body).command.name;if(name==='world_pause'||name==='world_resume'){current.view.world.paused=name==='world_pause';current.view.revision++;}}if(catchupLeft!==null&&options.body&&url.endsWith('/settle')){if(holdCatchup)await new Promise(resolve=>releaseCatchup=resolve);catchupLeft=Math.max(0,catchupLeft-1);current.view.revision++;current.view.time.simulation_time_ms++;current.view.time.pending=!!catchupLeft;current.view.time.continuation=catchupLeft?{revision:current.view.revision,target_sim_ms:8}:null;}if(catchupLeft!==null&&options.body&&url.endsWith('/command')&&JSON.parse(options.body).command.name==='dungeon_auto'){current.view.combat.auto.enabled=JSON.parse(options.body).command.payload.enabled;current.view.revision++;}if(realFetcher)return realFetcher(url,options);if(url.endsWith('/save')&&saveFixture){if(options.method==='PUT'){backup=JSON.parse(options.body).save;return {ok:true,status:200,json:async()=>({save:clone(backup)})};}const state=clone(saveFixture);state.revision=current.view.revision;state.time.world_paused=!!current.view.world?.paused;return {ok:true,status:200,json:async()=>({save:backup&&clone(backup),serverState:state})};}if(url.endsWith('/assets'))return {ok:true,status:200,json:async()=>({protocol_version:1,presentation:current.presentation})};return {ok:true,status:200,json:async()=>clone(current)};};
 const globals={document:doc,window:win,location,navigator,fetch,sessionStorage:store,crypto:{randomUUID:()=>`00000000-0000-4000-8000-${String(++serial).padStart(12,"0")}`},setTimeout:(f,ms)=>{timers.set(++serial,{f,ms});return serial;},clearTimeout:id=>timers.delete(id)};
 const modules=new Map();
 function load(path){if(path.endsWith('/battle/renderer.js'))return {mountBattle:()=>Object.assign(()=>{},{health(){},suspend(){},resume(){},rest(){},update(){},clearFeedback(){}})};if(modules.has(path))return modules.get(path);let source=sources[path];assert(source!==undefined,`Missing module ${path}`);const imports={};source=source.replace(/^import\s+(.+?)\s+from\s+['"](.+?)['"];?\s*$/gm,(_,bindings,target)=>{let parts=path.split('/');parts.pop();for(const p of target.split('/')){if(p==='..')parts.pop();else if(p!=='.')parts.push(p);}const dependency=load(parts.join('/'));if(bindings.startsWith('* as '))imports[bindings.slice(5)]=dependency;else for(const entry of bindings.replace(/[{}]/g,'').split(',')){const [key,alias]=entry.trim().split(/\s+as\s+/);imports[alias||key]=dependency[key];}return '';});
 const exports=[...source.matchAll(/export\s+(?:async\s+)?(?:function|class|const)\s+(\w+)/g)].map(m=>m[1]);source=source.replace(/export\s+/g,'');const args={...globals,...imports};const output=new Function(...Object.keys(args),source+`;return {${exports.join(',')}};`)(...Object.values(args));modules.set(path,output);return output;}

 const check=(v,m)=>{assert(v,m);checks++;},base='src/ui/pages/game/static/';


 current.view.economy.needs_poll=true;
 const errors=[];const probe=(v,m)=>{checks++;if(!v)errors.push(m);};
 const drain=async()=>{for(let i=0;i<400;i++)await Promise.resolve();};
 load(base+'game.js');await drain();
 const root=nodes.get('screen').children[0],resource=all(root).find(n=>n.tagName==='BUTTON'&&n.classList.contains('resource-summary'));
 check(!!resource,'home resource ready');resource.emit('click');
 const content=nodes.get('sheet-content').children[0],sheetButton=node('button');content.append(sheetButton);
 win.scrollY=430;blocked=true;const poll=[...timers.values()].find(t=>[2000,4000].includes(t.ms));check(!!poll,'real background poll scheduled');poll.f();await drain();
 probe(!resource.disabled,'Background sync must not disable home resource buttons');
 probe(!sheetButton.disabled,'Background sync must not disable open sheet controls');
 probe(nodes.get('screen').getAttribute('aria-busy')!=='true','Background sync must not mark whole page busy');
 const commandsBefore=fetches.filter(r=>r.body?.command).length;nodes.get('world-toggle').emit('click');await drain();probe(fetches.filter(r=>r.body?.command).length===commandsBefore,'Click waits for active synchronization');blocked=false;release();await drain();probe(fetches.filter(r=>r.body?.command).length===commandsBefore+1,'Queued click sends exactly one command after synchronization');
 probe(nodes.get('screen').children[0]===root&&nodes.get('sheet-content').children[0]===content&&nodes.get('sheet').open&&win.scrollY===430,'Sync retains root, open sheet and scroll');
 const {el}=load(base+'components/dom.js'),{patchPanel}=load(base+'components/patch.js');
 for(const width of [320,390,430])for(const mode of ['LIGHT','DARK']){win.innerWidth=width;doc.documentElement??=node('html');doc.documentElement.setAttribute('data-theme',mode.toLowerCase());
 const panel=el('section'),input=el('input');input.value='5';panel.append(input);input.value='37';
 const fresh=el('section'),next=el('input');next.value='5';fresh.append(next);patchPanel(panel,fresh);
 probe(input.value==='37','Unfocused edited quantity must survive state update');
 const list=el('div'),a=el('button'),b=el('button');a.dataset.id='a';b.dataset.id='b';list.append(a,b);
 const other=el('div'),c=el('button'),d=el('button');c.dataset.id='b';d.dataset.id='a';other.append(c,d);patchPanel(list,other);
 probe(list.children[0]===b&&list.children[1]===a,'Stable data-id items retain identity during reordering');
 }
 if(saveFixture){location.hash='#settings';win.emit('hashchange');await drain();const savePanel=all(nodes.get('screen')).find(n=>n.dataset.savePanel==='main');probe(!!savePanel,'Actual settings screen mounts save controls');probe(all(savePanel).some(n=>n.textContent==='导出存档')&&all(savePanel).some(n=>n.textContent==='复制存档'),'Settings offers file and text export');probe(all(savePanel).some(n=>n.type==='file')&&all(savePanel).some(n=>n.textContent==='粘贴文本导入'),'Settings offers both import paths');}
 const battleContext={data:clone(fixture),busy:true,combatProgress:{phase:'catchup',percent:74,stopping:true}};
 const waitingBattle=load(base+'screens/battle.js').render(battleContext),waitingButton=all(waitingBattle).find(n=>n.id==='combat-auto-toggle');
 probe(all(waitingButton).some(n=>n.textContent==='补算进度 74%…'),'Waiting stop button shows actual catch-up progress instead of generic submitting');
 probe(all(waitingBattle).some(n=>n.textContent.includes('完成后停止挂机')),'Battle explains why stopping is waiting');
 // Render the real game/battle/client path; only the unrelated animation renderer is stubbed.
 current.view.world.paused=false;current.view.combat.auto.enabled=true;current.view.time.simulation_time_ms=0;current.view.time.pending=false;current.view.time.continuation=null;catchupLeft=null;
 location.hash='#battle';win.emit('hashchange');await drain();
 const actualStop=all(nodes.get('screen')).find(n=>n.id==='combat-auto-toggle'),battleRoot=nodes.get('screen').children[0];
 catchupLeft=8;holdCatchup=true;actualStop.emit('click');await drain();
 probe(all(actualStop).some(n=>n.textContent==='补算进度 0%…'),'Actual game callback updates mounted stop button while settlement is waiting');
 probe(actualStop.disabled&&nodes.get('screen').children[0]===battleRoot,'Catch-up retains battle root and prevents duplicate clicks');
 location.hash='#settings';win.emit('hashchange');await drain();location.hash='#battle';win.emit('hashchange');await drain();
 probe(nodes.get('screen').children[0]===battleRoot&&all(actualStop).some(n=>n.textContent==='补算进度 0%…'),'Returning to cached battle preserves active stop progress');
 holdCatchup=false;releaseCatchup();await drain();
 probe(!current.view.combat.auto.enabled&&!actualStop.disabled&&all(actualStop).some(n=>n.textContent==='开启挂机'),'Completion clears busy state and restores the mounted button');
 probe(fetches.filter(r=>r.body?.command?.name==='dungeon_auto').length===1,'Progress updates never duplicate the stop command');
 doc.hidden=true;doc.emit('visibilitychange');probe(![...timers.values()].some(t=>[2000,4000].includes(t.ms)),'Hidden page stops simulation polling');
 if(errors.length)throw Error(errors.join('; '));
 return {tests:checks,status:'PASS',scope:'actual native sync with stalled fetch, open sheet and edited fields'};
}

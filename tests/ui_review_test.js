// Run shipped native ES modules in a V8 isolate. DOM harness tests behavior,
// not Safari layout, painting, or device performance.
async function testUIReview(sources, fixture, assetManifest) {
 const assert=(v,m)=>{if(!v)throw Error(m);};const clone=v=>JSON.parse(JSON.stringify(v));let checks=0;
 const listeners=new Map(),timers=new Map(),fetches=[],storageValues=new Map();let serial=0,creations=0,readGate=null;
 const store={getItem:k=>storageValues.get(k)||null,setItem:(k,v)=>storageValues.set(k,v),removeItem:k=>storageValues.delete(k)};
 const eventTarget=()=>({events:{},addEventListener(k,f){(this.events[k]??=[]).push(f);},removeEventListener(k,f){this.events[k]=(this.events[k]||[]).filter(x=>x!==f);},emit(k,e={}){for(const f of this.events[k]||[])f(e);}});
 let doc;
 function node(tag='div'){creations++;const n={...eventTarget(),tagName:tag.toUpperCase(),children:[],dataset:{},attrs:{},style:{},hidden:false,disabled:false,open:false,textContent:'',ownerDocument:doc,
 append(...children){for(const x of children){x.parentNode=this;this.children.push(x);}},replaceChildren(...children){this.children=[];this.append(...children);},remove(){if(this.parentNode)this.parentNode.children=this.parentNode.children.filter(x=>x!==this);},setAttribute(k,v){this.attrs[k]=String(v);},getAttribute(k){return this.attrs[k]??null;},removeAttribute(k){delete this.attrs[k];},focus(){this.focused=true;},showModal(){this.open=true;},close(){this.open=false;},getBoundingClientRect(){return {width:390,height:500,top:0,left:0,right:390,bottom:500};},querySelectorAll(selector){return all(this).filter(x=>selector==='[data-tab]'?!!x.dataset.tab:selector==='button'?x.tagName==='BUTTON':selector==='img[data-pending-icon-src]'?x.tagName==='IMG'&&!!x.dataset.pendingIconSrc:false);},set src(v){this.attrs.src=v;},get src(){return this.attrs.src;}};
 n.classList={add(k){n.className=(n.className||'')+' '+k;},contains(k){return (n.className||'').split(' ').includes(k);}};return n;}
 function all(n){return [n,...n.children.flatMap(all)];}
 const nodes=new Map(['world-bar','world-status','world-toggle','screen','connection','main-nav','sheet','sheet-title','sheet-content','close-sheet','refresh','toast'].map(id=>[id,node()]));
 const win={...eventTarget(),scrollY:0,innerHeight:844,innerWidth:390,scrollTo(x,y){this.scrollY=y;},matchMedia:()=>({...eventTarget(),matches:false}),requestAnimationFrame:f=>{timers.set(++serial,f);return serial;},cancelAnimationFrame:id=>timers.delete(id)};
 doc={...eventTarget(),body:{dataset:{uiReview:'true'}},hidden:false,defaultView:win,createElement:tag=>node(tag),getElementById:id=>nodes.get(id),querySelector:()=>null};for(const n of nodes.values())n.ownerDocument=doc;
 for(const name of ['sect','disciples','cultivation','inventory','adventure']){const a=node('a');a.dataset.tab=name;nodes.get('main-nav').append(a);}
 const location={hash:'',href:'',search:'?case=boss'},navigator={onLine:true};let current=clone(fixture);
 const fetch=async(url,options={})=>{if(readGate)await readGate;fetches.push({url,method:options.method||'GET'});if(!url.startsWith('/game/review/api/'))throw Error('Private API requested: '+url);return {ok:true,status:200,json:async()=>clone(url.endsWith('/assets')?{protocol_version:1,presentation:assetManifest}:current)};};
 const globals={document:doc,window:win,location,navigator,fetch,sessionStorage:store,crypto:{randomUUID:()=>`00000000-0000-4000-8000-${String(++serial).padStart(12,"0")}`},setTimeout:(f,ms)=>{timers.set(++serial,{f,ms});return serial;},clearTimeout:id=>timers.delete(id)};
 const modules=new Map();
 function load(path){if(modules.has(path))return modules.get(path);let source=sources[path];assert(source!==undefined,`Missing module ${path}`);const imports={};source=source.replace(/^import\s+(.+?)\s+from\s+['"](.+?)['"];?\s*$/gm,(_,bindings,target)=>{let parts=path.split('/');parts.pop();for(const p of target.split('/')){if(p==='..')parts.pop();else if(p!=='.')parts.push(p);}const dependency=load(parts.join('/'));if(bindings.startsWith('* as '))imports[bindings.slice(5)]=dependency;else for(const entry of bindings.replace(/[{}]/g,'').split(',')){const [key,alias]=entry.trim().split(/\s+as\s+/);imports[alias||key]=dependency[key];}return '';});
 const exports=[...source.matchAll(/export\s+(?:async\s+)?(?:function|class|const)\s+(\w+)/g)].map(m=>m[1]);source=source.replace(/export\s+/g,'');const args={...globals,...imports};const output=new Function(...Object.keys(args),source+`;return {${exports.join(',')}};`)(...Object.values(args));modules.set(path,output);return output;}
 const base='src/ui/pages/game/static/';
 const {ReviewClient}=load(base+'review-client.js');const review=new ReviewClient({fetcher:fetch,search:'?case=boss'});
 await review.sync(true);await review.poll();assert(review.pending()===null,'No private pending replay');checks++;
 for(const lane of ['action','combat','cultivation','economy','world']){let blocked=false;try{await review[lane]('arbitrary');}catch(e){blocked=e.code==='REVIEW_READONLY';}assert(blocked,'Mutation lane blocked '+lane);checks++;}
 const {runtimeURL}=load(base+'battle/metadata.js');assert(runtimeURL('/game/review/runtime/monster.static.test/'+ 'a'.repeat(64)).includes('/review/'),'Explicit review runtime allowed');checks++;
 for(const url of ['/game/review/runtime/../private','/game/review/source/test','https://outside.test/game/review/runtime/test']){let blocked=false;try{runtimeURL(url);}catch{blocked=true;}assert(blocked,'Unsafe runtime rejected');checks++;}
 load(base+'game.js');for(let i=0;i<50;i++)await Promise.resolve();assert(nodes.get('screen').children.length,'Review boots shipped game root');assert(nodes.get('main-nav').children[0].getAttribute('aria-current')==='page','Default sect');checks++;
 const stableRoot=nodes.get('screen').children[0],created=creations;let release;readGate=new Promise(resolve=>release=resolve);nodes.get('refresh').emit('click');
 assert(nodes.get('screen').getAttribute('aria-busy')==='true'&&creations===created,'Sync begin updates busy without constructing a comparison tree');checks++;
 const gates=all(nodes.get('screen')).filter(n=>n.tagName==='BUTTON');assert(gates.every(n=>n.disabled),'In-flight sync gates existing buttons');checks++;
 release();readGate=null;for(let i=0;i<80;i++)await Promise.resolve();assert(creations===created&&nodes.get('screen').children[0]===stableRoot&&nodes.get('screen').getAttribute('aria-busy')==='false','Identical snapshot skips reconstruction and restores busy');checks++;
 current.view.inventory.coins.quantity+=1;current.view.holdings.coins.quantity+=1;const changedCreations=creations;nodes.get('refresh').emit('click');for(let i=0;i<80;i++)await Promise.resolve();assert(creations>changedCreations&&nodes.get('screen').children[0]===stableRoot,'Changed facts update retained screen instead of being skipped');checks++;
 for(const route of ['disciples','cultivation','inventory','adventure','battle','building/alchemy','settings']){location.hash='#'+route;win.emit('hashchange');for(let i=0;i<50;i++)await Promise.resolve();assert(nodes.get('screen').children.length,'Actual screen rendered '+route);checks++;}
 location.hash='#battle';win.emit('hashchange');for(let i=0;i<50;i++)await Promise.resolve();
 const auto=all(nodes.get('screen')).find(n=>n.id==='combat-auto-toggle');assert(auto&&!auto.disabled,'Real battle control visible');auto.emit('click');for(let i=0;i<100;i++)await Promise.resolve();assert(nodes.get('toast').textContent.includes('只读 UI'),'Mutation button displays read-only message');checks++;
 location.hash='#inventory';win.emit('hashchange');for(let i=0;i<50;i++)await Promise.resolve();const detail=all(nodes.get('screen')).find(n=>n.tagName==='BUTTON'&&n.events.click?.length&&all(n).some(x=>x.tagName==='IMG'));assert(detail,'Item detail button available');detail.emit('click');assert(nodes.get('sheet').open,'Actual item bottom sheet opens');checks++;
 doc.hidden=true;doc.emit('visibilitychange');doc.hidden=false;doc.emit('visibilitychange');for(let i=0;i<50;i++)await Promise.resolve();
 assert(fetches.every(x=>x.method==='GET'&&x.url.startsWith('/game/review/api/')),'All initial/navigation/foreground requests read-only');assert(![...timers.values()].some(x=>x.ms===2000||x.ms===4000),'No simulation polling');checks++;
 assert(storageValues.size===0,'No command intent written to sessionStorage');checks++;
 return {tests:checks,status:'PASS',kind:'native JS/DOM; not browser screenshots'};
}

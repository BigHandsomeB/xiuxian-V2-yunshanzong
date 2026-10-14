// Run shipped native ES modules in a V8 isolate. DOM harness tests behavior,
// not Safari layout, painting, or device performance.
async function testConceptThemeUI(sources, fixture, realFetcher=null) {
 const assert=(v,m)=>{if(!v)throw Error(m);};const clone=v=>JSON.parse(JSON.stringify(v));let checks=0;
 const listeners=new Map(),timers=new Map(),fetches=[],storageValues=new Map();let serial=0;
 const store={getItem:k=>storageValues.get(k)||null,setItem:(k,v)=>storageValues.set(k,v),removeItem:k=>storageValues.delete(k)};
 const eventTarget=()=>({events:{},addEventListener(k,f){(this.events[k]??=[]).push(f);},removeEventListener(k,f){this.events[k]=(this.events[k]||[]).filter(x=>x!==f);},emit(k,e={}){for(const f of this.events[k]||[])f(e);}});
 let doc;
 function node(tag='div'){const n={...eventTarget(),tagName:tag.toUpperCase(),children:[],dataset:{},attrs:{},style:{},hidden:false,disabled:false,open:false,textContent:'',ownerDocument:doc,
 append(...children){for(const x of children){x.parentNode=this;this.children.push(x);}},replaceChildren(...children){this.children=[];this.append(...children);},remove(){if(this.parentNode)this.parentNode.children=this.parentNode.children.filter(x=>x!==this);},setAttribute(k,v){this.attrs[k]=String(v);},getAttribute(k){return this.attrs[k]??null;},removeAttribute(k){delete this.attrs[k];},focus(){this.focused=true;},showModal(){this.open=true;},close(){this.open=false;},getBoundingClientRect(){return {width:390,height:500,top:0,left:0,right:390,bottom:500};},querySelectorAll(selector){return all(this).filter(x=>selector==='[data-tab]'?!!x.dataset.tab:false);},set src(v){this.attrs.src=v;},get src(){return this.attrs.src;}};
 n.classList={add(k){n.className=(n.className||'')+' '+k;},contains(k){return (n.className||'').split(' ').includes(k);}};return n;}
 function all(n){return [n,...n.children.flatMap(all)];}
 const nodes=new Map(['screen','connection','main-nav','sheet','sheet-title','sheet-content','close-sheet','refresh','toast'].map(id=>[id,node()]));
 const win={...eventTarget(),scrollY:0,innerHeight:844,innerWidth:390,scrollTo(x,y){this.scrollY=y;},matchMedia:()=>({...eventTarget(),matches:false}),requestAnimationFrame:f=>{timers.set(++serial,f);return serial;},cancelAnimationFrame:id=>timers.delete(id)};
 doc={...eventTarget(),hidden:false,defaultView:win,createElement:tag=>node(tag),getElementById:id=>nodes.get(id)};for(const n of nodes.values())n.ownerDocument=doc;
 for(const name of ['sect','disciples','cultivation','inventory','adventure']){const a=node('a');a.dataset.tab=name;nodes.get('main-nav').append(a);}
 const location={hash:'',href:''},navigator={onLine:true};let current=clone(fixture);
 const fetch=async(url,options={})=>{fetches.push({url,body:options.body?JSON.parse(options.body):null});if(realFetcher)return realFetcher(url,options);if(url.endsWith('/assets'))return {ok:true,status:200,json:async()=>({protocol_version:1,presentation:{...current.presentation,catalog:current.catalog}})};return {ok:true,status:200,json:async()=>clone(current)};};
 const globals={document:doc,window:win,location,navigator,fetch,sessionStorage:store,crypto:{randomUUID:()=>`00000000-0000-4000-8000-${String(++serial).padStart(12,"0")}`},setTimeout:(f,ms)=>{timers.set(++serial,{f,ms});return serial;},clearTimeout:id=>timers.delete(id)};
 const modules=new Map();
 function load(path){if(modules.has(path))return modules.get(path);let source=sources[path];assert(source!==undefined,`Missing module ${path}`);const imports={};source=source.replace(/^import\s+(.+?)\s+from\s+['"](.+?)['"];?\s*$/gm,(_,bindings,target)=>{let parts=path.split('/');parts.pop();for(const p of target.split('/')){if(p==='..')parts.pop();else if(p!=='.')parts.push(p);}const dependency=load(parts.join('/'));if(bindings.startsWith('* as '))imports[bindings.slice(5)]=dependency;else for(const entry of bindings.replace(/[{}]/g,'').split(',')){const [key,alias]=entry.trim().split(/\s+as\s+/);imports[alias||key]=dependency[key];}return '';});
 const exports=[...source.matchAll(/export\s+(?:async\s+)?(?:function|class|const)\s+(\w+)/g)].map(m=>m[1]);source=source.replace(/export\s+/g,'');const args={...globals,...imports};const output=new Function(...Object.keys(args),source+`;return {${exports.join(',')}};`)(...Object.values(args));modules.set(path,output);return output;}


 const check=(v,m)=>{assert(v,m);checks++;},base='src/ui/pages/game/static/';
 win.document=doc;win.localStorage=store;doc.documentElement=node('html');const media={...eventTarget(),matches:false};win.matchMedia=()=>media;
 const {themePreference}=load(base+'theme.js');let theme=themePreference(win),before=JSON.stringify(current.view);
 check(theme.mode==='SYSTEM'&&doc.documentElement.getAttribute('data-theme')==='light','Default system light');
 theme.set('DARK');check(doc.documentElement.getAttribute('data-theme')==='dark','Dark applies root');check(store.getItem('xianxia-ui-theme')==='DARK','Preference saved locally');
 media.matches=false;media.emit('change');check(doc.documentElement.getAttribute('data-theme')==='dark','Explicit DARK ignores system');
 theme.set('LIGHT');check(doc.documentElement.getAttribute('data-theme')==='light','Light restores');media.matches=true;media.emit('change');check(doc.documentElement.getAttribute('data-theme')==='light','Explicit LIGHT ignores system');
 theme.set('SYSTEM');check(doc.documentElement.getAttribute('data-theme')==='dark','System dark read');media.matches=false;media.emit('change');check(doc.documentElement.getAttribute('data-theme')==='light','System change live');
 check((media.events.change||[]).length===1,'Single media listener');theme.dispose();check((media.events.change||[]).length===0,'Theme disposal removes listener');
 theme=themePreference(win);check(theme.mode==='SYSTEM','Refresh preference persists');theme.set('DARK');theme.dispose();theme=themePreference(win);check(theme.mode==='DARK'&&doc.documentElement.getAttribute('data-theme')==='dark','Refresh DARK persists');
 theme.set('INVALID');check(theme.mode==='DARK','Invalid preference rejected');
 theme.set('SYSTEM');media.matches=true;doc.hidden=true;doc.emit('visibilitychange');doc.hidden=false;doc.emit('visibilitychange');check(doc.documentElement.getAttribute('data-theme')==='dark','Safari foreground keeps current system appearance');
 const bad={...win,localStorage:{getItem(){throw Error('private');},setItem(){throw Error('private');}}};const privateTheme=themePreference(bad);privateTheme.set('LIGHT');check(privateTheme.mode==='LIGHT','Unavailable localStorage degrades safely');privateTheme.dispose();
 const legacyMedia={matches:true,addListener(f){this.listener=f;},removeListener(f){if(f===this.listener)this.listener=null;}},legacy={...win,matchMedia:()=>legacyMedia};const legacyTheme=themePreference(legacy);legacyTheme.set('SYSTEM');check(doc.documentElement.getAttribute('data-theme')==='dark','Older Safari matchMedia listener');legacyTheme.dispose();check(!legacyMedia.listener,'Older listener cleanup');
 check(JSON.stringify(current.view)===before&&fetches.length===0,'Theme never mutates Pause Time Combat Production Inventory or requests');
 const {itemIcon,resourceIcon,systemIcon}=load(base+'components/item-icon.js'),data=load(base+'adapters.js').gameView(current),ctx={data,ui:{},theme,busy:false,route:{name:'settings'},redraw(){},reloadAssets(){},sync(){},sheet(){},economyAction(){}};
 const settings=load(base+'screens/settings.js').render(ctx);const buttons=all(settings).filter(n=>n.dataset.themeMode);check(buttons.length===3,'Three theme controls');buttons.find(n=>n.dataset.themeMode==='LIGHT').emit('click');check(theme.mode==='LIGHT','Settings LIGHT action');buttons.find(n=>n.dataset.themeMode==='DARK').emit('click');check(theme.mode==='DARK','Settings DARK action');buttons.find(n=>n.dataset.themeMode==='SYSTEM').emit('click');check(theme.mode==='SYSTEM','Settings SYSTEM action');
 check(all(settings).some(n=>n.dataset.systemIcon==='light')&&all(settings).some(n=>n.dataset.systemIcon==='dark'),'Day and night official icon slots');
 data.assetManifest={catalog:fixture.catalog};ctx.route={name:'inventory',id:'catalog'};ctx.ui.catalogCategory='concepts';let shown=null;ctx.sheet=(name,body)=>shown={name,body};const catalog=load(base+'screens/catalog.js');let page=catalog.render(ctx);const cells=all(page).filter(n=>n.dataset.catalogAsset);check(cells.length===81,'All81 deduplicated concepts');
 check(cells.filter(n=>n.dataset.catalogAsset==='icon.material.ad0fb1bcacd94').length===1,'Blood one concept identity');check(!cells.some(n=>n.dataset.catalogAsset==='icon.resource.a2dce3aedb26f'),'Alternative blood image not a duplicate concept');
 check(!all(page).some(n=>n.className==='icon-quantity'),'No fake quantities in concept catalog');
 ctx.ui.conceptCategory='beast';page=catalog.render(ctx);check(all(page).filter(n=>n.dataset.catalogAsset).length===12,'Blood is also visible in beast category');
 ctx.ui.conceptCategory='material';page=catalog.render(ctx);check(all(page).filter(n=>n.dataset.catalogAsset).length===15,'Materials category including same blood concept');
 ctx.ui.conceptCategory='all';page=catalog.render(ctx);all(page).find(n=>n.dataset.catalogAsset==='icon.resource.a349ad28df67f').emit('click');check(shown&&all(shown.body).some(n=>n.textContent==='素材已登记，玩法尚未开放。'),'Spirit iron no invented Gameplay');
 check(all(shown.body).some(n=>n.dataset.profile==='detail'),'Concept96px detail');
 const fallback=itemIcon({asset_id:'missing',fallback:'resource'});check(fallback.dataset.assetFallback==='true','Missing asset consistent fallback');const broken=itemIcon({asset_id:'published',asset:{url:'/game/runtime/published/hash'}});broken.children.find(n=>n.tagName==='IMG').emit('error');check(broken.dataset.assetFallback==='true'&&!broken.children[0].hidden,'Runtime load error restores fallback');
 for(const key of ['hp','mp','cultivation','attack','defense','power','disciples','production','pause','automation','auto_combat','light','dark','capacity','locked','favorite'])check(systemIcon(ctx,key).dataset.systemIcon===key,'System icon:'+key);
 ctx.route={name:'sect'};const sect=load(base+'screens/sect.js').render(ctx);check(all(sect).some(n=>n.dataset.systemIcon==='disciples'),'Sect real workforce icon');
 ctx.route={name:'inventory'};const bag=load(base+'screens/inventory.js').render(ctx);check(all(bag).some(n=>n.dataset.systemIcon==='capacity'),'Bag capacity icon');
 const money=resourceIcon(ctx,'coins');check(money.dataset.assetId===data.presentation.icons.coins.asset_id,'Currency uses unified map');const herb=resourceIcon(ctx,'herb'),ore=resourceIcon(ctx,'ore');check(herb.dataset.assetId===data.presentation.icons.herb.asset_id&&ore.dataset.assetId!==fixture.catalog.groups.find(g=>g.name==='基础货币与资源')?.items.find(r=>r.concept_id==='concept.spirit_iron_ore')?.asset_id,'Herb unified, ore never spirit iron');
 check(JSON.stringify(current.view)===before&&fetches.length===0,'Icon/catalog rendering never changes gameplay or sends Command');
 theme.dispose();
 return {tests:checks,status:'PASS',scope:'81 concepts + UI theme/identity/readonly; device pending'};
}

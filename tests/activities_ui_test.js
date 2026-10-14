// Run shipped native ES modules in a V8 isolate. DOM harness tests behavior,
// not Safari layout, painting, or device performance.
async function testActivitiesUI(sources, fixture, realFetcher=null) {
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
 const screen=load(base+'screens/activities.js'),patch=load(base+'components/patch.js');
 const click=(tree,text)=>{const n=all(tree).find(n=>n.tagName==='BUTTON'&&n.textContent===text);check(!!n,'button '+text);check(!n.disabled,'enabled '+text);n.emit('click');};
 const confirm=()=>click(shown.content,'确认');
 for(const width of [320,390,430])for(const theme of ['LIGHT','DARK']){
  win.innerWidth=width;ctx.theme={mode:theme,set(){}};
  let tree=screen.renderCommissions(ctx);check(all(tree).filter(n=>n.dataset.id?.startsWith('commission:')).length===3,'three actual commissions');
  const icons=all(tree).filter(n=>n.classList?.contains('item-icon'));patch.patchPanel(tree,screen.renderCommissions(ctx));check(icons.every(n=>all(tree).includes(n)),'same icons retained on refresh');
  let count=commands.length;click(tree,'交付委托');check(commands.length===count,'commission requires confirmation');confirm();check(commands.at(-1).name==='sect_commission_claim','claim command');check(commands.at(-1).payload.quote_id===data.view.sect_activities.orders[0].quote_id,'server quote retained');
  tree=screen.renderContributionExchange(ctx);check(all(tree).filter(n=>n.dataset.id?.startsWith('contribution:')).length===6,'six actual exchanges');
  check(tree.children.at(-1).classList.contains('recipe-grid'),'reuse two-column grid');check(tree.children.at(-1).children.length===6,'six exchange cards');check(tree.children.at(-1).children.every(n=>n.classList.contains('recipe-card')),'exchange card layout');
  count=commands.length;click(tree,'40 贡献兑换');check(commands.length===count,'exchange requires confirmation');confirm();check(commands.at(-1).name==='sect_contribution_exchange'&&commands.at(-1).payload.exchange_id==='wood','exchange intent');
  tree=screen.renderChoiceChests(ctx);check(all(tree).filter(n=>n.dataset.id?.startsWith('choice-chest:')).length===1,'saved chest visible');
  click(tree,'查看并选择奖励');check(all(shown.content).filter(n=>n.tagName==='BUTTON'&&n.textContent.startsWith('选择')).length===3,'three explicit choices');
  count=commands.length;click(shown.content,'选择功法成长');check(commands.length===count,'choice requires confirmation');confirm();check(commands.at(-1).name==='boss_chest_open'&&commands.at(-1).payload.choice==='techniques'&&commands.at(-1).payload.chest_id==='thorn_path','exact chest choice');
  ctx.busy=true;tree=screen.renderCommissions(ctx);check(all(tree).filter(n=>n.tagName==='BUTTON').every(n=>n.disabled),'busy claims disabled');ctx.busy=false;
 }
 const p=data.view.sect_activities;p.blocked=true;
 check(all(screen.renderContributionExchange(ctx)).filter(n=>n.tagName==='BUTTON').every(n=>n.disabled),'pending exchanges disabled');
 check(all(screen.renderChoiceChests(ctx)).filter(n=>n.tagName==='BUTTON').every(n=>n.disabled),'pending chest disabled');p.blocked=false;
 const held=p.chests;p.chests=[];check(screen.renderChoiceChests(ctx).children.length===0,'no fake chest when none saved');p.chests=held;
 return {checks,context:'real projection and shipped modules; DOM at 320/390/430 light/dark, not browser painting'};
}

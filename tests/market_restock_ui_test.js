// Run shipped native ES modules in a V8 isolate. DOM harness tests behavior,
// not Safari layout, painting, or device performance.
async function testMarketRestockUI(sources, fixture, realFetcher=null) {
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
 const ctx={data,ui:{},busy:false,route:{name:'building',id:'market'},sheet:(title,content)=>shown={title,content},redraw(){},sync(){},economyAction:(name,payload)=>commands.push({name,payload})};
 const screen=load(base+'screens/market-restock.js'),patch=load(base+'components/patch.js');
 const click=(tree,text)=>{const b=all(tree).find(n=>n.tagName==='BUTTON'&&n.textContent===text);check(!!b,'button '+text);check(!b.disabled,'enabled '+text);b.emit('click');};
 const inputs=tree=>all(tree).filter(n=>n.tagName==='INPUT');
 for(const width of [320,390,430])for(const theme of ['LIGHT','DARK']){
  win.innerWidth=width;ctx.theme={mode:theme,set(){}};
  let tree=screen.renderRestock(ctx);const row=all(tree).find(n=>n.dataset.id?.startsWith('restock-')&&n.dataset.id!=='restock-log');
  check(!!row,width+'/'+theme+' row from server');
  check(all(row).some(n=>n.textContent.includes('保有量 10')),'server stock target');
  const icon=all(row).find(n=>n.classList.contains('item-icon'));
  patch.patchPanel(tree,screen.renderRestock(ctx));check(all(tree).includes(row),'stable row retained');check(all(tree).includes(icon),'stable icon retained');
  click(tree,'新增购买清单');check(shown.title==='新增购买清单','add sheet');
  const select=all(shown.content).find(n=>n.tagName==='SELECT'),target=inputs(shown.content)[0];
  check(select.children.length===data.view.sect_services.restock.eligible.length-1,'already configured omitted');
  check(select.children.every(n=>data.view.sect_services.restock.eligible.some(r=>r.resource_id===n.value)),'only unlocked choices');
  target.value='0';const count=commands.length;click(shown.content,'保存购买清单');check(commands.length===count,'invalid target no command');
  target.value='123';click(shown.content,'保存购买清单');check(commands.at(-1).name==='market_restock_set'&&commands.at(-1).payload.target===123,'add command');
  click(tree,'修改保有量');const change=all(shown.content).find(n=>n.tagName==='SELECT');
  check(change.disabled&&change.value===data.view.sect_services.restock.rows[0].resource_id,'edit fixed material');inputs(shown.content)[0].value='77';click(shown.content,'保存保有量');check(commands.at(-1).payload.target===77,'edit target');
  click(tree,'删除清单');check(shown.title==='删除购买清单','delete confirmation');click(shown.content,'确认');check(commands.at(-1).name==='market_restock_delete','delete command');
  click(tree,'分配弟子');check(shown.title.includes('分配弟子'),'existing work sheet');click(shown.content,'安排工作弟子');check(commands.at(-1).name==='work_assign'&&commands.at(-1).payload.count===1,'real shared workforce intent');
  ctx.busy=true;tree=screen.renderRestock(ctx);check(all(tree).filter(n=>n.tagName==='BUTTON'&&['新增购买清单','修改保有量','删除清单'].includes(n.textContent)).every(n=>n.disabled),'busy protects commands');ctx.busy=false;
  data.view.time.pending=true;tree=screen.renderRestock(ctx);check(all(tree).filter(n=>n.tagName==='BUTTON'&&['新增购买清单','修改保有量','删除清单'].includes(n.textContent)).every(n=>n.disabled),'pending protects commands');data.view.time.pending=false;
  ctx.ui.marketTab='restock';const market=load(base+'screens/sect-management.js').renderMaterials(ctx);check(all(market).some(n=>n.dataset.id==='market-restock'),'market tab routes to new feature');
 }
 const restockCurrent=data.view.sect_services.restock;delete data.view.sect_services.restock;check(all(screen.renderRestock(ctx)).some(n=>n.textContent==='自动补货尚未开放'),'old server fallback');data.view.sect_services.restock=restockCurrent;
 const GameClient=load(base+'api-client.js').GameClient;
 for(const [name,payload] of [['market_restock_set',{resource_id:restockCurrent.rows[0].resource_id,target:123}],['market_restock_delete',{resource_id:restockCurrent.rows[0].resource_id}]]){
  const state={protocol_version:1,csrf:'fixture',view:{save_id:'fixture',generation:1,revision:7,world:{paused:true},time:{pending:false}}},requests=[],values=new Map();
  const client=new GameClient({uuid:()=> 'request-fixture',storage:{getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)},fetcher:async(path,opt)=>{
   const body=opt.body?JSON.parse(opt.body):null;requests.push({path,body});if(path.endsWith('/command')){state.view.revision++;return {ok:true,status:200,json:async()=>({receipt:{committed_revision:state.view.revision}})};}return {ok:true,status:200,json:async()=>clone(state)};
  }});
  await client.economy(name,payload);const sent=requests.filter(r=>r.path.endsWith('/command'));check(sent.length===1,'client accepts '+name);check(JSON.stringify(sent[0].body.command.payload)===JSON.stringify(payload),'client exact payload '+name);
 }
 return {checks,scope:'native DOM and real client, six width/theme contexts; phone layout unverified'};
}

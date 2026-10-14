// Run shipped native ES modules in a V8 isolate. DOM harness tests behavior,
// not Safari layout, painting, or device performance.
async function testMarketPurchaseDialog(sources) {
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

 const commands=[];
 const offer={resource_id:'wood',name:'灵木',quantity:0,remaining_stock:30,max_quantity:0,price:3,price_milli:3000,market_day:1,variation_percent:0};
 const data={view:{inventory:{},world:{paused:false},time:{pending:true,simulation_time_ms:0},sect_services:{market:{offers:[offer],display_day:2,remaining_seconds:60},materials:[]}},presentation:{}};
 const ctx={data,ui:{marketTab:'buy'},busy:true,sheet:(title,content)=>{nodes.get('sheet-content').replaceChildren(content);nodes.get('sheet').open=true;},redraw(){},economyAction:(name,payload)=>commands.push({name,payload})};
 const market=load(base+'screens/sect-management.js');
 const grid=market.renderMaterials(ctx);all(grid).find(n=>n.className==='inventory-item').emit('click');
 const panel=nodes.get('sheet-content').children[0],findBuy=()=>all(panel).find(n=>n.textContent==='购买材料');
 check(findBuy().disabled,'pending disables purchase');
 ctx.busy=false;data.view.time.pending=false;offer.max_quantity=30;
 const renderHook=sources[base+'game.js'].split('\n').find(line=>line.trim().startsWith('if(context){'));
 check(!!renderHook,'game render updates active context');
 const refresh=(nextData=data,busy=ctx.busy)=>new Function('context','data','client','controlBusy','$',renderHook)(ctx,nextData,{},busy,id=>nodes.get(id));
 refresh();
 check(!findBuy().disabled,'purchase must recover after pending completes without reopening dialog');
 const input=all(panel).find(n=>n.tagName==='INPUT'),icon=all(panel).find(n=>n.classList?.contains('item-icon'));
 input.value='12';input.emit('input');refresh();
 check(all(panel).includes(input)&&input.value==='12','refresh preserves typed quantity and input node');
 check(all(panel).includes(icon),'unchanged resource icon retained');
 check(!findBuy().disabled,'valid edited quantity stays available');
 const next={...data,view:{...data.view,sect_services:{...data.view.sect_services,market:{...data.view.sect_services.market,offers:[{...offer,max_quantity:4}]}}}};
 refresh(next,false);check(findBuy().disabled,'quantity above changed limit blocked');
 input.value='3';input.emit('input');check(!findBuy().disabled,'valid revised quantity unblocks');
 refresh(next,true);check(findBuy().disabled,'in-flight command blocks repeated submit');
 refresh(next,false);check(!findBuy().disabled,'command completion recovers without retyping');
 const quote={...next,view:{...next.view,sect_services:{...next.view.sect_services,market:{...next.view.sect_services.market,offers:[{...offer,max_quantity:4,price:7,price_milli:7000,market_day:2}]}}}};
 refresh(quote,false);findBuy().emit('click');
 const confirmation=nodes.get('sheet-content').children[0];all(confirmation).find(n=>n.textContent==='确认').emit('click');
 check(commands.length===1&&commands[0].name==='market_buy','one confirmed purchase intent');
 check(commands[0].payload.quantity===3&&commands[0].payload.price_milli===7000&&commands[0].payload.market_day===2,'request uses preserved quantity and latest quote');
 nodes.get('sheet-content').replaceChildren(panel);
 const removed={...quote,view:{...quote.view,sect_services:{...quote.view.sect_services,market:{...quote.view.sect_services.market,offers:[]}}}};
 refresh(removed,false);check(!findBuy()&&all(panel).some(n=>n.textContent.includes('已下架')),'removed daily offer cannot be purchased');
 refresh(quote,false);check(!!findBuy()&&!findBuy().disabled,'restocked offer recovers');
 refresh({...quote,view:{...quote.view,world:{paused:true}}},false);check(!findBuy().disabled,'paused world permits instant purchases');
 return {tests:checks,status:'PASS',scope:'actual market dialog, game refresh hook, drafts and daily quotes'};
}

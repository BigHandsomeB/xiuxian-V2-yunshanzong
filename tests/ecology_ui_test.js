// Run shipped native ES modules in a V8 isolate. DOM harness tests behavior,
// not Safari layout, painting, or device performance.
async function testEcologyUI(sources, fixture, realFetcher=null) {
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
 const ctx={data,ui:{},busy:false,route:{name:'building',id:'garden'},sheet:(title,content)=>shown={title,content},redraw(){},sync(){},economyAction:(name,payload)=>commands.push({name,payload})};
 const screen=load(base+'screens/ecology.js'),patch=load(base+'components/patch.js');
 const clickText=(tree,text)=>{const button=all(tree).find(n=>n.tagName==='BUTTON'&&n.textContent===text);check(!!button,'button '+text);button.emit('click');};
 const confirm=()=>clickText(shown.content,'确认');
 for(const width of [320,390,430])for(const theme of ['LIGHT','DARK']){
  win.innerWidth=width;ctx.theme={mode:theme,set(){}};
  ctx.ui.ecologyTabs={};
  let node=screen.renderGarden(ctx);check(all(node).some(n=>n.className==='recipe-grid'),width+'/'+theme+' garden shared grid');
  check(all(node).filter(n=>n.dataset.recipeId?.startsWith('grow_sect_crop_')).length===17,'all seventeen new crops');
  const icons=all(node).filter(n=>n.classList?.contains('item-icon'));patch.patchPanel(node,screen.renderGarden(ctx));check(icons.every(n=>all(node).includes(n)),'garden icons retained during world update');
  ctx.ui.ecologyTabs.pasture='purchase';node=screen.renderHusbandry(ctx,'pasture');
  check(all(node).filter(n=>n.dataset.id?.startsWith('species-pasture')).length===12,'all twelve beasts');
  all(node).find(n=>n.dataset.id==='species-pasture_species_02').emit('click');
  check(shown.title==='金羽灵鸡','purchase detail names exact species');clickText(shown.content,'购入幼体');confirm();
  check(commands.at(-1).name==='ecology_buy'&&commands.at(-1).payload.species_id==='pasture_species_02'&&commands.at(-1).payload.count===1,'purchase emits exact transaction intent');
  ctx.ui.ecologyTabs.spring='purchase';node=screen.renderHusbandry(ctx,'spring');check(all(node).filter(n=>n.dataset.id?.startsWith('species-spring')).length===12,'all twelve aquatics');
  ctx.ui.ecologyTabs.pasture='stock';node=screen.renderHusbandry(ctx,'pasture');const owned=all(node).find(n=>n.dataset.id?.startsWith('batch-'));check(!!owned,'real owned batch');owned.emit('click');
  clickText(shown.content,'采集产物');check(commands.at(-1).name==='ecology_collect'&&commands.at(-1).payload.mode==='periodic','periodic action exact batch');
  clickText(shown.content,'屠宰收获');confirm();check(commands.at(-1).payload.mode==='harvest','destructive harvest requires confirmation');
  ctx.ui.ecologyTabs.meals='basic';node=screen.renderMeals(ctx);check(all(node).filter(n=>n.dataset.recipeId?.startsWith('meal_')||n.dataset.recipeId?.startsWith('supplement_recipe_')).length===19,'six original base recipes plus thirteen shanhai variants');
  ctx.ui.ecologyTabs.meals='position';node=screen.renderMeals(ctx);check(all(node).filter(n=>n.dataset.recipeId?.startsWith('meal_')).length===20,'all twenty position recipes');
  ctx.ui.ecologyTabs.meals='supply';node=screen.renderMeals(ctx);check(all(node).some(n=>n.textContent==='基础灵膳供应'),'daily supply settings');
  clickText(node,'开启自动供养');confirm();check(commands.at(-1).name==='ecology_supply'&&commands.at(-1).payload.target_days===3,'daily supply emits target days');
  const position=all(node).find(n=>n.dataset.id?.startsWith('position-'));check(!!position,'position meal cards');position.emit('click');
  const meal=all(shown.content).find(n=>n.dataset.id?.startsWith('meal-choice-'));check(!!meal,'matching meal choices');meal.emit('click');confirm();check(commands.at(-1).name==='ecology_meal','position meal uses authoritative command');
  node=screen.renderFacilities(ctx);check(all(node).filter(n=>n.dataset.recipeId?.startsWith('build_')).length===4,'four facility construction recipes');
  for(const row of data.view.economy.recipes.filter(r=>r.facility_id)){
   const card=all(node).find(n=>n.dataset.recipeId===row.recipe_id);
   const expected=data.presentation.system_icons[row.facility_id].asset_id;
   check(all(card).some(n=>n.dataset.assetId===expected&&n.__runtimeURL),'facility card uses approved runtime '+row.facility_id);
   card.emit('click');check(all(shown.content).some(n=>n.dataset.assetId===expected&&n.__runtimeURL),'facility detail uses same runtime');
  }
  check(!all(node).some(n=>n.textContent.includes('干粮')),'new UI contains no dry-food concepts');
 }
 const allowed=data.view.ecology.available;data.view.ecology.available=false;ctx.ui.ecologyTabs.pasture='purchase';let pausedPage=screen.renderHusbandry(ctx,'pasture');all(pausedPage).find(n=>n.dataset.id==='species-pasture_species_02').emit('click');check(all(shown.content).filter(n=>n.tagName==='BUTTON').every(n=>n.disabled),'paused purchase controls disabled');data.view.ecology.available=allowed;
 const css=sources[base+'game.css'];check(/\.recipe-grid\{[^}]*grid-template-columns:repeat\(2,minmax\(0,1fr\)\)/.test(css),'shared grid has exactly two columns');check(!/\.ecology[^}]*grid-template-columns:repeat\([134]/.test(css),'no ecology override introduces another card count');
 return {checks,context:'native DOM at 320/390/430 with light/dark contexts; no device painting claim'};
}

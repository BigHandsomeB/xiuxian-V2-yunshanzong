// Run shipped native ES modules in a V8 isolate. DOM harness tests behavior,
// not Safari layout, painting, or device performance.
async function testWarehouseUI(sources, fixture, realFetcher=null) {
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



 const data=load(base+'adapters.js').gameView(fixture),before=JSON.stringify(data.view),commands=[];let shown;
 const ctx={data,ui:{},busy:false,route:{name:'inventory'},redraw(){},sheet:(title,content)=>shown={title,content},economyAction:(name,payload)=>commands.push({name,payload})};
 const inventory=load(base+'screens/inventory.js'),groups=load(base+'warehouse-categories.js'),patch=load(base+'components/patch.js');
 const cases={coins:'currency',spirit_stone_immortal:'currency',water_spirit_stone:'mineral',ingot:'mineral',ordinary_wood:'wood',spirit_plank:'wood',herb:'herb',sect_crop_13:'herb',sect_crop_14:'herb',sect_crop_01:'crop',sect_crop_15:'crop',spring_water:'crop',grain:'crop',meal_baicao_tongxuan_soup:'meal',beast_feed_refined:'feed',fish_feed_basic:'feed',sect_product_33:'animal',egg:'animal',thorn_boar_bone:'dungeon',red_copper_mine_material_01:'dungeon',mist_marsh_material_12:'dungeon',cold_jade_cave_material_12:'dungeon',sect_lining:'processed',cloth:'processed',insight:'other'};
 for(const [id,wanted]of Object.entries(cases))check(groups.warehouseCategoryFor(id,data.view.inventory[id])===wanted,'formal material '+id+' belongs to '+wanted);
 check(groups.warehouseCategories.length===12,'twelve warehouse groups');
 const expected=Object.entries(data.view.inventory).filter(([,row])=>row.quantity>0&&!['pill','equipment'].includes(row.category)).map(([id])=>id).sort();
 const partition=groups.warehouseCategories.filter(([id])=>id!=='all').flatMap(([id])=>inventory.inventoryRows(data.view,id).map(([key])=>key)).sort();
 check(JSON.stringify(expected)===JSON.stringify(partition),'all real material rows appear in exactly one broad group');
 for(const width of [320,390,430])for(const theme of ['LIGHT','DARK']){
  win.innerWidth=width;ctx.theme={mode:theme};ctx.ui={};let page=inventory.render(ctx);
  const filters=all(page).find(n=>n.className==='inventory-filters');check(filters.children.length===12,'four-by-three warehouse category controls '+width+'/'+theme);
  for(const [category,label]of groups.warehouseCategories){
   const chip=filters.children.find(n=>n.textContent===label);chip.emit('click');check(ctx.ui.inventoryCategory===category,'category click selects '+category);
   const next=inventory.render(ctx),actual=all(next).filter(n=>n.dataset.resourceId).map(n=>n.dataset.resourceId).sort();
   const wanted=category==='all'?expected:inventory.inventoryRows(data.view,category).map(([id])=>id).sort();
   check(JSON.stringify(actual)===JSON.stringify(wanted),'actual cards match '+label);
  }
  ctx.ui={inventoryCategory:'meal',inventorySearch:'百草通玄',inventorySort:'quantity'};page=inventory.render(ctx);
  check(all(page).filter(n=>n.dataset.resourceId).length===1,'category combines with search and sort');
  all(page).find(n=>n.dataset.resourceId==='meal_baicao_tongxuan_soup').emit('click');
  check(all(shown.content).some(n=>n.textContent==='灵膳'),'detail classification matches selected group');
  ctx.ui={inventoryCategory:'resource'};page=inventory.render(ctx);check(all(page).filter(n=>n.dataset.resourceId).length===expected.length,'retired generic resource selection safely falls back to all');
  const icons=all(page).filter(n=>n.classList?.contains('item-icon'));patch.patchPanel(page,inventory.render(ctx));check(icons.every(icon=>all(page).includes(icon)),'world refresh retains unchanged warehouse icons');
  ctx.ui={bagCategory:'pill'};page=inventory.render({...ctx,bag:true});
  check(all(page).find(n=>n.className==='inventory-filters').children.length===3,'bag has original three categories');
  check(all(page).filter(n=>n.dataset.resourceId).every(n=>data.view.inventory[n.dataset.resourceId].category==='pill'),'bag pill filtering preserved');
 }
 const rows=inventory.inventoryRows({inventory:{meal_zero:{name:'未获得灵膳',quantity:0,category:'resource'},future:{name:'将来材料',quantity:2,category:'resource'}}},'other');check(rows.length===1&&rows[0][0]==='future','unknown positive material goes to other; zero stocks remain hidden');
 check(JSON.stringify(data.view)===before&&commands.length===0,'classification, search, detail and refresh never mutate domain');
 const css=sources[base+'game.css'];check(css.includes('.warehouse-screen>.inventory-filters{grid-template-columns:repeat(4,minmax(0,1fr))}'),'only warehouse filters override to four columns');
 return {checks,status:'PASS',contexts:'320/390/430 LIGHT/DARK native DOM; phone painting pending'};
}

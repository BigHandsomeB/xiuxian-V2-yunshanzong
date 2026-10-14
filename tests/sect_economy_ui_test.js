// Run shipped native ES modules in a V8 isolate. DOM harness tests behavior,
// not Safari layout, painting, or device performance.
async function testSectEconomyUI(sources, fixture, realFetcher=null) {
 const assert=(v,m)=>{if(!v)throw Error(m);};const clone=v=>JSON.parse(JSON.stringify(v));let checks=0;
 const listeners=new Map(),timers=new Map(),fetches=[],storageValues=new Map();let serial=0;
 const store={getItem:k=>storageValues.get(k)||null,setItem:(k,v)=>storageValues.set(k,v),removeItem:k=>storageValues.delete(k)};
 const eventTarget=()=>({events:{},addEventListener(k,f){(this.events[k]??=[]).push(f);},removeEventListener(k,f){this.events[k]=(this.events[k]||[]).filter(x=>x!==f);},emit(k,e={}){for(const f of this.events[k]||[])f(e);}});
 let doc;
 function node(tag='div'){const n={...eventTarget(),tagName:tag.toUpperCase(),children:[],dataset:{},attrs:{},style:{},hidden:false,disabled:false,open:false,textContent:'',ownerDocument:doc,
 append(...children){for(const x of children){x.parentNode=this;this.children.push(x);}},replaceChildren(...children){this.children=[];this.append(...children);},remove(){if(this.parentNode)this.parentNode.children=this.parentNode.children.filter(x=>x!==this);},setAttribute(k,v){this.attrs[k]=String(v);},getAttribute(k){return this.attrs[k]??null;},removeAttribute(k){delete this.attrs[k];},focus(){this.focused=true;},showModal(){this.open=true;},close(){this.open=false;},getBoundingClientRect(){return {width:390,height:500,top:0,left:0,right:390,bottom:500};},querySelectorAll(selector){return all(this).filter(x=>selector==='[data-tab]'?!!x.dataset.tab:false);},set src(v){this.attrs.src=v;},get src(){return this.attrs.src;}};
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
 const ctx={data,ui:{},busy:false,route:{name:'building',id:'forge'},sheet:(title,content)=>shown={title,content},redraw(){},sync(){},economyAction:(name,payload)=>commands.push({name,payload}),cultivationAction:(name,payload)=>commands.push({name,payload})};
 const building=load(base+'screens/building.js'),cultivation=load(base+'screens/cultivation.js'),settings=load(base+'screens/settings.js'),patch=load(base+'components/patch.js');
 for(const width of [320,390,430])for(const theme of ['LIGHT','DARK']){
  win.innerWidth=width;ctx.theme={mode:theme,set(){}};
  const n=building.render(ctx),craft=all(n).filter(x=>x.dataset.craftEquipment);
  check(craft.length===12,`${width}/${theme}: all twelve craft choices`);
  const first=craft[0];check(!first.disabled,'funded craft available');first.emit('click');
  check(shown.title==='确认打造','craft confirmation sheet');all(shown.content).find(x=>x.textContent==='确认').emit('click');
  check(commands.at(-1).name==='equipment_craft'&&commands.at(-1).payload.equipment_id===first.dataset.craftEquipment,'craft submits definition identity');
  const grown=cultivation.render(ctx);check(all(grown).some(x=>x.textContent.includes('炼气 · 后期')),'derived stage rendered');check(all(grown).some(x=>x.textContent.includes('10%')),'stage percent rendered');
  const options=settings.render({...ctx,reloadAssets(){}}),toggle=all(options).find(x=>x.dataset.materialOverflow);check(!!toggle,'overflow setting rendered');toggle.emit('click');check(commands.at(-1).name==='material_overflow','setting uses authoritative command');
 }
 ctx.route.id='warehouse';let n=building.render(ctx);const upgrade=all(n).find(x=>x.dataset.buildingUpgrade);check(!!upgrade&&!upgrade.disabled,'funded warehouse upgrade available');upgrade.emit('click');check(shown.title==='确认升级','upgrade confirmation');all(shown.content).find(x=>x.textContent==='确认').emit('click');check(commands.at(-1).name==='building_upgrade','upgrade command');
 ctx.route.id='alchemy';n=building.render(ctx);check(all(n).some(x=>x.dataset.recipeId==='breakthrough_pill'),'new alchemy recipe choice');
 ctx.route.id='mountain';n=building.render(ctx);check(all(n).some(x=>x.dataset.recipeId==='stone'),'stone entry');
 ctx.route.id='forge';n=building.render(ctx);check(all(n).some(x=>x.dataset.recipeId==='ingot'),'smelting entry');
 const beforeIcons=all(n).filter(x=>x.classList?.contains('item-icon'));patch.patchPanel(n,building.render(ctx));check(beforeIcons.every(x=>all(n).includes(x)),'unchanged craft/recipe icons retained by patch');

 const features=load(base+'components/features.js'),equipment=load(base+'screens/equipment.js'),inventory=load(base+'screens/inventory.js'),economy=load(base+'screens/economy.js');
 for(const width of [320,390,430])for(const theme of ['LIGHT','DARK']){
  win.innerWidth=width;ctx.theme={mode:theme,set(){}};
  const grown=cultivation.render(ctx),quantity=all(grown).find(x=>x.className==='quantity-controls'),input=all(quantity).find(x=>x.type==='number'),submit=all(quantity).find(x=>x.textContent==='批量使用凝气丹');
  check(all(quantity).some(x=>x.textContent==='×1')&&all(quantity).some(x=>x.textContent==='×10'),'pill quantity shortcuts');all(quantity).find(x=>x.textContent==='×10').emit('click');check(input.value==='10'&&!submit.disabled,'ten selects valid quantity');submit.emit('click');all(shown.content).find(x=>x.textContent==='确认').emit('click');check(commands.at(-1).name==='cultivation_train'&&commands.at(-1).payload.count===10,'batch pill count reaches command');
  for(const invalid of ['0','-1','1.5','abc','99999']){input.value=invalid;input.emit('input');check(submit.disabled,'invalid batch quantity disabled');}
  input.value='3';input.emit('input');check(!submit.disabled,'custom positive quantity enabled');
  const bag=inventory.render({...ctx,bag:true,embedded:true,route:{name:'cultivation'}}),pillCell=all(bag).find(x=>x.dataset.resourceId==='pill');pillCell.emit('click');check(all(shown.content).some(x=>x.textContent==='批量使用凝气丹'),'backpack pill batch action');
  const open=equipment.batchEquipmentControls(ctx,'equipment_sell');check(!open.disabled,'batch equipment button');open.emit('click');const sale=shown.content,boxes=all(sale).filter(x=>x.type==='checkbox');check(boxes.length===12,'only eligible instances offered');boxes[0].checked=false;const amount=all(sale).find(x=>x.type==='number');amount.value='2';amount.emit('input');all(sale).find(x=>x.textContent==='批量出售').emit('click');check(shown.title==='确认批量出售','batch sale requires confirmation');all(shown.content).find(x=>x.textContent==='确认').emit('click');check(commands.at(-1).payload.instance_ids.length===2&&!commands.at(-1).payload.instance_ids.includes(ctx.data.view.equipment.instances[0].instance_id),'selection and count preserve instance identities');
  const workers=economy.workerControls({...ctx,data:{...ctx.data,view:{...ctx.data.view,disciples:{groups:[{name:'测试分组',instance_id:'cohort-test',available_count:20,assignments:[]}]}}}},'building-test');all(workers).find(x=>x.textContent==='安排工作弟子').emit('click');const workforce=shown.content;all(workforce).find(x=>x.textContent==='×10').emit('click');all(workforce).find(x=>x.textContent==='安排工作弟子').emit('click');check(commands.at(-1).name==='work_assign'&&commands.at(-1).payload.count===10,'workforce ten uses existing count command');
 }
 const pausedQuantity=features.quantityControls({...ctx,data:{...ctx.data,view:{...ctx.data.view,world:{paused:true}}}},{max:20,onSubmit(){}});check(all(pausedQuantity).filter(x=>x.tagName==='BUTTON').every(x=>!x.disabled),'pause allows instantaneous quantity actions');
 const originalData=ctx.data;
 const foundation=clone(originalData);foundation.view.cultivation={...foundation.view.cultivation,foundation:true,current_realm:'realm_1',realm_name:'筑基',progress:2000,threshold:6000,status:'FOUNDATION_TRAINING',next_realm:null,stage:{name:'中期',bonus_bps:800,next_progress:4000,remaining:2000},foundation_pills:[['pill_1_0','培元丹',30],['gu_yuan_pill','固元丹',60],['ju_yuan_pill','聚元丹',120],['ning_yuan_pill','凝元丹',240],['yang_yuan_pill','养元丹',480]].map(([item_id,name,gain])=>({item_id,name,gain,quantity:12,can_use:true,blocking_reasons:[]}))};
 for(const p of foundation.view.cultivation.foundation_pills)foundation.view.inventory[p.item_id]={name:p.name,quantity:p.quantity,category:'pill',tier:'待定'};
 foundation.view.sect_development={level:2,next:{level:3,building_count:4,building_level:5,current_building_count:2,cleared_floor:60,current_cleared_floor:30},unlocks:[{name:'灵品配方',level:2,unlocked:true}]};
 ctx.data=foundation;
 for(const width of [320,390,430])for(const theme of ['LIGHT','DARK']){
  win.innerWidth=width;ctx.theme={mode:theme,set(){}};
  const grown=cultivation.render(ctx);check(all(grown).some(x=>x.textContent==='筑基修为'),'foundation progress label');check(all(grown).some(x=>x.textContent==='2000 / 6000'),'foundation real progress');check(all(grown).some(x=>x.textContent.includes('8%')),'foundation bonus shown');check(all(grown).filter(x=>x.dataset.usePill).length===5,'five foundation choices');
  all(grown).find(x=>x.dataset.usePill==='gu_yuan_pill').emit('click');check(commands.at(-1).name==='cultivation_use_pill'&&commands.at(-1).payload.item_id==='gu_yuan_pill','single foundation command carries item id');
  const bag=inventory.render({...ctx,bag:true,embedded:true,route:{name:'cultivation'}});all(bag).find(x=>x.dataset.resourceId==='ju_yuan_pill'&&x.tagName==='BUTTON').emit('click');check(all(shown.content).some(x=>x.dataset.usePill==='ju_yuan_pill'),'backpack foundation pill entry');check(all(shown.content).some(x=>x.textContent==='品阶：待定'),'unknown tier honestly shown');
  ctx.route.id='hall';const hall=building.render(ctx);check(all(hall).some(x=>x.textContent==='宗门等级 2'),'sect rank shown');check(all(hall).some(x=>x.textContent.includes('2 / 4')),'building count progress');check(all(hall).some(x=>x.textContent.includes('30 / 60')),'floor progress');
  const icons=all(grown).filter(x=>x.classList?.contains('item-icon'));patch.patchPanel(grown,cultivation.render(ctx));check(icons.every(x=>all(grown).includes(x)),'foundation unchanged icons retained');
 }
 foundation.view.world.paused=true;
 const pausedFoundation=cultivation.render(ctx);check(all(pausedFoundation).filter(x=>x.dataset.usePill).every(x=>!x.disabled),'paused foundation pill actions allowed by unchanged read model');
 ctx.data=originalData;ctx.route.id='forge';
 ctx.busy=true;n=building.render(ctx);check(all(n).filter(x=>x.dataset.craftEquipment).every(x=>x.disabled),'busy craft disabled');
 const {GameClient}=load(base+'api-client.js');
 const batchClient=new GameClient({fetcher:fetch,storage:store,uuid:()=>`00000000-0000-4000-8000-${String(++serial).padStart(12,'0')}`});await batchClient.cultivation('cultivation_train',{count:10});check(fetches.filter(r=>r.body?.command?.name==='cultivation_train').at(-1).body.command.payload.count===10,'client preserves batch pill payload');await batchClient.economy('equipment_sell',{instance_ids:['item-a','item-b']});check(fetches.filter(r=>r.body?.command?.name==='equipment_sell').at(-1).body.command.payload.instance_ids.length===2,'client preserves batch equipment instances');
 await batchClient.cultivation('cultivation_use_pill',{item_id:'gu_yuan_pill',count:2});check(fetches.filter(r=>r.body?.command?.name==='cultivation_use_pill').at(-1).body.command.payload.count===2,'foundation client whitelist and count preserved');
 for(const name of ['material_overflow','building_upgrade','equipment_craft']){const client=new GameClient({fetcher:fetch,storage:store});let entered=false;client.lock=async()=>{entered=true;return null;};await client.economy(name,{});check(entered,`${name} accepted by client whitelist`);}
 return {tests:checks,status:'PASS',scope:'shipped modules and DOM, six width/theme contexts; not screenshot or device validation'};
}

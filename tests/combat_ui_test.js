// Native module/DOM + optional isolated real WSGI fetch harness. Not device acceptance.
async function testCombatUI(sources,fixture,realFetcher=null){
 let checks=0;const assert=(v,m)=>{if(!v)throw Error(m);checks++;},clone=v=>JSON.parse(JSON.stringify(v)),base='src/ui/pages/game/static/';
 const events=new Map(),raf=new Map(),observers=[],timers=new Map(),requests=[],values=new Map();let serial=0,doc;
 const target=()=>({listeners:{},addEventListener(k,f){(this.listeners[k]??=[]).push(f);},removeEventListener(k,f){this.listeners[k]=(this.listeners[k]||[]).filter(x=>x!==f);},emit(k,event={}){for(const f of this.listeners[k]||[])f(event);}});
 function node(tag='div'){const n={...target(),ownerDocument:doc,tagName:tag.toUpperCase(),children:[],style:{},attrs:{},dataset:{},hidden:false,disabled:false,open:false,textContent:'',append(...ns){for(const x of ns){x.parentNode=this;this.children.push(x);}},replaceChildren(...ns){for(const x of this.children)x.parentNode=null;this.children=[];this.append(...ns);},remove(){if(this.parentNode)this.parentNode.children=this.parentNode.children.filter(x=>x!==this);},setAttribute(k,v){this.attrs[k]=String(v);if(k.startsWith('data-'))this.dataset[k.slice(5)]=String(v);},getAttribute(k){return this.attrs[k]??null;},removeAttribute(k){delete this.attrs[k];},set src(v){this.attrs.src=v;},get src(){return this.attrs.src;},getBoundingClientRect(){return {width:390,height:350,top:0,left:0,right:390,bottom:350};},close(){this.open=false;}};n.classList={add(k){n.className=(n.className||'')+' '+k;},contains(k){return (n.className||'').split(' ').includes(k);}};return n;}
 const media={...target(),matches:false},win={...target(),innerWidth:390,innerHeight:844,matchMedia:()=>media,requestAnimationFrame:f=>{raf.set(++serial,f);return serial;},cancelAnimationFrame:id=>raf.delete(id),IntersectionObserver:class{constructor(f){this.f=f;observers.push(this);}observe(){}disconnect(){this.disconnected=true;}}};
 const sheet=node('dialog');doc={...target(),hidden:false,defaultView:win,createElement:tag=>node(tag),getElementById:()=>sheet};sheet.ownerDocument=doc;
 const globals={document:doc,setTimeout:(f,ms)=>{timers.set(++serial,{f,ms});return serial;},clearTimeout:id=>timers.delete(id)},modules=new Map();
 function load(path){if(modules.has(path))return modules.get(path);let source=sources[path];if(source===undefined)throw Error('Missing '+path);const imports={};source=source.replace(/^import\s+(.+?)\s+from\s+['"](.+?)['"];?\s*$/gm,(_,bindings,name)=>{let parts=path.split('/');parts.pop();for(const p of name.split('/'))if(p==='..')parts.pop();else if(p!=='.')parts.push(p);const dependency=load(parts.join('/'));for(const item of bindings.replace(/[{}]/g,'').split(',')){const [k,a]=item.trim().split(/\s+as\s+/);imports[a||k]=dependency[k];}return '';});const exported=[...source.matchAll(/export\s+(?:async\s+)?(?:function|class|const)\s+(\w+)/g)].map(m=>m[1]);source=source.replace(/export\s+/g,'');const args={...globals,...imports},result=new Function(...Object.keys(args),source+`;return {${exported.join(',')}};`)(...Object.values(args));modules.set(path,result);return result;}
 function all(n){return [n,...n.children.flatMap(all)];}
 const {GameClient}=load(base+'api-client.js'),storage={getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)};
 const fetcher=async(url,options={})=>{requests.push({url,options});return realFetcher?realFetcher(url,options):{ok:true,status:200,json:async()=>clone(fixture)};};
 const client=new GameClient({fetcher,storage,uuid:()=>`00000000-0000-4000-8000-${String(++serial).padStart(12,'0')}`});client.current=clone(fixture);
 let data=clone(fixture),controller,root,shown;
 const context={data,busy:false,route:{name:'battle'},combatReceipt:null,sheet(title,content){shown=content;sheet.open=true;},combatAction:async(name,payload)=>{context.busy=true;controller.update(data,true,client.combatReceipt);try{data=await client.combat(name,payload);}finally{context.busy=false;controller.update(data,false,client.combatReceipt);}}};
 const screen=load(base+'screens/battle.js');root=screen.render(context);controller=context.afterMount();
 const main=all(root).find(n=>n.id==='combat-primary'),hp=()=>all(root).filter(n=>n.attrs.role==='progressbar'),actor=role=>all(root).find(n=>n.attrs['data-role']===role),drain=()=>{for(const [id,t]of [...timers].sort((a,b)=>a[1].ms-b[1].ms)){if(timers.has(id)){timers.delete(id);t.f();}}};
 assert(hp().length===2&&hp()[0].attrs['aria-valuenow']==='80'&&hp()[1].attrs['aria-valuenow']==='35','True Battle View HP renders');
 assert(main.textContent==='进入试炼'&&!main.disabled,'Ready start control');
 assert(actor('player').children.some(n=>n.className.includes('battle-placeholder')&&!n.hidden),'Player fallback renders');
 assert(actor('enemy').children.some(n=>n.className.includes('battle-placeholder')&&!n.hidden),'Monster fallback renders');
 assert(all(root).some(n=>n.className==='battle-landscape'),'Missing background fallback');
 assert(all(root).filter(n=>n.className?.includes('battle-layer--')).length===5,'Reuse five scene layers');
 const scene=all(root).find(n=>n.className==='battle-scene'),background=scene.children[0],originalActor=actor('player');
 if(realFetcher){
  await main.listeners.click[0]();assert(data.view.combat.status==='ACTIVE','UI start reaches real Domain');assert(main.textContent==='基础攻击','Actual attack available');
  let release;const saved=client.fetcher;client.fetcher=async(...args)=>{await new Promise(r=>release=r);return saved(...args);};
  const pending=main.listeners.click[0]();assert(main.disabled,'Pending attack disables touch button');main.listeners.click[0]();assert(client.active,'Serialized command');for(let i=0;i<20&&!release;i++)await Promise.resolve();client.fetcher=saved;release();await pending;
  assert(hp()[0].attrs['aria-valuenow']==='74.5'&&hp()[1].attrs['aria-valuenow']==='25','Both true HP update from HTTP');
  assert(all(root).find(n=>n.className==='battle-scene')===scene&&scene.children[0]===background&&actor('player')===originalActor,'Scene/background/actors stable across attack');
  drain();assert(actor('player').attrs['data-action']==='idle'&&actor('enemy').attrs['data-action']==='idle','Presentation returns surviving actors to idle');
  for(let i=0;i<3;i++)await main.listeners.click[0]();drain();
  assert(data.view.combat.status==='PLAYER_WIN'&&hp()[1].attrs['aria-valuenow']==='0','Win real enemy death HP clamp');assert(actor('enemy').attrs['data-action']==='death','Death animation selected');
  assert(main.textContent==='领取战利品'&&all(root).some(n=>n.textContent==='待领取战利品'),'Win completion and reward view');
  await main.listeners.click[0]();assert(data.view.combat.reward_state==='SETTLED','UI reward settled');assert(data.view.holdings.coins.quantity===3&&data.view.holdings.dewleaf.quantity===1,'UI HTTP actual Inventory reward');
  const id=data.view.combat.battle_id,q={battle_id:id};await context.combatAction('combat_reward',q);assert(data.view.holdings.dewleaf.quantity===1,'Repeated reward request cannot duplicate');
  await main.listeners.click[0]();assert(data.view.combat.status==='ACTIVE'&&data.view.combat.battle_id!==id,'Restart challenge after settled battle');assert(actor('enemy').attrs['data-action']==='idle','New battle resets dead monster presentation');
  await main.listeners.click[0]();const before=clone(data.view.combat);controller();
  data=await client.read();context.data=data;context.combatReceipt=client.combatReceipt;root=screen.render(context);controller=context.afterMount();assert(JSON.stringify(data.view.combat)===JSON.stringify(before),'Leaving/return restores current true HP and revision');
  const quit=all(root).find(n=>n.id==='combat-abandon');quit.listeners.click[0]();assert(sheet.open&&shown,'Abandon confirmation sheet');await all(shown).find(n=>n.tagName==='BUTTON').listeners.click[0]();
  assert(data.view.combat.status==='ABANDONED'&&!sheet.open,'Abandon real flow ends battle without reward');assert(data.view.holdings.coins.quantity===3,'Abandon does not grant');
 }
 // Semantic animation selection; read supplied facts, never recompute their amounts.
 const {presentEvents}=load(base+'battle/presentation.js'),selected=[],numbers=[];
 const view={battle_id:'facts',step:1,player:{hp:0},enemy:{hp:0},latest_events:[{kind:'player_attack',actor:'player'},{kind:'enemy_hit',target:'enemy'},{kind:'enemy_attack',actor:'enemy'},{kind:'player_hit',target:'player'},{kind:'damage',target:'enemy',damage:123.5},{kind:'enemy_defeated',target:'enemy'},{kind:'player_defeated',target:'player'}]};
 const clear=presentEvents({play:(role,action)=>selected.push(role+':'+action),feedback:e=>numbers.push(e.damage)},view,{});drain();
 for(const key of ['player:attack','enemy:hit','enemy:attack','player:hit','enemy:death','player:death'])assert(selected.includes(key),'Semantic animation '+key);
 assert(numbers[0]===123.5,'Damage feedback uses server fact even unusual amount; missing Effect safe');clear();
 const lose=clone(data);lose.view.combat={...clone(fixture.view.combat),status:'PLAYER_LOSE',available_commands:['combat_start'],player:{...fixture.view.combat.player,hp:0},reward:[],latest_events:[]};controller.update(lose,false,null);
 assert(all(root).some(n=>n.textContent==='力竭败退'),'Lose result screen');
 controller();assert(!raf.size&&observers.every(o=>o.disconnected)&&!timers.size,'Leaving battle stops RAF, observers and presentation timers');
 assert(!/Math\.random|attack_milli|armor_milli|damage\s*=/.test(sources[base+'battle/presentation.js']+sources[base+'screens/battle.js']),'Presentation has no damage authority');
 return {tests:checks,status:'PASS',realHTTP:!!realFetcher};
}

// Run shipped native ES modules in a V8 isolate. DOM harness tests behavior,
// not Safari layout, painting, or device performance.
async function testExpeditionUI(sources, fixture, realFetcher=null) {
 const assert=(v,m)=>{if(!v)throw Error(m);};const clone=v=>JSON.parse(JSON.stringify(v));let checks=0;
 const listeners=new Map(),timers=new Map(),fetches=[],storageValues=new Map();let serial=0;
 const store={getItem:k=>storageValues.get(k)||null,setItem:(k,v)=>storageValues.set(k,v),removeItem:k=>storageValues.delete(k)};
 const eventTarget=()=>({events:{},addEventListener(k,f){(this.events[k]??=[]).push(f);},removeEventListener(k,f){this.events[k]=(this.events[k]||[]).filter(x=>x!==f);},emit(k,e={}){for(const f of this.events[k]||[])f(e);}});
 let doc;
 function node(tag='div'){const n={...eventTarget(),tagName:tag.toUpperCase(),children:[],dataset:{},attrs:{},style:{},hidden:false,disabled:false,open:false,textContent:'',ownerDocument:doc,
 append(...children){for(const x of children){x.parentNode=this;this.children.push(x);}},prepend(...children){for(const x of children)x.parentNode=this;this.children.unshift(...children);},replaceChildren(...children){this.children=[];this.append(...children);},remove(){if(this.parentNode)this.parentNode.children=this.parentNode.children.filter(x=>x!==this);},setAttribute(k,v){this.attrs[k]=String(v);},getAttribute(k){return this.attrs[k]??null;},removeAttribute(k){delete this.attrs[k];},focus(){this.focused=true;},showModal(){this.open=true;},close(){this.open=false;},getBoundingClientRect(){return {width:390,height:500,top:0,left:0,right:390,bottom:500};},querySelectorAll(selector){return all(this).filter(x=>selector==='img[data-pending-icon-src]'?x.tagName==='IMG'&&x.dataset.pendingIconSrc:selector==='[data-tab]'?!!x.dataset.tab:selector==='button,a,h2,summary,label'?['BUTTON','A','H2','SUMMARY','LABEL'].includes(x.tagName):false);},querySelector(selector){return selector==='span'?this.children.find(x=>x.tagName==='SPAN'):all(this).find(x=>selector.startsWith('.')&&x.classList.contains(selector.slice(1)))||null;},set src(v){this.attrs.src=v;},get src(){return this.attrs.src;}};
 n.classList={add(k){n.className=(n.className||'')+' '+k;},contains(k){return (n.className||'').split(' ').includes(k);},remove(k){n.className=(n.className||'').split(' ').filter(x=>x!==k).join(' ');}};return n;}
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

 const data=load(base+'adapters.js').gameView(fixture),commands=[];
 const ctx={data,ui:{},busy:false,route:{name:'adventure'},sheet(){},redraw(){},combatAction:async(name,payload)=>{commands.push({name,payload});return {view:{combat:{dungeon:{id:payload.dungeon_id}}}};}};
 const adventure=load(base+'screens/adventure.js'),battle=load(base+'screens/battle.js'),patch=load(base+'components/patch.js');
 for(const width of [320,390,430])for(const theme of ['LIGHT','DARK']){
  win.innerWidth=width;ctx.theme={mode:theme};location.hash='';
  let n=adventure.render(ctx),cards=all(n).filter(x=>x.dataset.dungeonId);check(cards.length===10,'all planned dungeon cards remain');
  const mine=cards.find(x=>x.dataset.dungeonId==='red_copper_mine');check(mine.tagName==='A','second dungeon unlocked after thorn100');
  await mine.events.click[0]({preventDefault(){}});check(commands.at(-1).name==='dungeon_select'&&commands.at(-1).payload.dungeon_id==='red_copper_mine','selection authoritative id');check(location.hash==='#battle','navigation follows successful selection');
  const swamp=cards.find(x=>x.dataset.dungeonId==='mist_marsh');check(swamp.tagName==='ARTICLE'&&all(swamp).some(x=>x.textContent==='需通关赤铜废矿100层'),'third dungeon locked with explicit condition');
  if(ctx.data.view.combat.dungeons.some(d=>d.id==='cold_jade_cave')){
   const cold=cards.find(x=>x.dataset.dungeonId==='cold_jade_cave');check(cold.tagName==='ARTICLE'&&all(cold).some(x=>x.textContent==='需通关雾隐灵泽100层'),'fourth dungeon uses real previous-dungeon gate');check(!all(cold).some(x=>x.textContent==='尚未开放'),'registered fourth dungeon is no longer an upcoming placeholder');
   const saved=ctx.data;ctx.data=clone(saved);ctx.data.view.combat.dungeons.find(d=>d.id==='cold_jade_cave').unlocked=true;ctx.data.view.combat.dungeons.find(d=>d.id==='mist_marsh').cleared_floor=100;
   const open=all(adventure.render(ctx)).find(x=>x.dataset.dungeonId==='cold_jade_cave');check(open.tagName==='A','fourth dungeon unlocked after third100');await open.events.click[0]({preventDefault(){}});check(commands.at(-1).payload.dungeon_id==='cold_jade_cave'&&location.hash==='#battle','fourth selection follows server response');
   ctx.data.view.combat.dungeon={...ctx.data.view.combat.dungeons.find(d=>d.id==='cold_jade_cave'),cleared_floor:2};ctx.data.view.combat.encounter.name='寒玉冰窟 · 第3层';check(all(battle.render(ctx)).some(x=>x.textContent.includes('寒玉冰窟 · 已通关 2 / 100')),'fourth battle progress uses server facts');
   ctx.data=saved;
  }
  {
   const saved=ctx.data,oldAction=ctx.combatAction,oldSheet=ctx.sheet;let shown=null,fail=true;
   ctx.data=clone(saved);const v=ctx.data.view.combat;v.status='PLAYER_WIN';v.battle_id='pending-exit-battle';v.available_commands=['combat_reward','combat_abandon'];v.reward_state='READY';v.auto.enabled=false;v.auto.reason='STORAGE_FULL';v.enemy.hp=0;
   ctx.sheet=(title,content)=>{shown=content;};ctx.combatAction=async(name,payload)=>{commands.push({name,payload});return {view:{combat:{status:fail?'PLAYER_WIN':'ABANDONED',battle_id:payload.battle_id}}};};location.hash='';
   const winning=battle.render(ctx),main=all(winning).find(x=>x.id==='combat-primary'),exit=all(winning).find(x=>x.id==='combat-abandon');load(base+'components/approved-controls.js').decorateControls(winning,ctx.data);
   check(!exit.hidden&&!exit.disabled,'victory pending reward has enabled exit');check(main.dataset.controlIcon==='none'&&!all(main).some(x=>x.classList.contains('system-icon')),'claim button has no leading icon after production decoration');
   check(all(winning).some(x=>x.textContent.includes('退出战斗丢弃本场战利品')),'full storage message offers explicit discard');const before=commands.length;exit.events.click[0]();check(shown&&all(shown).some(x=>x.textContent.includes('丢弃本场未领取')),'exit asks to discard only this pending loot');check(commands.length===before,'opening exit confirmation does not discard');
   await all(shown).find(x=>x.tagName==='BUTTON').events.click[0]();check(location.hash==='','failed exit remains in battle');fail=false;exit.events.click[0]();await all(shown).find(x=>x.tagName==='BUTTON').events.click[0]();check(commands.at(-1).name==='combat_abandon'&&commands.at(-1).payload.battle_id==='pending-exit-battle','confirmed exit targets exact server battle');check(location.hash==='#adventure','successful exit returns to adventure');
   ctx.data=saved;ctx.combatAction=oldAction;ctx.sheet=oldSheet;
  }
  const icons=all(n).filter(x=>x.classList.contains('item-icon'));patch.patchPanel(n,adventure.render(ctx));check(icons.every(x=>all(n).includes(x)),'unchanged adventure icons retained');
  const selected=clone(ctx.data);selected.view.combat.dungeon={...selected.view.combat.dungeon,id:'red_copper_mine',name:'赤铜废矿',cleared_floor:17,total_floors:100};selected.view.combat.encounter.name='赤铜废矿 · 第18层';ctx.data=selected;
  const panel=battle.render(ctx);check(all(panel).some(x=>x.textContent.includes('赤铜废矿 · 已通关 17 / 100')),'battle consumes selected dungeon name/progress');check(!all(panel).some(x=>x.textContent.includes('荆棘古道 · 已通关')),'no hardcoded thorn progress');
  ctx.data=clone(data);ctx.data.view.world.paused=true;n=adventure.render(ctx);check(all(n).find(x=>x.dataset.dungeonId==='red_copper_mine').tagName==='ARTICLE','paused view cannot select new dungeon');
  ctx.data=clone(data);ctx.data.view.combat.auto.enabled=true;n=adventure.render(ctx);check(all(n).find(x=>x.dataset.dungeonId==='red_copper_mine').tagName==='ARTICLE','auto must stop before switching');
  ctx.data=clone(data);ctx.data.view.combat.status='PLAYER_WIN';n=adventure.render(ctx);check(all(n).find(x=>x.dataset.dungeonId==='red_copper_mine').tagName==='ARTICLE','unclaimed victory prevents switch');
  ctx.data=clone(data);
 }
 const {GameClient}=load(base+'api-client.js');
 const client=new GameClient({fetcher:fetch,storage:store,uuid:()=>`00000000-0000-4000-8000-${String(++serial).padStart(12,'0')}`});await client.combat('dungeon_select',{dungeon_id:'red_copper_mine'});check(fetches.some(r=>r.body?.command?.name==='dungeon_select'&&r.body.command.payload.dungeon_id==='red_copper_mine'),'client supports selection command');
 // Compile production modules without running the game bootstrap.
 for(const path of [base+'game.js',base+'screens/adventure.js',base+'screens/battle.js']){const source=sources[path].replace(/^import.*from.*;\s*$/gm,'').replace(/export\s+/g,'');new Function(source);check(true,'module syntax '+path);}
 return {tests:checks,status:'PASS',deviceAcceptance:false};
}

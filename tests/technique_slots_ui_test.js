// Run shipped native ES modules in a V8 isolate. DOM harness tests behavior,
// not Safari layout, painting, or device performance.
async function testTechniqueSlotsUI(sources,fixture,styles) {
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

 const module=load(base+'components/technique-slots.js'),cultivation=load(base+'screens/cultivation.js'),patch=load(base+'components/patch.js');
 const rules=module.techniqueRules;
 check(!rules.system_open&&rules.character_kill_xp_requires_equipped&&!rules.meditation_open,'gate reserved until techniques open');
 check(rules.grades.map(row=>row.max_level).join(',')==='10,15,20,25,30,40','six level caps');
 check(rules.grades.map(row=>row.id).join(',')==='white,green,blue,purple,orange,red','six grade identities');
 const ctx={data:fixture,ui:{},busy:false,sheet(){throw Error('closed slot must not open sheet');},cultivationAction(){throw Error('no gameplay changes');}};
 for(const width of [320,390,430])for(const theme of ['LIGHT','DARK']){
  win.innerWidth=width;ctx.theme={mode:theme};const page=cultivation.render(ctx);
  const grid=all(page).find(n=>n.className==='technique-grid');
  check(grid?.children.length===8,width+'/'+theme+': eight cards');
  check(grid.children.map(n=>n.dataset.slot).join(',')===rules.slots.map(s=>'technique:'+s.id).join(','),'slot types and order');
  check(grid.children.every(n=>n.tagName==='DIV'&&n.getAttribute('aria-disabled')==='true'),'reserved slots cannot mutate');
  check(all(grid).filter(n=>n.textContent==='Lv —').length===8,'no invented skill levels');
  const loadout=page.children.findIndex(n=>n.className==='cultivation-loadout');check(page.children[loadout+1].className==='technique-slots','slots immediately below equipment area');
  check(all(page).some(n=>n.className==='panel growth-milestone'),'compact milestone class');
  const cards=[...grid.children];patch.patchPanel(page,cultivation.render(ctx));
  check(cards.every(n=>all(page).includes(n)),'stable cards survive refresh');
 }
 check(styles.game.includes('.technique-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px}'),'four columns at all widths');
 check(styles.game.includes('.growth-progress progress{grid-column:1/-1;width:100%;height:8px;'),'compact eight-pixel bar');
 check(styles.game.includes('.growth-milestone h2,.growth-milestone p{font-size:var(--text-help);margin:0}'),'compact milestone typography');
 for(const id of rules.grades.map(g=>g.id)){
  check((styles.theme.match(new RegExp('--technique-'+id+':','g'))||[]).length===2,'grade token exists in both themes: '+id);
  check(styles.game.includes('[data-grade='+id+']{color:var(--technique-'+id+')}'),'semantic grade color: '+id);
 }
 return {tests:checks,status:'PASS',scope:'actual cultivation DOM in six width/theme contexts; no device painting'};
}

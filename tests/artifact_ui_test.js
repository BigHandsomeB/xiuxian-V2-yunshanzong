// Run shipped native ES modules in a V8 isolate. DOM harness tests behavior,
// not Safari layout, painting, or device performance.
async function testArtifactUI(sources, fixture, realFetcher=null) {
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
 const ctx={data,ui:{},busy:false,route:{name:'building',id:'forge'},sheet:(title,content)=>shown={title,content},redraw(){},sync(){},economyAction:(name,payload)=>commands.push({name,payload})};
 const screen=load(base+'screens/artifacts.js'),patch=load(base+'components/patch.js');
 const click=(tree,text)=>{const b=all(tree).find(n=>n.tagName==='BUTTON'&&n.textContent===text);check(!!b,'button '+text);check(!b.disabled,'enabled '+text);b.emit('click');};
 for(const width of [320,390,430])for(const theme of ['LIGHT','DARK']){
  win.innerWidth=width;ctx.theme={mode:theme,set(){}};
  const node=screen.renderArtifactLibrary(ctx);
  check(all(node).filter(n=>n.dataset.id?.startsWith('artifact-')&&n.dataset.id!=='artifact-library').length===5,width+'/'+theme+' catalog from server');
  const sword=all(node).find(n=>n.dataset.id==='artifact-slayer_sword');sword.emit('click');
  check(shown.title==='斩妖飞剑','owned artifact detail');
  click(shown.content,'卸下法宝');check(commands.at(-1).name==='artifact_unequip','unequip command');
  click(shown.content,'强化至 +1');click(shown.content,'确认');check(commands.at(-1).name==='artifact_enhance','enhance confirmation command');
  sword.emit('click');const select=all(shown.content).find(n=>n.tagName==='SELECT');select.value='beast_bone';select.emit('change');
  click(shown.content,'投喂材料');click(shown.content,'确认');check(commands.at(-1).name==='artifact_feed'&&commands.at(-1).payload.quantity===1,'feed quantity exact');
  ctx.busy=true;const busy=screen.renderArtifactLibrary(ctx);all(busy).find(n=>n.dataset.id==='artifact-slayer_sword').emit('click');check(all(shown.content).filter(n=>n.tagName==='BUTTON').every(n=>n.disabled),'busy actions disabled');ctx.busy=false;
  ctx.ui.forge={tab:'artifacts'};const forge=load(base+'building-adapters.js').adapterFor('forge').render(ctx);check(all(forge).some(n=>n.dataset.id==='artifact-library'),'artifact page inside forge');
  patch.patchPanel(node,screen.renderArtifactLibrary(ctx));check(all(node).some(n=>n===sword),'unchanged artifact card retained');
 }
 const retained=all(screen.renderArtifactLibrary(ctx)).find(n=>n.dataset.id==='artifact-slayer_sword');
 const old=data.view.artifacts;delete data.view.artifacts;check(all(screen.renderArtifactLibrary(ctx)).some(n=>n.textContent==='法宝尚未开放'),'historical view has honest fallback');data.view.artifacts=old;
 check(commands.every(c=>!c.name.includes('upgrade')),'UI cannot migrate content');
 return {checks};
}

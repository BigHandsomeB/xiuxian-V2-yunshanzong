// Run shipped native ES modules in a V8 isolate. DOM harness tests behavior,
// not Safari layout, painting, or device performance.
async function testCatalogNotesUI(sources,fixture,styles) {
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


 const responses=[];globals.fetch=async(url,options={})=>{fetches.push({url,payload:options.body?JSON.parse(options.body):null});return responses.shift();};
 const notes=load(base+'components/catalog-notes.js'),screen=load(base+'screens/catalog.js'),patch=load(base+'components/patch.js');
 for(const width of [320,390,430])for(const theme of ['LIGHT','DARK']){
  win.innerWidth=width;let sheet;const row={asset_id:'icon.test',name:'测试素材',annotation:{},visual:{asset:{url:'/image.png'}},gameplay_status:'已登记',planned_grade:'白阶',manual_function:'用于身法槽'},group={set_id:'manual-test',name:'功法',category:'manual',items:[row]},ctx={ui:{catalogCategory:'manual'},busy:false,data:{csrf:'isolated-csrf',assetManifest:{catalog:{available:true,groups:[group]}}},sheet(t,b){sheet=b;},redraw(){},reloadAssets(){}};
  const page=screen.render(ctx),summary=all(page).find(n=>n.className==='catalog-notes-summary');check(summary.children.length===3,'three fields under icon');check(all(page).some(n=>n.textContent==='功法'),'manual filter');
  const image=all(page).find(n=>n.tagName==='IMG');patch.patchPanel(page,screen.render(ctx));check(all(page).includes(image),'summary refresh retains art');
  all(page).find(n=>n.dataset.catalogAsset==='icon.test').emit('click');const editor=all(sheet).find(n=>n.className==='catalog-notes-editor'),fields=all(editor).filter(n=>['INPUT','TEXTAREA'].includes(n.tagName));
  check(fields.length===3,'three editable fields');fields[1].value='兑换功法';fields[1].emit('input');fields[2].value='<script>纯文本</script>';fields[2].emit('input');
  const again=notes.notesEditor(ctx,row,group);check(all(again).find(n=>n.getAttribute('aria-label')==='备注').value==='<script>纯文本</script>','draft survives rebuilding');
  responses.push({ok:true,json:async()=>({entry:{grade:'白阶',function:'兑换功法',note:'<script>纯文本</script>',revision:1}})});
  const save=all(editor).find(n=>n.textContent==='保存说明'),start=fetches.length,first=save.__onClick(),duplicate=save.__onClick();await Promise.all([first,duplicate]);check(fetches.length===start+1,'single save flight');check(fetches.at(-1).payload.expected_revision===0,'optimistic note revision');check(row.annotation.note==='<script>纯文本</script>','saved as literal text');
  const refreshed=notes.notesSummary(row,group);check(refreshed.children[2].title==='<script>纯文本</script>','summary literal escaped text');
  fields[2].value='未提交草稿';fields[2].emit('input');responses.push({ok:false,json:async()=>({message:'版本已变化'})});await save.__onClick();check(ctx.ui.catalogNoteDrafts['icon.test'].note==='未提交草稿','conflict preserves draft');
  responses.push({ok:true,json:async()=>({presentation:{catalog:{groups:[{items:[{...row,annotation:{grade:'绿阶',function:'新版功能',note:'他处编辑',revision:2}}]}]}}})});await all(editor).find(n=>n.textContent==='读取已保存说明').__onClick();check(fields[2].value==='他处编辑'&&ctx.ui.catalogNoteDrafts['icon.test'].revision===2,'explicit read resolves conflict');
 }
 return {checks,device_visual_verified:false};
}

// Native DOM regression checks, not a browser/network or phone acceptance claim.
export function testIconStability(sources){
 let checks=0,loads=0;const check=(value,message)=>{if(!value)throw Error(message);checks++;};
 let doc;function node(tag){let content='';const n={tagName:tag.toUpperCase(),nodeType:1,children:[],dataset:{},attrs:{},events:{},className:'',ownerDocument:doc,
 get childNodes(){return this.children;},get textContent(){return content||this.children.map(x=>x.textContent).join('');},set textContent(value){content=String(value);this.children=[];},
 append(...nodes){for(const x of nodes){x.remove();x.parentNode=this;this.children.push(x);}},insertBefore(x,before){x.remove();x.parentNode=this;const i=before?this.children.indexOf(before):this.children.length;this.children.splice(i,0,x);},
 replaceChildren(...nodes){for(const x of this.children)x.parentNode=null;this.children=[];this.append(...nodes);},remove(){if(this.parentNode){this.parentNode.children=this.parentNode.children.filter(x=>x!==this);this.parentNode=null;}},
 addEventListener(type,f){(this.events[type]??=[]).push(f);},emit(type){for(const f of this.events[type]||[])f({type});},
 getAttributeNames(){return Object.keys(this.attrs);},getAttribute(k){return this.attrs[k]??null;},setAttribute(k,v){if(k==='src')loads++;this.attrs[k]=String(v);},removeAttribute(k){delete this.attrs[k];},
 get src(){return this.attrs.src;},set src(v){this.setAttribute('src',v);},querySelectorAll(selector){const all=this.children.flatMap(x=>[x,...x.querySelectorAll('*')]);return selector==='*'?all:all.filter(x=>x.tagName==='IMG'&&x.dataset.pendingIconSrc);}};
 n.classList={contains:c=>n.className.split(' ').includes(c),add:c=>{n.className+=' '+c;}};return n;}
 doc={createElement:node,activeElement:null};const base='src/ui/pages/game/static/',modules=new Map();
 function load(path){if(modules.has(path))return modules.get(path);let code=sources[path],imports={};code=code.replace(/^import\s+\{([^}]+)\}\s+from\s+['"](.+)['"];?\s*$/gm,(_,names,target)=>{let parts=path.split('/');parts.pop();for(const part of target.split('/'))if(part==='..')parts.pop();else if(part!=='.')parts.push(part);const m=load(parts.join('/'));for(const name of names.split(','))imports[name.trim()]=m[name.trim()];return '';});const names=[...code.matchAll(/export (?:function|const) (\w+)/g)].map(x=>x[1]);const m=new Function('document',...Object.keys(imports),code.replace(/^export /gm,'')+`;return {${names.join(',')}};`)(doc,...Object.values(imports));modules.set(path,m);return m;}
 const {itemIcon}=load(base+'components/item-icon.js'),{patchPanel}=load(base+'components/patch.js'),{deferIconLoads,activateIconLoads}=load(base+'components/icon-loading.js');
 const icon=(quantity=1,quality='green',locked=false,url='/game/runtime/test/'+'a'.repeat(64))=>itemIcon({asset_id:'test',asset:{url},quantity,quality,locked});
 let old=icon(),image=old.children.find(n=>n.tagName==='IMG');check(old.classList.contains('quality-uncommon'),'Service green maps to uncommon');const before=loads;
 for(let i=0;i<30;i++){const fresh=deferIconLoads(()=>icon(i+2,'green',i%2===0));check(patchPanel(old,fresh)===old,'Icon identity survives quantity/lock refresh');activateIconLoads(old);}
 check(loads===before&&old.children.includes(image),'Unchanged icons never assign another source, including comparison trees');
 check(old.children.find(n=>n.className==='icon-quantity').textContent==='×31','Latest quantity shown');
 image.emit('error');const failedLoads=loads;patchPanel(old,deferIconLoads(()=>icon(32)));activateIconLoads(old);check(old.dataset.assetFallback==='true'&&!old.children.some(n=>n.tagName==='IMG')&&loads===failedLoads,'Failed image not retried during polling');
 const replacement=patchPanel(old,deferIconLoads(()=>icon(33,'green',false,'/game/runtime/test/'+'b'.repeat(64))));check(replacement!==old,'Published version changes replace only that icon');old=replacement;activateIconLoads(old);check(loads===failedLoads+1&&old.children.some(n=>n.tagName==='IMG'),'Changed version loads exactly one adopted image');
 const plain=doc.createElement('img');plain.src='old';const different=doc.createElement('img');different.src='new';check(patchPanel(plain,different)===different&&plain.src==='old','Source compared before attribute copy');
 const container=doc.createElement('div'),a=doc.createElement('button'),b=doc.createElement('button');a.dataset.equipmentId='a';b.dataset.equipmentId='b';a.append(icon());b.append(icon());container.append(a,b);const ai=a.children[0],bi=b.children[0];
 const reordered=deferIconLoads(()=>{const root=doc.createElement('div');for(const id of ['b','new','a']){const c=doc.createElement('button');c.dataset.equipmentId=id;c.append(icon());root.append(c);}return root;});const reorderLoads=loads;patchPanel(container,reordered);activateIconLoads(container);
 check(container.children[0]===b&&container.children[2]===a&&a.children[0]===ai&&b.children[0]===bi,'Insertion/reordering retains existing equipment artwork');check(loads===reorderLoads+1,'Only inserted item loads');
 const {retainScreen}=load(base+'components/retained-screen.js'),ctx={data:{quantity:1},busy:false};let renders=0;const render=c=>{renders++;const root=doc.createElement('section');root.append(icon(c.data.quantity));return root;};const root=render(ctx),retained=root.children[0],count=loads;const controller=retainScreen(root,ctx,render);controller.update({quantity:2},false);check(root.children[0]===retained&&loads===count,'Actual retained-screen update defers unused loads');
 return {tests:checks,status:'PASS'};
}

export function testRetainedScreen(sources){
 let checks=0;const assert=(v,m)=>{if(!v)throw Error(m);checks++;};
 const doc={activeElement:null,createElement(tag){return {tagName:tag.toUpperCase(),ownerDocument:doc,querySelectorAll(){return [];},children:[],dataset:{},attrs:{},events:{},value:'',className:'',textContent:'',
 addEventListener(type,f){(this.events[type]??=[]).push(f);},emit(type){for(const f of this.events[type]||[])f({type});},append(...nodes){this.children.push(...nodes);},replaceChildren(...nodes){this.children=nodes;},getAttributeNames(){return Object.keys(this.attrs);},getAttribute(k){return this.attrs[k];},setAttribute(k,v){this.attrs[k]=v;},removeAttribute(k){delete this.attrs[k];}};}};
 const {el,button}=new Function('document',sources.dom.replace(/^export /gm,'')+';return {el,button};')(doc);
 const {patchPanel}=new Function(sources.patch.replace(/^export /gm,'')+';return {patchPanel};')();
 const {retainScreen}=new Function('patchPanel','deferIconLoads','activateIconLoads',sources.retained.replace(/^import.*$/gm,'').replace(/^export /gm,'')+';return {retainScreen};')(patchPanel,build=>build(),()=>{});
 let seen=null;const ctx={data:{quantity:1},busy:false};
 const render=c=>{const root=el('section'),value=el('span','',c.data.quantity),input=el('input'),details=el('details');input.value='saved';input.addEventListener('change',()=>{seen=input.value+':'+c.data.quantity;});root.append(value,input,button('执行',()=>{seen=input.value+':'+c.data.quantity;}),details);return root;};
 const root=render(ctx),[value,input,command,details]=root.children;details.open=true;details.setAttribute('open','');doc.activeElement=input;input.value='draft';const cleanup=retainScreen(root,ctx,render);
 cleanup.update({quantity:2},true);
 assert(root.children[0]===value&&root.children[1]===input&&root.children[2]===command,'Polling preserves node identities');
 assert(value.textContent==='2'&&ctx.busy===true,'Committed values update');
 assert(input.value==='draft'&&details.open,'Polling preserves focused draft and expanded details');
 input.value='latest';command.emit('click');assert(seen==='latest:2','Retained button reads live input and new facts');
 input.emit('change');assert(seen==='latest:2','Retained change handler reads live input');
 cleanup.update({quantity:3},false);command.emit('click');assert(seen==='latest:3','Repeated polling uses newest handler once');
 return {tests:checks,status:'PASS'};
}

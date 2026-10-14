// Retain DOM and loaded artwork while adopting authoritative display facts.
const identities=['progressJob','recipeId','resourceId','building','equipmentId','dungeonId','slot','overviewConcept','systemIcon','attributeId','id','assetId','catalogAsset'];
function key(node){for(const name of identities)if(node?.dataset?.[name])return `${name}:${node.dataset[name]}`;return node?.id?`id:${node.id}`:'';}
function reconcile(parent,before,after){
 if(before.length===after.length&&after.every((node,i)=>node===before[i]))return;
 // Move only changed children: replaceChildren would detach every retained image.
 if(!parent.insertBefore){parent.replaceChildren(...after);return;}
 for(let i=0;i<after.length;i++)if(parent.childNodes[i]!==after[i])parent.insertBefore(after[i],parent.childNodes[i]||null);
 for(const node of before)if(!after.includes(node))node.remove();
}
function patchIcon(old,fresh){
 old.className=fresh.className;
 for(const name of ['profile','fallback']){if(name in fresh.dataset)old.dataset[name]=fresh.dataset[name];else delete old.dataset[name];}
 // Keep successfully loaded images and their original error handlers.
 for(const cls of ['icon-quantity','icon-lock']){
  const before=[...old.children].find(n=>n.className===cls),after=[...fresh.children].find(n=>n.className===cls);
  if(before&&after){if(before.textContent!==after.textContent)before.textContent=after.textContent;}
  else if(after)old.append(after);else before?.remove();
 }
 return old;
}
export function patchPanel(old,fresh){
 if(old.nodeType===3&&fresh.nodeType===3){if(old.nodeValue!==fresh.nodeValue)old.nodeValue=fresh.nodeValue;return old;}
 if(old.tagName!==fresh.tagName||key(old)!==key(fresh))return fresh;
 if(['INPUT','SELECT','TEXTAREA'].includes(old.tagName)&&(old.type!==fresh.type||old.getAttribute('aria-label')!==fresh.getAttribute('aria-label')))return fresh;
 if(old.tagName==='IMG'&&old.getAttribute('src')!==(fresh.dataset?.pendingIconSrc||fresh.getAttribute('src')))return fresh;
 if(old.classList?.contains('item-icon')&&fresh.classList?.contains('item-icon')){
  if(old.__runtimeURL!==fresh.__runtimeURL||old.dataset.assetId!==fresh.dataset.assetId)return fresh;
  // Retry a transient load failure once per mounted icon; avoid requests on every poll.
  if(old.dataset.assetFallback==='true'&&fresh.__runtimeURL&&!fresh.dataset.assetFallback&&!old.__iconRetried){fresh.__iconRetried=true;return fresh;}
  return patchIcon(old,fresh);
 }
 if(old.__jobProgress&&fresh.__jobProgress){old.__jobProgress.update(fresh.__jobProgress.snapshot);return old;}
 if(fresh.__runtimeURL!==undefined)old.__runtimeURL=fresh.__runtimeURL;
 if(fresh.__onClick)old.__onClick=fresh.__onClick;
 if(old.__eventBindings&&fresh.__eventBindings){for(let i=0;i<old.__eventBindings.length;i++){const before=old.__eventBindings[i],after=fresh.__eventBindings[i];if(after&&before.type===after.type)before.callback=after.callback;}}
 if(old.className!==fresh.className)old.className=fresh.className;
 const attrs=n=>n.getAttributeNames?n.getAttributeNames():Object.keys(n.attrs||{});
 for(const a of attrs(old))if(!attrs(fresh).includes(a)&&!(old.tagName==='DETAILS'&&a==='open'))old.removeAttribute(a);
 for(const a of attrs(fresh))if(!(old.tagName==='IMG'&&a==='src')&&old.getAttribute(a)!==fresh.getAttribute(a))old.setAttribute(a,fresh.getAttribute(a));
 for(const a of Object.keys(old.dataset||{}))if(!(a in (fresh.dataset||{})))delete old.dataset[a];
 for(const [a,v]of Object.entries(fresh.dataset||{}))if(old.dataset[a]!==v)old.dataset[a]=v;
 // Mounted fields hold unsubmitted user drafts, including after focus leaves them.
 // Explicit redraw/navigation may reset them; live state polling must not.
 for(const a of ['disabled','hidden','href','type','title','max','value','checked'])if(fresh[a]!==undefined&&old[a]!==fresh[a]&&!(['value','checked'].includes(a)&&(['INPUT','SELECT','TEXTAREA'].includes(old.tagName)||old.ownerDocument?.activeElement===old)))old[a]=fresh[a];
 if(['INPUT','SELECT','TEXTAREA'].includes(old.tagName)){for(const prop of ['value','checked']){try{Object.defineProperty(fresh,prop,{configurable:true,get:()=>old[prop],set:value=>{old[prop]=value;}});}catch{}}}
 if(old.tagName==='DETAILS')fresh.open=old.open;
 const before=[...(old.childNodes||old.children)],after=[...(fresh.childNodes||fresh.children)];
 if(!before.length&&!after.length){if(old.textContent!==fresh.textContent)old.textContent=fresh.textContent;return old;}
 const used=new Set(),children=after.map((n,i)=>{const k=key(n),candidate=k?before.find(x=>key(x)===k&&!used.has(x)):before[i];if(!candidate||used.has(candidate)||(!k&&key(candidate)))return n;used.add(candidate);return patchPanel(candidate,n);});
 reconcile(old,before,children);
 return old;
}

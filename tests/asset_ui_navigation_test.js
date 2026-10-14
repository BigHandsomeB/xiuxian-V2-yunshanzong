// Deferred responses drive the shipped functions; removed page nodes return null.
// Native DOM adapter only: real mobile visual acceptance remains separate.
async function testAssetUiNavigation(source, fixture) {
 const nodes=new Map(),named=new Map(),actions=[];let epoch=0,pending=[];
 const attr=s=>Object.fromEntries([...s.matchAll(/([\w-]+)="([^"]*)"/g)].map(m=>[m[1],m[2]]));
 function node(persistent=false){const born=epoch;return {persistent,value:'',checked:false,disabled:false,open:false,dataset:{},textContent:'',_html:'',get isConnected(){return persistent||born===epoch;},focus(){},scrollIntoView(){},showModal(){this.open=true;},close(){this.open=false;},querySelector:find,querySelectorAll(s){if(s==='[data-action]:checked')return actions.filter(n=>n.checked);if(s==='input,select')return actions;return [];},get innerHTML(){return this._html;},set innerHTML(h){this._html=h;if(this===nodes.get('#view')){epoch++;for(const [k,n] of nodes)if(!n.persistent)nodes.delete(k);named.clear();actions.length=0;}if(h.includes('<option')){const opts=[...h.matchAll(/<option value="([^"]*)"([^>]*)>/g)];if(opts.length)this.value=(opts.find(m=>m[2].includes('selected'))||opts[0])[1];}parse(h);}};}
 function parse(html){for(const m of html.matchAll(/<(input|select|textarea|section|form|div|fieldset|button|p|label)\b([^>]*)>/g)){const a=attr(m[2]),n=node();n.value=a.value||'';n.name=a.name;n.type=a.type;n.checked=/\bchecked\b/.test(m[2]);n.disabled=/\bdisabled\b/.test(m[2]);if(a.id)nodes.set('#'+a.id,n);if(a.name)named.set(a.name,n);if(a['data-action']){n.dataset.action=a['data-action'];actions.push(n);}if(a['data-count']){n.dataset.count=a['data-count'];nodes.set('[data-count="'+a['data-count']+'"]',n);}if(m[1]==='select')n.innerHTML=html.slice(m.index).match(/^<select[^>]*>([\s\S]*?)<\/select>/)?.[1]||'';}}
 function find(s){if(s==='meta[name="asset-base"]')return {content:'/tools/assets'};const m=s.match(/\[name="([^"]+)"\]/);return m?named.get(m[1])||null:nodes.get(s)||null;}
 for(const id of ['view','heading','editor','notice','dialog-body'])nodes.set('#'+id,node(true));
 class Form {constructor(){this.entries=[...named].filter(([k,n])=>!n.disabled).map(([k,n])=>[k,n.value]);}get(k){return this.entries.find(([name])=>name===k)?.[1]??null;}*[Symbol.iterator](){yield* this.entries;}}
 const response=data=>({ok:true,status:200,json:async()=>data});
 const fetch=(url,request)=>{if(url.split('?')[0].endsWith('/state'))return Promise.resolve(response(fixture));return new Promise(resolve=>pending.push({url,body:request.body?JSON.parse(request.body):null,resolve:data=>resolve(response(data))}));};
 const prefix=source.slice(0,source.indexOf("$('#close').onclick"));
 const ui=new Function('document','FormData','fetch','fixture',prefix+'\nstate=fixture; return {browse,promptPage};')({querySelector:find},Form,fetch,fixture);
 const flush=async()=>{for(let i=0;i<30;i++)await Promise.resolve();};
 const take=path=>{const i=pending.findIndex(p=>p.url.includes('/api/'+path));if(i<0)throw Error('Missing request '+path);return pending.splice(i,1)[0];};
 const noError=()=>{if(find('#notice').textContent)throw Error(find('#notice').textContent);};
 // Old library search completing after the actual Prompt page replaces the list.
 ui.browse();find('#search').oninput();await flush();const search=take('search');ui.promptPage(null,{template_id:'character_compact_v1'});await flush();search.resolve({assets:[]});await flush();noError();
 // Re-entering Prompt creates a different page instance; old spec must not update it.
 const old=take('spec');ui.promptPage(null,{template_id:'pill_icon_v1'});await flush();const latest=take('spec');latest.resolve(fixture.specs.pill_icon_v1);await flush();const expected=find('#pixel-spec').innerHTML;old.resolve(fixture.specs.character_compact_v1);await flush();if(find('#pixel-spec').innerHTML!==expected)throw Error('Old specification overwrote new Prompt page');noError();
 // Leaving Prompt before spec completes cannot write to a removed pixel-spec node.
 ui.promptPage(null,{template_id:'character_compact_v1'});await flush();const leaving=take('spec');find('#view').innerHTML='<p>Sources</p>';leaving.resolve(fixture.specs.character_compact_v1);await flush();noError();
 // Prompt generation can complete/save, but must not replace another Prompt instance.
 ui.promptPage({asset_id:'test.character',template_id:'character_compact_v1',name_zh:'剑修',state:'idle'},{});await flush();take('spec').resolve(fixture.specs.character_compact_v1);await flush();find('#prompt-form').onsubmit({preventDefault(){}});await flush();const generated=take('prompts');ui.promptPage(null,{template_id:'pill_icon_v1'});await flush();take('spec').resolve(fixture.specs.pill_icon_v1);await flush();generated.resolve({prompt_id:'late',template_version:1,frozen_spec:fixture.specs.character_compact_v1,text:'OLD ENGLISH PROMPT'});await flush();if(find('#prompt-result').innerHTML.includes('OLD ENGLISH PROMPT'))throw Error('Old generation replaced current page');noError();
 // A queued spec update must not start after synchronous page replacement.
 ui.promptPage(null,{template_id:'character_compact_v1'});find('#view').innerHTML='<p>Sources</p>';await flush();noError();
 // Same-page searches complete out of order; newest filter remains visible.
 ui.browse();find('#search').oninput();await flush();const first=take('search');find('#search').value='new';find('#search').oninput();await flush();const second=take('search');second.resolve({assets:[]});await flush();const library=find('#results').innerHTML;first.resolve({assets:[{asset_id:'old',name_zh:'old',template_id:'resource_icon_v1',versions:[],art_status:'draft'}]});await flush();if(find('#results').innerHTML!==library)throw Error('Older search replaced latest result');noError();
 return 'PASS: actual library→Prompt, repeated Prompt/spec, Prompt→Sources, late generation and out-of-order filters';
}

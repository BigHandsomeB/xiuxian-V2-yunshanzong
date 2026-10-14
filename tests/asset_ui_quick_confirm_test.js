// Actual quickReview handler tests in a native DOM adapter; not real-phone visual acceptance.
async function testAssetQuickUi(source,preview){
 const attrs=s=>Object.fromEntries([...s.matchAll(/([\w-]+)="([^"]*)"/g)].map(m=>[m[1],m[2]]));let nodes=[];
 const container={isConnected:true,_html:'',get innerHTML(){return this._html;},set innerHTML(html){this._html=html;nodes=[];for(let m of html.matchAll(/<(button|img|p)\b([^>]*)>/g)){let a=attrs(m[2]),n={dataset:{},disabled:/\bdisabled\b/.test(m[2]),textContent:'',complete:false,naturalWidth:0};for(let [k,v] of Object.entries(a))if(k.startsWith('data-'))n.dataset[k.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase())]=v;for(let flag of m[2].matchAll(/\bdata-([a-z-]+)(?=\s|$)/g))n.dataset[flag[1].replace(/-([a-z])/g,(_,c)=>c.toUpperCase())]='';nodes.push(n);}},querySelectorAll(selector){let attr=selector.slice(1,-1).replace(/-([a-z])/g,(_,c)=>c.toUpperCase()).replace(/^data/,'');attr=attr[0].toLowerCase()+attr.slice(1);return nodes.filter(n=>n.dataset[attr]!==undefined);},querySelector(selector){let m=selector.match(/^\[data-([a-z-]+)(?:="([^"]*)")?\]$/),key=m?.[1].replace(/-([a-z])/g,(_,c)=>c.toUpperCase());return nodes.find(n=>n.dataset[key]!==undefined&&(m[2]===undefined||n.dataset[key]===m[2]));}};
 let calls=[],release;
 const api=async(path,data)=>{calls.push({path,data});return await new Promise(resolve=>release=()=>resolve({assets:preview.items.map(i=>({asset_id:i.asset_id,name_zh:i.name_zh,version:1,status:data.excluded.includes(i.asset_id)?'needs_review':'approved',excluded:data.excluded.includes(i.asset_id),issues:[],master:false})),manifest_updated:true}));};
 const block=source.slice(source.indexOf('function quickReview('),source.indexOf('async function quickExisting('));
 const show=new Function('esc','label','BASE','api','refresh','notice',block+';return quickReview;')(x=>String(x),x=>x,'/tools/assets',api,async()=>{},()=>{});
 show(preview,container);
 const exportTarget=(preview.items[0].runtime_spec||preview.items[0].frozen_spec).runtime_profile.frame_size.join('×');
 if(!container.innerHTML.includes('Runtime '+exportTarget+' · 最近邻'))throw Error('Runtime preview shows generation size instead of export target');
 let finish=container.querySelector('[data-quick-finish]');
 if(!finish.disabled)throw Error('Confirmation enabled before previews load');
 if(container.innerHTML.includes('type="checkbox"'))throw Error('Batch review requires redundant checkboxes');
 const images=container.querySelectorAll('[data-quick-load]');for(let image of images)image.onload();
 if(finish.disabled||!container.querySelector('[data-quick-summary]').textContent.startsWith('6 / 6'))throw Error('All valid items not included by default');
 container.querySelector('[data-quick-toggle="4"]').onclick();if(!container.querySelector('[data-quick-summary]').textContent.startsWith('5 / 6'))throw Error('Exclude does not update batch count');
 let completion=finish.onclick();finish.onclick();if(calls.length!==1||!finish.disabled)throw Error('Repeated tap submits duplicate confirmation');
 if(calls[0].data.excluded[0]!==preview.items[4].asset_id||calls[0].data.confirmed!==true)throw Error('Excluded asset or explicit review consent missing');
 release();await completion;if(!container.innerHTML.includes('已批准 5 个素材')||!container.innerHTML.includes('Manifest：已更新'))throw Error('Completion result not visible');
 show(preview,container);finish=container.querySelector('[data-quick-finish]');let broken=container.querySelectorAll('[data-quick-load]')[0];broken.onerror();for(let image of container.querySelectorAll('[data-quick-load]'))image.onload();
 if(!container.querySelector('[data-quick-toggle="0"]').disabled||container.querySelector('[data-quick-summary]').textContent.startsWith('6 / 6'))throw Error('Invisible broken preview could be approved');
 if(finish.disabled)throw Error('Broken item blocked all healthy items');
 const oldImages=container.querySelectorAll('[data-quick-load]');container.quickToken='new-preview';container.innerHTML='';for(let image of oldImages){image.onload();image.onerror();}
 return 'PASS: default-all previews, explicit once-only confirmation, exclusion, completion output and failed-image isolation and stale-image guards';
}

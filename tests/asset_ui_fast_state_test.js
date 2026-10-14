// Shipped lazy-read and list handlers with delayed responses; no phone visual claim.
async function testAssetFastUi(source){
 const nodes=new Map(),pending=[];
 function find(s){if(s==='meta[name="asset-base"]')return {content:'/tools/assets'};if(!nodes.has(s))nodes.set(s,node());return nodes.get(s);}
 function node(){return {value:'',open:false,textContent:'',_html:'',querySelector:find,querySelectorAll(){return [];},showModal(){this.open=true;},close(){this.open=false;},insertAdjacentHTML(_,html){this._html+=html;},get innerHTML(){return this._html;},set innerHTML(html){if(this===nodes.get('#view'))for(const k of [...nodes.keys()])if(!['#view','#heading','#editor','#dialog-body','#notice'].includes(k))nodes.delete(k);this._html=html;}};}
 const fetch=(url)=>new Promise(resolve=>pending.push({url,resolve:body=>resolve({ok:true,status:200,json:async()=>body})}));
 const fixture={assets:[{asset_id:'test.actor',name_zh:'测试',template_id:'monster_static_v1',summary_only:true,versions:[],tags:[]}],prompts:[],sources:[{source_id:'old-source',summary_only:true}],templates:[],sets:[]};
 const prefix=source.slice(0,source.indexOf("$('#close').onclick"));
 const ui=new Function('document','fetch','fixture',prefix+'\nstate=fixture;return {detail,slice,loadPrompt,renderAssetPage,getState:()=>state};')({querySelector:find},fetch,fixture);
 const flush=async()=>{for(let i=0;i<25;i++)await Promise.resolve();};
 ui.detail('test.actor');await flush();if(pending.length!==1||!pending[0].url.includes('/asset-detail?'))throw Error('Asset must load only its own detail');
 find('#view').innerHTML='OTHER PAGE';pending.shift().resolve({asset:{asset_id:'test.actor'},prompts:[]});await flush();if(find('#view').innerHTML!=='OTHER PAGE'||!fixture.assets[0].summary_only)throw Error('Late asset read overwrote navigation');
 ui.detail('test.actor');await flush();pending.shift().resolve({asset:{asset_id:'test.actor',name_zh:'完整记录',template_id:'monster_static_v1',versions:[],tags:[],current_approved_version:null},prompts:[{prompt_id:'p1',asset_id:'test.actor',text:'original history',frozen_spec:{},options:{}}]});await flush();if(fixture.assets[0].summary_only||!find('#view').innerHTML.includes('original history'))throw Error('Asset detail/history not hydrated');
 ui.slice(fixture.sources[0]);await flush();if(!pending[0].url.includes('/source-detail?'))throw Error('Source must hydrate before slicing');find('#view').innerHTML='NEXT PAGE';pending.shift().resolve({source:{source_id:'old-source'},prompt:null});await flush();if(find('#view').innerHTML!=='NEXT PAGE')throw Error('Late source read replaced page');
 fixture.prompts.push({prompt_id:'p2',options:{}});let first=ui.loadPrompt('p2');await flush();pending.shift().resolve({prompt_id:'p2',text:'exact saved text',frozen_spec:{}});await first;await ui.loadPrompt('p2');if(pending.length)throw Error('Hydrated Prompt fetched twice');
 const list=node(),assets=Array.from({length:30},(_,i)=>({asset_id:'id'+i,name_zh:'asset '+i,template_id:'monster_static_v1',versions:[],art_status:'draft'}));ui.renderAssetPage(list,assets);if((list.innerHTML.match(/<article>/g)||[]).length!==24||list.innerHTML.includes('asset 29'))throw Error('List must be bounded to24 cards');find('[data-list-next]').onclick();if((list.innerHTML.match(/<article>/g)||[]).length!==6||!list.innerHTML.includes('asset 29'))throw Error('Remaining cards not reachable');
 return 'PASS: lazy asset/history and Source hydration, stale-navigation guards, Prompt reuse and24-card pagination';
}

// Tests the shipped dialog handler using native JS, not a phone visual PASS.
async function testAssetLifecycleUi(source){
 const block=source.slice(source.indexOf('const lifecycleNames='),source.indexOf('async function route()'));
 let html='',nodes={},calls=[],release,routes=[],notices=[];
 const open=text=>{html=text;nodes={};for(const m of text.matchAll(/<(button|input|p)\b([^>]*)>/g)){const id=m[2].match(/id="([^"]+)"/);if(id)nodes[id[1]]={disabled:/\bdisabled\b/.test(m[2]),checked:false,value:m[2].match(/value="([^"]*)"/)?.[1]||'',textContent:''};}};
 const $=sel=>nodes[sel.slice(1)]||null;
 const api=async(path,data)=>{calls.push({path,data});return new Promise(resolve=>release=()=>resolve({new_status:'active'}));};
 const show=new Function('open','$','esc','label','assetBy','close','api','refresh','detail','setDetail','sources','groups','browse','notice',block+';return showLifecycleConfirmation;')(open,$,x=>String(x).replaceAll('<','&lt;'),x=>x,()=>null,()=>{},api,async()=>{},id=>routes.push(id),id=>routes.push(id),()=>{},()=>{},()=>{},s=>notices.push(s));
 const p={operation:'deprecate_set',kind:'set',key:'set.test.v1',name_zh:'宗门矿石',previous_status:'active',art_status:null,asset_count:6,approved:6,runtime:6,source_count:1,manifest_count:6,file_count:0,physical:false,blockers:[],force_blockers:[],confirmation_id:'receipt'};
 show(p);if(!html.includes('宗门矿石')||!html.includes('已发布 6 项')||!html.includes('普通操作保留文件'))throw Error('Missing impact summary');
 if(calls.length)throw Error('Opening summary submitted mutation');
 const work=$('#life-confirm').onclick();$('#life-confirm').onclick();if(calls.length!==1||calls[0].data.confirmed!==true||calls[0].data.force!==false)throw Error('Explicit confirmation or repeated tap guard missing');release();await work;
 if(routes[0]!==p.key||notices.length!==1)throw Error('Completion routing missing');
 const hard={...p,operation:'purge_set_members',confirmation_phrase:'永久删除',physical:true,file_count:12,blockers:[{asset_id:'icon.ore',reason:'历史批准记录'}]};show(hard);
 if(!html.includes('输入“永久删除”确认')||html.includes('输入完整机器ID'))throw Error('Machine ID typing still required');
 if($('#life-confirm')||!$('#life-force'))throw Error('Blocked purge bypasses second confirmation');$('#life-force').onclick();if($('#life-confirm-final'))throw Error('Missing confirmation phrase check');
 $('#life-id').value=hard.confirmation_phrase;$('#life-force').onclick();if(!$('#life-confirm-final').disabled||!html.includes('二次确认'))throw Error('Irreversible second confirmation missing');
 $('#life-understood').checked=true;$('#life-understood').onchange();const forced=$('#life-confirm-final').onclick();if(calls[1].data.confirmation_text!=='永久删除'||!calls[1].data.force||!calls[1].data.force_confirmed)throw Error('Explicit force choices missing');release();await forced;
 show({...hard,force_blockers:[{asset_id:'icon.ore',reason:'被其他素材引用'}]});if($('#life-force')||$('#life-confirm')||!html.includes('请先废弃或解除引用'))throw Error('External reference can be forced');
 show({...hard,kind:'asset',operation:'purge_asset',key:'icon.ore',blockers:[{asset_id:'icon.ore',reason:'仍属于素材组：建筑图标'}],force_blockers:[{asset_id:'icon.ore',reason:'仍属于素材组：建筑图标'}]});
 if(!$('#life-blocked')?.disabled||!$('#life-detach')||$('#life-id')||$('#life-confirm')||$('#life-force'))throw Error('Grouped asset lacks actionable blocked state or asks for unusable deletion confirmation');
 show({...p,kind:'asset',operation:'restore_asset',art_status:'deprecated'});const restore=$('#life-confirm').onclick();if(calls[2].path!=='lifecycle-confirm'||calls[2].data.force)throw Error('Restore is not ordinary explicit action');release();await restore;if(calls.some(c=>c.path==='publish'))throw Error('Restore automatically publishes');
 return 'PASS: six-item impact, explicit confirmation, duplicate-tap prevention, Chinese phrase/second force consent, external-reference block and restore without publish';
}

// A stale phone cookie after service restart must not leave an inert open dialog.
async function testAssetExpiredSessionUi(source){
 const block=source.slice(source.indexOf('async function api('),source.indexOf('async function refresh('));
 let redirects=[],mode=401,requests=0;
 const location={hash:'#set/asset_set.resource.a93cfff610b5a',assign:url=>redirects.push(url)};
 const fetch=async()=>{requests++;return {status:mode,ok:mode===200,json:async()=>mode===200?{ok:true}:{error:mode===401?'Authentication required':'Referenced asset'}};};
 const api=new Function('fetch','BASE','state','location',block+';return api;')(fetch,'/tools/assets',{csrf:'stub'},location);
 try{await api('lifecycle-preview',{kind:'asset',key:'icon.ore',operation:'clean_runtime'});}catch(error){if(!redirects.length)throw Error('Expired-session cleanup leaves open dialog with hidden error; login navigation missing');if(!error.message.includes('登录'))throw Error('Expired session message is not actionable');}
 if(redirects[0]!=='/tools/assets/login'+location.hash||requests!==1)throw Error('Login loses current destination or silently replays cleanup');
 mode=400;const count=redirects.length;try{await api('lifecycle-confirm',{confirmation_id:'old',confirmed:true});}catch(error){if(error.message!=='Referenced asset')throw error;}if(redirects.length!==count)throw Error('Validation failure redirects to login');
 mode=200;if(!(await api('state')).ok)throw Error('Successful API changed');
 const runBlock=source.slice(source.indexOf('function run(fn)'),source.indexOf("\n$('#close').onclick"));let dialogError={textContent:''};const run=new Function('$','notice',runBlock+';return run;')(id=>id==='#dialog-error'?dialogError:null,()=>{});run(()=>{throw Error('明确的引用阻止原因');});await Promise.resolve();await Promise.resolve();if(dialogError.textContent!=='明确的引用阻止原因')throw Error('Modal error hidden behind the open dialog');
 return 'PASS: 401 cleanup explicitly opens login with current view preserved, no replay, ordinary validation/success unaffected';
}

// Source deletion must expose a route to retained assets, without bypassing references.
async function testAssetSourceReferencesUi(source){
 const block=source.slice(source.indexOf('const lifecycleNames='),source.indexOf('async function route()'));
 let html='',nodes={},closed=0,requests=0;const location={hash:'#sources'};
 const open=text=>{html=text;nodes={};for(const m of text.matchAll(/<(button|input|p)\b([^>]*)>/g)){const id=m[2].match(/id="([^"]+)"/);if(id)nodes[id[1]]={disabled:/\bdisabled\b/.test(m[2]),value:'',textContent:''};}};
 const $=sel=>nodes[sel.slice(1)]||null;
 const noop=()=>{};
 const show=new Function('open','$','esc','label','assetBy','close','location','api','refresh','detail','setDetail','sources','groups','browse','notice',block+';return showLifecycleConfirmation;')(open,$,String,String,()=>({name_zh:'银灵矿'}),()=>closed++,location,()=>requests++,noop,noop,noop,noop,noop,noop,noop);
 const p={kind:'source',key:'source-id',operation:'delete_source',name_zh:'source.png',previous_status:'active',asset_count:0,approved:0,runtime:0,source_count:1,file_count:1,manifest_count:0,physical:true,reference_asset_count:1,referencing_assets:[{asset_id:'kuangshi.icon',name_zh:'银灵矿',lifecycle_status:'active',set_id:null,version_numbers:[1],approved_version_numbers:[1]}],blockers:[{asset_id:'kuangshi.icon',reason:'原图仍被素材历史版本引用；废弃不会解除历史引用'}],force_blockers:[{asset_id:'kuangshi.icon',reason:'原图仍被素材历史版本引用'}]};
 show(p);
 if(!html.includes('引用素材</dt><dd>1 个')||!html.includes('未分组不等于已删除')||!html.includes('含已批准版本')||!html.includes('查看 银灵矿'))throw Error('Source blocker does not explain retained Asset and history');
 if(html.includes('成员 / 素材')||html.includes('请先废弃或解除引用'))throw Error('Misleading Source summary or deprecation advice remains');
 if($('#life-confirm')||$('#life-force')||requests)throw Error('Source reference protection bypassed');
 $('#life-reference-0').onclick();if(location.hash!=='asset/kuangshi.icon'||closed!==1||requests)throw Error('View reference did not navigate safely without mutation');
 show({...p,reference_asset_count:0,referencing_assets:[],blockers:[],force_blockers:[],retired_preview_ids:['a','b','c','d','e','f'],pending_preview_count:1});
 if(!html.includes('6 条切图预览缓存')||!html.includes('取消 1 条待确认预览')||!$('#life-confirm')||requests)throw Error('Obsolete preview cleanup is still blocked or lacks explicit confirmation');
 return 'PASS: retained ungrouped approved asset shown, accurate Source count/advice, safe reference navigation and deletion still blocked';
}

async function testAssetWholeSetDeleteUi(source){
 const block=source.slice(source.indexOf('function setActions('),source.indexOf('async function lifecycleDialog('));
 let html='',buttons=[],calls=[];
 const open=text=>{html=text;buttons=[...text.matchAll(/<button[^>]*data-life="([^"]+)"[^>]*>/g)].map(m=>({dataset:{life:m[1]}}));};
 const setActions=new Function('open','esc','$','run','lifecycleDialog',block+';return setActions;')(open,String,()=>({querySelectorAll:()=>buttons}),fn=>fn(),(...args)=>calls.push(args));
 setActions({set_id:'group.test',name_zh:'宗门矿石',status:'active'});
 if(!html.split('<details>')[0].includes('删除整个素材组及全部素材'))throw Error('Whole-group deletion remains hidden');
 if(!html.includes('一次删除组内全部素材')||!html.includes('仅删除组容器 · 保留素材'))throw Error('Group/container deletion semantics unclear');
 buttons.find(b=>b.dataset.life==='purge_set_members').onclick();
 if(calls.length!==1||calls[0].join('|')!=='set|group.test|purge_set_members')throw Error('Whole-group deletion requires member-by-member actions');
 return 'PASS: visible whole-set deletion invokes one existing batch impact preview; container-only option remains separate';
}

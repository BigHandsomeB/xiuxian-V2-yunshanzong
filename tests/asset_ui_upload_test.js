// Actual upload submit handler, isolated network/DOM. No live uploads.
async function testAssetUpload(source){
 const nodes=new Map(),errors=[],calls=[],saved={source_id:'saved',width:10,height:10};let file={name:'monster.png',size:1024},fail=false,refreshFail=false,pending=null,sliced=null;
 const $=selector=>{if(!nodes.has(selector))nodes.set(selector,{value:selector.includes('template_id')?'monster':'',disabled:false,textContent:'',innerHTML:''});return nodes.get(selector);};
 const state={templates:[{template_id:'monster',template_version:1,families:{}}],prompts:[],sets:[],sources:[]};
 class Form{constructor(){this.values=new Map([['file',file],['prompt_id','']]);}get(k){return this.values.get(k);}set(k,v){this.values.set(k,v);}}
 const api=async(path)=>{if(path==='spec')return {};calls.push(path);if(pending)await pending;if(fail)throw Error('Load failed');return saved;};
 const block=source.slice(source.indexOf('function upload('),source.indexOf('\nfunction slice('));
 new Function('state','$','open','options','run','api','loadPrompt','specSummary','FormData','refresh','close','slice','notice',block+';upload();')(state,$,()=>{},()=>'',fn=>Promise.resolve().then(fn).catch(e=>errors.push(e.message)),api,()=>{},()=>'',Form,async()=>{if(refreshFail)throw Error('Load failed');},()=>{},s=>{sliced=s;},()=>{});
 const flush=async()=>{for(let i=0;i<30;i++)await Promise.resolve();};await flush();
 const submit=()=>$('#upload-form').onsubmit({preventDefault(){},target:{}});
 file.size=13*1024*1024;submit();await flush();if(calls.length||!errors.at(-1).includes('12MB'))throw Error('Oversized image was uploaded');
 file.size=1024;let release;pending=new Promise(r=>release=r);submit();submit();await flush();if(calls.length!==1||!$('#upload-submit').disabled)throw Error('Duplicate submit was allowed');release();pending=null;await flush();if(sliced!==saved)throw Error('Successful upload did not open saved source');
 sliced=null;fail=true;submit();await flush();if($('#upload-submit').disabled||file.name!=='monster.png'||sliced)throw Error('Failure lost file or prevented retry');
 fail=false;refreshFail=true;submit();await flush();if(sliced!==saved||state.sources[0]!==saved)throw Error('List refresh failure discarded successful upload');
 const apiBlock=source.slice(source.indexOf('async function api('),source.indexOf('async function refresh('));
 const networkApi=new Function('fetch','BASE','state','location',apiBlock+';return api;')(async()=>{throw TypeError('Load failed');},'',{csrf:'test'},{assign(){}});
 try{await networkApi('source',{},true);throw Error('Expected rejection');}catch(e){if(!e.message.includes('所选图片仍保留'))throw Error('Raw Load failed still leaks through API');}
 return 'PASS: upload size preflight, duplicate prevention, retained file retry, successful save despite list failure, localized network failure';
}

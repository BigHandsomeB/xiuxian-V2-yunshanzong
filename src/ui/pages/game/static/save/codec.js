// Complete gameplay state only: transport credentials and pending HTTP intent never enter this format.
export const MAX_SAVE_BYTES=2*1024*1024;
const fields=['ancestors','commitId','formatVersion','saveId','source','state','updatedAt','version'];
const stateFields=['content_version','data_schema_version','domains','generation','identity','revision','save_id','save_schema_version','time'];
const forbidden=new Set(['csrf','session','xianxia-game-pending-v1','__proto__','prototype','constructor']);
const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
function requireValue(ok,message='存档格式不正确。'){if(!ok)throw new Error(message);}
function object(value){return value!==null&&typeof value==='object'&&!Array.isArray(value);}
function integer(value,min=0){return Number.isSafeInteger(value)&&value>=min;}
function exact(value,keys){return object(value)&&Object.keys(value).sort().join('|')===keys.join('|');}
function clean(value,depth=0){
 requireValue(depth<=64,'存档层级过深。');
 if(value===null||typeof value==='string'||typeof value==='boolean')return value;
 if(typeof value==='number'){requireValue(Number.isFinite(value));return value;}
 if(Array.isArray(value))return value.map(v=>clean(v,depth+1));
 requireValue(object(value));const result={};
 for(const key of Object.keys(value).sort()){requireValue(!forbidden.has(key),'存档不能含登录信息或待确认请求。');result[key]=clean(value[key],depth+1);}
 return result;
}
export function canonical(value){return JSON.stringify(clean(value));}
export function byteLength(value){const text=typeof value==='string'?value:canonical(value);return encodeURIComponent(text).replace(/%[A-F\d]{2}/gi,'x').length;}
export function validateState(state,saveId,reference=null){
 requireValue(exact(state,stateFields));requireValue(uuid.test(saveId)&&state.save_id===saveId,'存档不属于当前宗门。');
 requireValue(state.save_schema_version===1&&integer(state.data_schema_version,1),'存档版本暂不支持。');
 requireValue(typeof state.content_version==='string'&&state.content_version.length>0&&integer(state.generation,1)&&integer(state.revision));
 if(reference){requireValue(state.content_version===reference.content_version&&state.data_schema_version===reference.data_schema_version,'存档内容版本不兼容，请保留原文件。');for(const domain of Object.keys(reference.domains))requireValue(object(state.domains?.[domain]),'存档缺少游戏数据分区。');}
 requireValue(object(state.time)&&object(state.identity)&&object(state.domains));
 for(const key of ['last_settled_at_ms','sim_time_ms'])requireValue(integer(state.time[key]));requireValue(integer(state.time.day_length_ms,1));
 requireValue(state.time.pending===null||object(state.time.pending));requireValue(state.time.world_paused===undefined||typeof state.time.world_paused==='boolean');
 requireValue(integer(state.identity.instance_counter)&&integer(state.identity.event_counter)&&object(state.identity.rng_streams)&&Object.keys(state.identity.rng_streams).length===0);
 for(const key of ['inventory','sect','disciples','production'])requireValue(object(state.domains[key]),'存档缺少完整游戏状态。');
 requireValue(object(state.domains.inventory.holdings)&&object(state.domains.sect.buildings)&&object(state.domains.production.jobs));
 for(const quantity of Object.values(state.domains.inventory.holdings))requireValue(integer(quantity));
 for(const job of Object.values(state.domains.production.jobs)){requireValue(object(job)&&['WORKING','OUTPUT_READY','COMPLETE'].includes(job.status));for(const key of ['started_ms','due_ms','progress_milli'])requireValue(integer(job[key]));for(const key of ['workers','yield_milli','work_rate_milli'])requireValue(integer(job[key],1));requireValue(job.due_ms>=job.started_ms);}
 clean(state);return state;
}
export function validateSave(value,saveId,reference=null){
 requireValue(exact(value,fields));requireValue(value.formatVersion===1,'存档文件版本暂不支持。');
 requireValue(value.saveId===saveId&&uuid.test(value.commitId),'存档标识不正确。');
 requireValue(integer(value.version,1)&&integer(value.updatedAt)&&['server','import'].includes(value.source));
 requireValue(Array.isArray(value.ancestors)&&value.ancestors.length<=128&&new Set(value.ancestors).size===value.ancestors.length);
 requireValue(value.ancestors.every(id=>typeof id==='string'&&uuid.test(id)&&id!==value.commitId));
 validateState(value.state,saveId,reference);requireValue(byteLength(value)<=MAX_SAVE_BYTES,'存档文件过大。');return JSON.parse(canonical(value));
}
export function parseSave(text,saveId,reference=null){requireValue(typeof text==='string'&&byteLength(text)<=MAX_SAVE_BYTES,'存档文件过大。');let value;try{value=JSON.parse(text);}catch{throw new Error('无法读取存档，请检查是否为完整 JSON 文件。');}return validateSave(value,saveId,reference);}
export function makeSave(state,{previous=null,other=null,source=previous?.source||'server',uuid:makeId,now=Date.now}={}){
 const ancestors=[...new Set([previous?.commitId,other?.commitId,...(previous?.ancestors||[]),...(other?.ancestors||[])].filter(Boolean))].slice(0,128);
 const save={formatVersion:1,saveId:state.save_id,version:Math.max(previous?.version||0,other?.version||0)+1,updatedAt:Math.max(now(),previous?.updatedAt||0,other?.updatedAt||0),commitId:makeId(),ancestors,source,state};
 return validateSave(save,state.save_id);
}
export function compareSaves(local,cloud){
 if(!local)return cloud?'cloud':'same';if(!cloud)return 'local';
 if(local.saveId!==cloud.saveId)return 'conflict';
 if(local.commitId===cloud.commitId)return canonical(local)===canonical(cloud)?'same':'conflict';
 if(local.ancestors.includes(cloud.commitId)&&local.version>cloud.version)return 'local';
 if(cloud.ancestors.includes(local.commitId)&&cloud.version>local.version)return 'cloud';
 return 'conflict';
}

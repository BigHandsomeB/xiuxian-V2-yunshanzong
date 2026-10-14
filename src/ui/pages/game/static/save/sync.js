import {canonical,validateSave,validateState,parseSave,makeSave,compareSaves} from './codec.js';

export class SaveCoordinator {
 constructor({client,storage,owner,navigator,uuid,now=Date.now,onChange=()=>{},setInterval:every=globalThis.setInterval,clearInterval:stop=globalThis.clearInterval}){
  Object.assign(this,{client,storage,owner,navigator,uuid,now,onChange,every,stop});this.row={current:null,conflict:null,previous:null,dirty:false,baseVersion:0};this.initialized=false;this.status='正在连接存档';this.uiStamp=0;this.serial=Promise.resolve();this.uploadFlight=null;this.refreshFlight=null;this.captureAgain=false;this.critical=false;
 }
 get canWrite(){return this.initialized&&this.owner.writable&&!this.row.conflict&&!this.recovering;}
 changed(status=this.status){this.status=status;const stamp=JSON.stringify([status,this.owner.writable,this.row.current?.commitId,this.row.conflict?.local?.commitId,this.row.conflict?.cloud?.commitId,this.row.dirty,this.storage.mode,this.persistent,this.recovering]);if(stamp===this.lastUI)return;this.lastUI=stamp;this.uiStamp++;this.onChange(this);}
 queue(task){const next=this.serial.then(task);this.serial=next.catch(()=>{});return next;}
 async persist(row){if(!this.owner.writable)throw new Error('此标签页只读，请在主标签页操作。');await this.storage.write(this.saveId,row);this.row=row;}
 async start(saveId){
  this.saveId=saveId;
  try{await this.load();}catch{this.changed('本地存档无法读取；请保留浏览器数据并导出可用副本。');throw new Error(this.status);}
  await this.owner.start(saveId);this.initialized=true;
  // A queued owner must reload the shared record before issuing any mutation.
  this.owner.onChange=writable=>{if(writable&&this.initialized){this.recovering=true;this.changed();this.queue(async()=>{await this.load();await this.pull();}).catch(()=>this.changed('存档暂不可用，可稍后重试。')).finally(()=>{this.recovering=false;this.changed();});}else this.changed();};
  await this.refreshServer();
  try{this.persistent=await this.navigator?.storage?.persist?.()||false;}catch{this.persistent=false;}
  if(this.every)this.timer=this.every(()=>{this.refreshServer().then(()=>this.flush());},45000);
  this.changed();
 }
 async load(){const row=await this.storage.read(this.saveId);if(!row)return;for(const save of [row.current,row.previous,row.conflict?.local,row.conflict?.cloud])if(save)validateSave(save,this.saveId);if(!Number.isSafeInteger(row.baseVersion)||row.baseVersion<0||typeof row.dirty!=='boolean')throw new Error('本地存档记录损坏。');this.row=row;}
 async reconcile(cloud){
  if(cloud)cloud=validateSave(cloud,this.saveId);
  // An unresolved pair survives reload, even if the remote endpoint is unavailable.
  if(this.row.conflict){if(cloud&&canonical(cloud)!==canonical(this.row.conflict.cloud)){const row={...this.row,conflict:{local:this.row.conflict.local,cloud},previous:this.row.conflict.cloud,baseVersion:cloud.version};if(this.owner.writable)await this.persist(row);else this.row=row;}return;}
  const local=this.row.current,relation=compareSaves(local,cloud);let row;
  if(relation==='conflict')row={...this.row,conflict:{local,cloud},baseVersion:cloud.version};
  else if(relation==='cloud')row={...this.row,current:cloud,previous:local||this.row.previous,dirty:false,baseVersion:cloud.version};
  else row={...this.row,baseVersion:cloud?.version||0,dirty:!!local&&relation==='local'};
  if(this.owner.writable){if(canonical(row)!==canonical(this.row))await this.persist(row);}else this.row=row;
 }
 async pull(){
  const result=await this.client.saveRead();this.serverState=validateState(result.serverState,this.saveId);
  await this.reconcile(result.save);
  if(this.row.conflict){this.changed('本地与云端存档分叉，请到设置选择；两份都可导出。');return;}
  if(!this.owner.writable){this.changed('另一个标签页正在写入，此页只读。');return;}
  const previous=this.row.current;
  if(previous?.source==='import'){this.changed('已保留导入存档；当前游戏仍使用服务器进度。');return;}
  if(previous&&canonical(previous.state)===canonical(this.serverState)){this.changed('存档已保存在本机。');return;}
  if(previous&&(previous.state.generation>this.serverState.generation||(previous.state.generation===this.serverState.generation&&previous.state.revision>this.serverState.revision))){
   const cloud=makeSave(this.serverState,{uuid:this.uuid,now:this.now});await this.persist({...this.row,conflict:{local:previous,cloud}});this.changed('服务器进度与备份不一致，请到设置选择保留的副本。');return;
  }
  const current=makeSave(this.serverState,{previous,uuid:this.uuid,now:this.now});await this.persist({...this.row,current,previous,dirty:true});this.changed('存档已保存在本机。');
 }
 async refreshServer(critical=false){
  this.critical||=critical;if(!this.initialized)return;
  if(this.refreshFlight){this.captureAgain=true;return this.refreshFlight;}
  this.refreshFlight=this.queue(async()=>{do{this.captureAgain=false;await this.pull();}while(this.captureAgain);}).catch(error=>{this.changed(error.login?'云备份需要重新登录；本地副本保留。':'云备份稍后重试，本地副本保留。');}).finally(()=>{this.refreshFlight=null;const upload=this.critical;this.critical=false;if(upload)this.flush();});
  return this.refreshFlight;
 }
 async flush({hidden=false}={}){
  if(this.uploadFlight)return this.uploadFlight;
  this.uploadFlight=this.queue(async()=>{
   if(!this.canWrite||!this.row.dirty||!this.row.current)return;
   const sent=this.row.current,base=this.row.baseVersion;
   try{
    const reply=await this.client.savePut(sent,base,{hidden});validateSave(reply.save,this.saveId);
    if(reply.save.commitId!==sent.commitId||canonical(reply.save)!==canonical(sent))throw new Error('备份响应不匹配。');
    await this.persist({...this.row,baseVersion:reply.save.version,dirty:this.row.current.commitId!==sent.commitId});this.changed('云备份已更新。');
   }catch(error){
    if(error.status===409){try{await this.pull();}catch{this.changed('云端存档变化，读取后再选择；本地副本保留。');}}
    else this.changed(error.login?'云备份需要重新登录；本地副本保留。':error.status===422?'云端校验未通过，请保留导出副本并检查存档。':'云备份稍后重试，本地副本保留。');
   }
  }).finally(()=>{this.uploadFlight=null;});return this.uploadFlight;
 }
 exportText(which='current'){const save=which==='local'?this.row.conflict?.local:which==='cloud'?this.row.conflict?.cloud:which==='previous'?this.row.previous:this.row.current;if(!save)throw new Error('暂时没有可导出的存档。');return canonical(validateSave(save,this.saveId));}
 async choose(which){
  return this.queue(async()=>{if(!this.owner.writable)throw new Error('此标签页只读。');const pair=this.row.conflict;if(!pair||!['local','cloud'].includes(which))throw new Error('没有待选择的存档。');
   const chosen=pair[which],other=pair[which==='local'?'cloud':'local'];
   // Keep the discarded side as previous, and acknowledge both heads in a new commit.
   const current=makeSave(chosen.state,{previous:chosen,other,source:'import',uuid:this.uuid,now:this.now});
   await this.persist({...this.row,current,previous:other,conflict:null,dirty:true});this.changed('已保留所选副本；当前游戏进度仍由服务器管理。');
  }).then(()=>this.flush());
 }
 async importText(text){
  return this.queue(async()=>{if(!this.canWrite)throw new Error('请先在主标签页处理存档选择。');const incoming=parseSave(text,this.saveId,this.serverState||this.row.current?.state);
   // Imported files are staged backups: never replace the live server save or feed the renderer.
   const current=makeSave(incoming.state,{previous:this.row.current,other:incoming,source:'import',uuid:this.uuid,now:this.now});
   await this.persist({...this.row,current,previous:this.row.current,conflict:null,dirty:true});this.changed('导入已保存。当前游戏进度不变，所选存档可再次导出。');
  }).then(()=>this.flush());
 }
 async resumeServerBackup(){return this.queue(async()=>{if(!this.canWrite)throw new Error('请先处理存档选择。');const result=await this.client.saveRead();validateState(result.serverState,this.saveId);await this.reconcile(result.save);if(this.row.conflict)return;const previous=this.row.current,current=makeSave(result.serverState,{previous,source:'server',uuid:this.uuid,now:this.now});await this.persist({...this.row,current,previous,dirty:true});this.serverState=result.serverState;this.changed('已恢复备份当前服务器进度，原副本仍可导出。');}).then(()=>this.flush());}
 describe(){if(!this.owner.writable)return '另一个标签页正在写入，或当前浏览器无法取得独占权；此页只读。';if(this.row.conflict)return '发现分叉，请先导出两份，再选择保留的存档。';return this.status;}
 async suspend(){if(this.timer)this.stop?.(this.timer);this.timer=null;await this.owner.stop();}
 async resume(){await this.owner.start(this.saveId);await this.refreshServer();if(this.every&&!this.timer)this.timer=this.every(()=>this.refreshServer().then(()=>this.flush()),45000);await this.flush();}
}

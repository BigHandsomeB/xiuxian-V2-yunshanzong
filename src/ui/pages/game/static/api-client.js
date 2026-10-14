// HTTP pending intent is separate from the complete save/ backup modules.
export class GameClient {
  constructor({fetcher,storage,uuid,notify=()=>{}}){this.fetcher=fetcher;this.storage=storage;this.uuid=uuid;this.notify=notify;this.current=null;this.active=false;this.key='xianxia-game-pending-v1';}
  assertWriter(){if(this.canWrite&&!this.canWrite()){const error=new Error('此标签页只读，请在主标签页操作或先处理存档分叉。');error.readOnly=true;throw error;}}
  async api(path,body,options={}){if(body&&['command','settle'].includes(path))this.assertWriter();let response,timeout=null,timedOut=false;const controller=typeof AbortController==='function'?new AbortController():null;const external=options.signal;const cancel=()=>controller?.abort();external?.addEventListener?.('abort',cancel,{once:true});if(external?.aborted)cancel();if(controller)timeout=setTimeout(()=>{timedOut=true;controller.abort();},12000);
    try{
      try{response=await this.fetcher('/game/api/'+path,{method:options.method||(body?'POST':'GET'),headers:body?{'Content-Type':'application/json','X-CSRF-Token':this.current.csrf}:{},body:body?JSON.stringify(body):undefined,cache:'no-store',signal:controller?.signal||external,keepalive:options.keepalive||false});}
      catch(cause){if(!timedOut&&(cause.name==='AbortError'||external?.aborted)){const e=new Error('请求已取消。');e.name='AbortError';e.cancelled=true;throw e;}const e=new Error(timedOut?'连接超时，原请求已保留；更新状态可安全重试。':'连接中断，原请求已保留；更新状态可安全重试。');e.transport=true;throw e;}
      let result;try{result=await response.json();}catch(cause){if(!timedOut&&(cause.name==='AbortError'||external?.aborted)){const e=new Error('请求已取消。');e.cancelled=true;e.name='AbortError';throw e;}const e=new Error(response.status===401?'登录状态已失效，请重新登录。':'服务响应暂不可用，请更新状态重试。');e.status=response.status;e.login=response.status===401;e.transport=!e.login&&(response.status>=500||response.ok);throw e;}
      if(!response.ok){if(response.status===409&&typeof console!=='undefined')console.warn('[game:409]',{time:new Date().toISOString(),local_revision:body?.expected_revision??this.current?.view.revision??null,server_revision:result.current_revision??null,source:this.triggerSource||'用户操作',path});const e=new Error(result.error||'请求未完成，请更新状态。');e.code=result.code;e.status=response.status;e.login=response.status===401||result.code==='CSRF';e.transport=response.status>=500;throw e;}return result;
    }finally{if(timeout!==null)clearTimeout(timeout);external?.removeEventListener?.('abort',cancel);}
  }
  saveRead(){return this.api('save');}
  savePut(save,baseVersion,{hidden=false}={}){this.assertWriter();return this.api('save',{save,baseVersion},{method:'PUT',keepalive:hidden});}
  async read(){if(this.readFlight)return this.readFlight;const serial=(this.readSerial||0)+1;this.readSerial=serial;const controller=typeof AbortController==='function'?new AbortController():null;this.readController=controller;
    const task=(async()=>{const incoming=await this.api('view',undefined,{signal:controller?.signal});if(serial!==this.readSerial){const e=new Error('请求已取消。');e.cancelled=true;throw e;}if(incoming.protocol_version!==1)throw new Error('页面协议版本不兼容，请刷新。');if(this.current){const old=this.current.view,next=incoming.view;if(next.save_id!==old.save_id)throw new Error('存档入口已变化，请重新打开页面。');if(next.generation<old.generation||(next.generation===old.generation&&next.revision<old.revision)){const e=new Error('收到旧状态，已保留较新状态，请更新重试。');e.code='STALE_VIEW';e.status=409;throw e;}}this.current=incoming;try{this.onSnapshot?.(incoming.view);}catch{}return this.current;})();this.readFlight=task;
    try{return await task;}finally{if(this.readFlight===task){this.readFlight=null;this.readController=null;}}
  }
  cancelRead(){this.readSerial=(this.readSerial||0)+1;this.readController?.abort();this.readController=null;this.readFlight=null;}
  async poll(advance=false,source='轮询'){return this.lock(async()=>{if(this.canWrite&&!this.canWrite())return this.read();if(!this.current)await this.read();if(this.pending())await this.replay();const v=this.current.view;if(!v.world?.paused&&(advance||v.time.pending||v.economy?.needs_settlement||v.alchemy.current.status==='WORKING')){await this.settleLatest();}else await this.read();return this.current;},source);}
  pending(){const raw=this.storage.getItem(this.key);if(!raw)return null;try{return JSON.parse(raw);}catch{this.storage.removeItem(this.key);return null;}}
  async send(record,{notifyCommit=true}={}){this.assertWriter();this.cancelRead();this.storage.setItem(this.key,JSON.stringify(record));try{const result=await this.api(record.path,record.body);this.cancelRead();this.storage.removeItem(this.key);if(notifyCommit)try{this.onCommitted?.(record.path);}catch{}return result;}catch(error){if(error.status>=400&&error.status<500&&!error.login)this.storage.removeItem(this.key);if(record.path==='command'&&error.status===409&&!error.login)await this.read();throw error;}}
  async replay(){const record=this.pending();if(!record)return;if(record.save_id!==this.current.view.save_id||record.body.generation!==this.current.view.generation){this.storage.removeItem(this.key);this.notify('存档已恢复换代，旧请求已停止，请重新操作。');return;}try{await this.send(record);}catch(error){if(record.path!=='settle'||error.status!==409||error.login)throw error;await this.read();return null;}await this.read();return record;}
  async settle(progressOnly=false){const view=this.current.view;const reply=await this.send({path:'settle',save_id:view.save_id,body:{protocol_version:1,save_id:view.save_id,request_id:this.uuid(),generation:view.generation,expected_revision:view.revision,continuation:view.time.continuation}},{notifyCommit:false});
    // Older servers fall back to view; progress snapshots never enter full-save backup.
    const t=reply.time,c=t?.continuation,validProgress=reply.protocol_version===1&&reply.save_id===view.save_id&&reply.generation===view.generation&&Number.isSafeInteger(reply.revision)&&reply.revision>=view.revision&&reply.receipt?.committed_revision===reply.revision&&typeof t?.pending==='boolean'&&Number.isSafeInteger(t.simulation_time_ms)&&t.simulation_time_ms>=(view.time.simulation_time_ms??view.time.sim_time_ms)&&Number.isSafeInteger(t.target_sim_ms)&&t.target_sim_ms>=t.simulation_time_ms&&t.remaining_ms===t.target_sim_ms-t.simulation_time_ms&&(t.pending?c?.save_id===view.save_id&&c.generation===view.generation&&c.revision===reply.revision&&c.target_sim_ms===t.target_sim_ms&&/^[0-9a-f]{64}$/.test(c.state_fingerprint):c===null);
    if(validProgress){const from=t.from_sim_ms??view.time.from_sim_ms??view.time.simulation_time_ms??view.time.sim_time_ms;
      this.settlementProgress=t.pending?{phase:'catchup',percent:Math.max(0,Math.min(99,Math.floor(100*(t.simulation_time_ms-from)/Math.max(1,t.target_sim_ms-from)))),duration_ms:t.offline_duration_ms,levels_gained:(this.settlementProgress?.levels_gained||0)+(reply.receipt?.result?.levels_gained||0)}:null;
      try{this.onSettlementProgress?.(this.settlementProgress);}catch{}
    }
    if(validProgress&&reply.view&&!reply.time.pending){
      this.current={...this.current,...reply};try{this.onSnapshot?.(reply.view);}catch{}return;
    }
    if(validProgress&&(progressOnly||reply.time.pending)){
      this.current={...this.current,view:{...view,revision:reply.revision,time:{...view.time,...reply.time}}};return;
    }
    await this.read();
  }
  async settleLatest(progressOnly=false){try{await this.settle(progressOnly);return true;}catch(error){if(error.status!==409||error.login)throw error;await this.read();return false;}}
  async lock(task,source='用户操作'){if(this.active)throw new Error('上一次操作尚未完成。');this.active=true;this.triggerSource=source;try{return await task();}finally{this.active=false;this.triggerSource=null;}}
  async sync(advance=true,source='前台恢复'){return this.lock(async()=>{if(!this.current)await this.read();if(this.canWrite&&!this.canWrite())return this.read();await this.replay();if(!this.current.view.world?.paused&&(advance||this.current.view.time.pending||this.current.view.economy?.needs_settlement||this.current.view.alchemy.current.status==='WORKING')){await this.settleLatest();}else await this.read();return this.current;},source);}
  async action(action){if(!['start','assign','unassign'].includes(action))throw new Error('此玩法尚未开放。');return this.lock(async()=>{await this.read();const replayed=await this.replay();await this.settleLatest();if(replayed?.path==='command')return this.current;if(this.current.view.time.pending)throw new Error('离线进度仍在续算，请稍后再操作。');const view=this.current.view;await this.send({path:'command',save_id:view.save_id,body:{protocol_version:1,save_id:view.save_id,request_id:this.uuid(),generation:view.generation,expected_revision:view.revision,command:{name:{start:'alchemy_start',assign:'work_assign',unassign:'work_unassign'}[action],version:1,payload:{}}}});return this.read();});}
  updateCombatProgress(progress){this.combatProgress=progress;try{this.onCombatProgress?.(progress);}catch{}}
  async combat(name,payload){
    if(!['combat_start','combat_attack','combat_abandon','combat_reward','dungeon_auto','dungeon_select'].includes(name))throw new Error('此战斗操作尚未开放。');
    return this.lock(async()=>{try{if(!this.current||['dungeon_auto','dungeon_select'].includes(name))await this.read();const replayed=await this.replay();if(replayed?.path==='command')return this.current;
      if(this.current.view.world?.paused)throw new Error('世界已暂停：战斗及挂机需要时间推进，请先继续运行。');
      if(['dungeon_auto','dungeon_select'].includes(name)){
        const identity=this.current.view;let conflicts=0;
        const progress=(initial=false)=>{const t=this.current.view.time,p=t.pending,sim=t.simulation_time_ms??t.sim_time_ms,from=p?.from_sim_ms??identity.time.simulation_time_ms??identity.time.sim_time_ms,target=t.continuation?.target_sim_ms??p?.target_sim_ms??sim;
          const percent=p?Math.max(0,Math.min(99,Math.floor(100*(sim-from)/Math.max(1,target-from)))):initial?0:100;
          this.updateCombatProgress({phase:'catchup',percent,duration_ms:t.offline_duration_ms,stopping:name==='dungeon_auto'&&payload.enabled===false});};
        progress(true);
        if(!identity.world?.paused)do{
          const before=this.current.view;
          if(before.save_id!==identity.save_id||before.generation!==identity.generation)throw new Error('存档已恢复换代，请重新操作挂机。');
          const settled=await this.settleLatest(true),after=this.current.view;
          progress();
          if(after.save_id!==identity.save_id||after.generation!==identity.generation)throw new Error('存档已恢复换代，请重新操作挂机。');
          if(!settled){if(++conflicts>3)throw new Error('宗门进度持续变化，请稍后重试挂机操作。');continue;}
          if(after.time.pending&&(after.time.simulation_time_ms??after.time.sim_time_ms)<=(before.time.simulation_time_ms??before.time.sim_time_ms)&&
             (after.time.pending.processed_total||0)<=(before.time.pending?.processed_total||0)&&after.revision<=before.revision)
            throw new Error('宗门续算暂未推进，请更新状态后重试。');
        }while(this.current.view.time.pending&&!this.current.view.world?.paused);
      }
      const view=this.current.view;if(view.time.pending)throw new Error('宗门进度正在续算，请先更新状态。');
      this.updateCombatProgress({phase:'command',stopping:name==='dungeon_auto'&&payload.enabled===false});
      const response=await this.send({path:'command',save_id:view.save_id,body:{protocol_version:1,save_id:view.save_id,request_id:this.uuid(),generation:view.generation,expected_revision:view.revision,command:{name,version:1,payload}}});
      this.combatReceipt=response.receipt;return await this.read();
      }finally{this.updateCombatProgress(null);}
    });
  }

  async acknowledgeReport(report_id){return this.lock(async()=>{await this.read();const replayed=await this.replay();if(replayed?.path==='command'&&replayed.body.command?.name==='offline_report_ack')return this.current;
    const view=this.current.view;if(view.time.pending)throw new Error('请先完成离线结算，再收下报告。');
    await this.send({path:'command',save_id:view.save_id,body:{protocol_version:1,save_id:view.save_id,request_id:this.uuid(),generation:view.generation,expected_revision:view.revision,command:{name:'offline_report_ack',version:1,payload:{report_id}}}});return this.read();
  });}

  async world(name){
    if(!['world_pause','world_resume'].includes(name))throw new Error('世界操作无效');
    return this.lock(async()=>{
      await this.read();const replayed=await this.replay();
      if(replayed?.path==='command'&&replayed.body.command?.name===name)return this.current;
      const identity=this.current.view;let conflicts=0;
      if(name==='world_pause'&&!identity.world?.paused)this.notify('正在处理宗门进度，完成后自动暂停。');
      for(;;){
        if(name==='world_pause'&&!this.current.view.world?.paused){
          // Complete the fixed pending target. Even without a cursor, settle fresh wall backlog first.
          do{
            const before=this.current.view;
            if(before.save_id!==identity.save_id||before.generation!==identity.generation)throw new Error('存档已恢复换代，请重新操作暂停。');
            if(!await this.settleLatest(true)){
              if(++conflicts>3)throw new Error('宗门进度持续变化，请稍后重试暂停。');
              continue;
            }
            const after=this.current.view;
            if(after.save_id!==identity.save_id||after.generation!==identity.generation)throw new Error('存档已恢复换代，请重新操作暂停。');
            if(after.time.pending&&(after.time.simulation_time_ms??after.time.sim_time_ms)<=(before.time.simulation_time_ms??before.time.sim_time_ms)&&
               (after.time.pending.processed_total||0)<=(before.time.pending?.processed_total||0)&&after.revision<=before.revision)
              throw new Error('宗门续算暂未推进，请更新状态后重试。');
          }while(this.current.view.time.pending&&!this.current.view.world?.paused);
        }
        const v=this.current.view;
        if(v.save_id!==identity.save_id||v.generation!==identity.generation)throw new Error('存档已恢复换代，请重新操作暂停。');
        await this.send({path:'command',save_id:v.save_id,body:{protocol_version:1,save_id:v.save_id,request_id:this.uuid(),generation:v.generation,expected_revision:v.revision,command:{name,version:1,payload:{}}}});
        return this.read();
      }
    });
  }
  async cultivation(name,payload={}){
    if(!['cultivation_train','cultivation_breakthrough','cultivation_use_pill'].includes(name))throw new Error('此修炼操作尚未开放。');
    return this.lock(async()=>{await this.read();const replayed=await this.replay();if(replayed?.path==='command')return this.current;
      const view=this.current.view;if(view.time.pending)throw new Error('宗门进度正在续算，请先更新状态。');
      const response=await this.send({path:'command',save_id:view.save_id,body:{protocol_version:1,save_id:view.save_id,request_id:this.uuid(),generation:view.generation,expected_revision:view.revision,command:{name,version:1,payload}}});
      this.cultivationReceipt=response.receipt;return this.read();
    });
  }
  async economy(name,payload){
    if(!['sect_commission_claim','sect_contribution_exchange','boss_chest_open','technique_equip','technique_unequip','technique_buy','technique_claim','technique_exchange','market_order','market_bid','market_auction_claim','market_consign','market_consignment_claim','sect_recruit','sect_supply','sect_facility_build','material_sell','material_reserve','equipment_enhance','sect_stone_buy','market_buy','production_start','work_assign','work_unassign','work_reassign','automation_production','automation_equipment','material_overflow','building_upgrade','equipment_craft','equipment_equip','equipment_unequip','equipment_lock','equipment_favorite','equipment_sell','equipment_salvage','equipment_sell_all','equipment_salvage_all'].includes(name))throw new Error('此经营操作尚未开放。');
    return this.lock(async()=>{await this.read();const replayed=await this.replay();if(replayed?.path==='command')return this.current;
      if(this.current.view.world?.paused&&['market_bid','market_consign','market_auction_claim','market_consignment_claim'].includes(name))throw new Error('世界已暂停：拍卖依赖时间与清算，请先继续运行。');
      const bulkEquipment=name==='equipment_sell_all'||name==='equipment_salvage_all';
      // Keep the confirmed equipment selection stable; catch-up may award new equipment.
      if(!bulkEquipment&&!this.current.view.world?.paused){await this.settleLatest();for(let n=0;n<3&&this.current.view.time.pending;n++)await this.settleLatest();}
      const view=this.current.view;if(view.time.pending)throw new Error('宗门进度正在续算，请更新状态后重试。');
      const response=await this.send({path:'command',save_id:view.save_id,body:{protocol_version:1,save_id:view.save_id,request_id:this.uuid(),generation:view.generation,expected_revision:view.revision,command:{name,version:1,payload}}});this.economyReceipt=response.receipt;await this.read();
      if(name.startsWith('automation_')&&!this.current.view.world?.paused){await this.settleLatest();}
      return this.current;
    });
  }

}

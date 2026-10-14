// No heartbeat expiry: a frozen Safari tab must never lose its write ownership to a timer.
export class SaveOwnership {
 constructor({navigator,Channel,storage,uuid,onChange=()=>{}}){this.navigator=navigator;this.Channel=Channel;this.storage=storage;this.id=uuid();this.onChange=onChange;this.writable=false;this.epoch=0;}
 set(value){if(this.writable!==value){this.writable=value;this.onChange(value);}}
 async start(saveId){
  this.saveId=saveId;const epoch=++this.epoch;this.set(false);
  if(this.navigator?.locks?.request){
   const ready=new Promise(resolve=>{this.navigator.locks.request('xianxia-save:'+saveId,{ifAvailable:true},async lock=>{if(epoch!==this.epoch){resolve(false);return;}if(!lock){resolve(false);return;}this.set(true);resolve(true);await new Promise(done=>{this.releaseLock=done;});}).catch(()=>resolve(false));});
   if(!await ready&&epoch===this.epoch)this.wait(epoch);return this.writable;
  }
  // BroadcastChannel announces release; an IndexedDB transaction arbitrates simultaneous claims.
  // If atomic arbitration is unavailable, remain read-only instead of risking two writers.
  if(this.Channel){try{this.channel=new this.Channel('xianxia-save:'+saveId);this.channel.onmessage=event=>{if(event.data?.type==='released'&&!this.writable&&epoch===this.epoch)this.claim(epoch);};await this.claim(epoch);}catch{this.set(false);}}
  return this.writable;
 }
 wait(epoch){this.controller=typeof AbortController==='function'?new AbortController():null;this.navigator.locks.request('xianxia-save:'+this.saveId,{...(this.controller?{signal:this.controller.signal}:{})},async lock=>{if(epoch!==this.epoch||!lock)return;this.set(true);await new Promise(done=>{this.releaseLock=done;});}).catch(()=>{});}
 async claim(epoch){const claimed=await this.storage.claim(this.saveId,this.id);if(epoch!==this.epoch){if(claimed)await this.storage.release(this.saveId,this.id);return;}this.set(claimed);}
 async stop(){++this.epoch;this.controller?.abort();this.releaseLock?.();this.releaseLock=null;const wasOwner=this.writable;this.set(false);if(wasOwner&&this.channel){await this.storage.release(this.saveId,this.id);this.channel.postMessage({type:'released'});}this.channel?.close();this.channel=null;}
}

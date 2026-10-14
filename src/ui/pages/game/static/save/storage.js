// One atomic record keeps the current snapshot and both sides of an unresolved conflict.
export class SaveStorage {
 constructor({indexedDB,localStorage,timeout=2500}){this.indexedDB=indexedDB;this.localStorage=localStorage;this.timeout=timeout;this.mode='未连接';this.db=null;this.openFlight=null;this.fallback=false;}
 key(saveId){return 'xianxia-local-save-v1:'+saveId;}
 async open(){
  if(this.fallback||!this.indexedDB){this.mode='localStorage';return null;}if(this.db)return this.db;if(this.openFlight)return this.openFlight;
  this.openFlight=new Promise(resolve=>{let ended=false;const finish=db=>{if(ended){db?.close();return;}ended=true;clearTimeout(timer);this.db=db;this.fallback=!db;this.mode=db?'IndexedDB':'localStorage';resolve(db);};const timer=setTimeout(()=>finish(null),this.timeout);
   try{const req=this.indexedDB.open('xianxia-saves-v1',1);req.onupgradeneeded=()=>{for(const name of ['saves','owners'])if(!req.result.objectStoreNames.contains(name))req.result.createObjectStore(name);};req.onsuccess=()=>{const db=req.result;db.onversionchange=()=>{db.close();this.db=null;this.fallback=true;};finish(db);};req.onerror=()=>finish(null);req.onblocked=()=>finish(null);}catch{finish(null);}
  });return this.openFlight;
 }
 async transaction(store,mode,operation){const db=await this.open();if(!db)throw new Error('IndexedDB unavailable');return new Promise((resolve,reject)=>{let value;const tx=db.transaction(store,mode),timer=setTimeout(()=>{try{tx.abort();}catch{}reject(new Error('本地存储超时。'));},this.timeout);tx.oncomplete=()=>{clearTimeout(timer);resolve(value);};tx.onabort=tx.onerror=()=>{clearTimeout(timer);reject(tx.error||new Error('本地存储未完成。'));};try{operation(tx.objectStore(store),v=>{value=v;});}catch(error){clearTimeout(timer);tx.abort();reject(error);}});}
 async read(saveId){
  let raw;try{raw=this.localStorage?.getItem(this.key(saveId));}catch{raw=null;}const mirror=raw?JSON.parse(raw):null;
  if(mirror?.fallback){this.fallback=true;this.mode='localStorage';return mirror.data;}
  const db=await this.open();if(db)try{const row=await this.transaction('saves','readonly',(store,done)=>{const req=store.get(saveId);req.onsuccess=()=>done(req.result||null);});if(row)return row;}catch{this.fallback=true;this.mode='localStorage';}
  return mirror?.data||null;
 }
 async write(saveId,row){
  let saved=false;
  if(await this.open())try{await this.transaction('saves','readwrite',store=>store.put(row,saveId));saved=true;}catch{this.fallback=true;this.mode='localStorage';}
  try{if(!this.localStorage){if(!saved)throw new Error('无法保存本地存档。');}else this.localStorage.setItem(this.key(saveId),JSON.stringify({data:row,fallback:!saved}));}catch(error){if(!saved)throw error;}
 }
 async claim(saveId,owner){try{return await this.transaction('owners','readwrite',(store,done)=>{const req=store.get(saveId);req.onsuccess=()=>{if(!req.result||req.result===owner){store.put(owner,saveId);done(true);}else done(false);};});}catch{return false;}}
 async release(saveId,owner){try{await this.transaction('owners','readwrite',store=>{const req=store.get(saveId);req.onsuccess=()=>{if(req.result===owner)store.delete(saveId);};});}catch{} }
}

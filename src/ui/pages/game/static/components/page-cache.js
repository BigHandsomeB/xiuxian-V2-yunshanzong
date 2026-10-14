// Bounded session-memory cache of views, never authoritative world/save data.
export function pageCache(limit=6){
 const entries=new Map();
 const dispose=entry=>{if(typeof entry.controller==='function')entry.controller();else entry.controller?.dispose?.();};
 return {
  get(key){const entry=entries.get(key);if(entry){entries.delete(key);entries.set(key,entry);}return entry;},
  put(key,entry){if(entries.has(key)&&entries.get(key)!==entry)dispose(entries.get(key));entries.delete(key);entries.set(key,entry);while(entries.size>limit){const oldest=entries.keys().next().value;dispose(entries.get(oldest));entries.delete(oldest);}},
  delete(key){const entry=entries.get(key);if(entry)dispose(entry);entries.delete(key);},
  clearExcept(key){for(const id of [...entries.keys()])if(id!==key)this.delete(id);},
  get size(){return entries.size;}
 };
}

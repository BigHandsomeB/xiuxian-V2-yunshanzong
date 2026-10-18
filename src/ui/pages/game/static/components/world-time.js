// Display-only interpolation. Python remains the authority for time and all rewards.
export class WorldTimeline {
 constructor(snapshot,now){this.update(snapshot,now);}
 update(snapshot,now){
  const stamp=JSON.stringify([snapshot.save_id,snapshot.generation,snapshot.simulation_time_ms,snapshot.day_length_ms,snapshot.paused,snapshot.pending]);
  if(stamp===this.stamp)return false;
  const old=this.snapshot,previous=old?this.sample(now).time:null;
  this.snapshot={...snapshot};this.stamp=stamp;this.anchor=now;
  this.valid=Number.isFinite(snapshot.simulation_time_ms)&&snapshot.simulation_time_ms>=0&&Number.isFinite(snapshot.day_length_ms)&&snapshot.day_length_ms>0;
  this.base=this.valid?snapshot.simulation_time_ms:0;
  this.from=previous!==null&&old.save_id===snapshot.save_id&&old.generation===snapshot.generation&&!snapshot.paused&&!snapshot.pending?previous:this.base;
  return true;
 }
 sample(now){
  const elapsed=Math.max(0,now-this.anchor),s=this.snapshot,running=this.valid&&!s.paused&&!s.pending;
  const advanced=running?Math.min(elapsed,10000):0,target=this.base+advanced;
  const blend=running?Math.min(1,elapsed/200):1;
  return {time:Math.max(0,this.from+(target-this.from)*blend),valid:this.valid,animated:running&&elapsed<10000};
 }
}
export function animateWorldTime(root){
 const win=root.ownerDocument?.defaultView||globalThis.window;
 let nodes=[],frame=null,suspended=false,disposed=false;
 const now=()=>globalThis.performance?.now?.()||0;
 function stop(){if(frame!==null)win?.cancelAnimationFrame?.(frame);frame=null;}
 function tick(){frame=null;if(suspended||disposed||root.ownerDocument?.hidden)return;
  let active=false;for(const node of nodes)active=node.__worldTime.paint(now())||active;
  if(active&&win?.requestAnimationFrame)frame=win.requestAnimationFrame(tick);
 }
 return {refresh(){nodes=[...(root.__worldTime?[root]:[]),...Array.from(root.querySelectorAll?.('.sect-world-time')||[])].filter(n=>n.__worldTime);stop();tick();},
  suspend(){suspended=true;stop();},resume(){suspended=false;stop();tick();},dispose(){disposed=true;stop();}};
}

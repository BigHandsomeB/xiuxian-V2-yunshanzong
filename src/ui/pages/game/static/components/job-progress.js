import {el} from './dom.js';
// Browser-only display estimate. No Domain time, inventory, commands or completion.
export class JobTimeline {
 constructor(snapshot,now){this.last=0;this.update(snapshot,now);}
 update(snapshot,now){const previous=this.snapshot?this.sample(now).fraction:null;const stamp=JSON.stringify([snapshot.job_id,snapshot.revision,snapshot.generation,snapshot.progress,snapshot.total,snapshot.remaining_ms,snapshot.status,snapshot.paused,snapshot.pending]);if(stamp===this.stamp)return false;
 this.snapshot={...snapshot};this.stamp=stamp;this.anchor=now;this.base=Math.min(1,Math.max(0,snapshot.progress/snapshot.total));this.duration=Math.max(0,snapshot.remaining_ms);this.from=previous===null||snapshot.job_id!==this.id||snapshot.paused?this.base:previous;this.id=snapshot.job_id;return true;
 }
 sample(now){const s=this.snapshot,elapsed=Math.max(0,now-this.anchor),running=s.status==='WORKING'&&!s.paused&&!s.pending;const advanced=running?Math.min(elapsed,this.duration):0;const target=Math.min(1,this.base+advanced*(s.rate||1000)/s.total);const correction=running?Math.min(1,elapsed/250):1;const fraction=this.from+(target-this.from)*correction;return {fraction:Math.max(0,Math.min(1,fraction)),remaining_ms:Math.max(0,this.duration-advanced),waiting:running&&advanced>=this.duration,animated:running&&advanced<this.duration};}
 }
export function jobProgress(snapshot){const root=el('div','job-progress');root.dataset.progressJob=snapshot.job_id;const meter=el('progress','job-progress-meter'),track=el('div','job-progress-track'),fill=el('div','job-progress-fill'),caption=el('p','progress-caption');meter.max=1;meter.setAttribute('aria-label',snapshot.label||'生产进度');fill.setAttribute('aria-hidden','true');track.append(fill);root.append(meter,track,caption);const now=()=>(typeof performance!=='undefined'?performance.now():0);let timeline=new JobTimeline(snapshot,now()),seconds=null;
 function paint(t){const v=timeline.sample(t),s=timeline.snapshot;fill.style.transform=`scaleX(${v.fraction})`;root.dataset.paused=String(!!s.paused);const next=Math.ceil(v.remaining_ms/1000),text=s.paused?`世界暂停 · 余下 ${next} 秒`:s.status==='OUTPUT_READY'?'产物已成，等待仓库入库':s.status==='COMPLETE'?'生产已完成，产物已入库':s.pending?'正在同步世界进度':v.waiting?'进度已满，等待世界确认':`生产中 · 余下 ${next} 秒`;
 if(next!==seconds||caption.textContent!==text){seconds=next;caption.textContent=text;meter.value=v.fraction;meter.setAttribute('aria-valuetext',text);}return v.animated;
 }
 root.__jobProgress={get snapshot(){return timeline.snapshot;},update(s){if(timeline.update(s,now()))paint(now());},paint};paint(now());return root;
}
function progressNodes(root){const found=[];function visit(n){if(n.__jobProgress)found.push(n);else for(const c of n.children||[])visit(c);}visit(root);return found;}
export function animateJobs(root){let frame=null,suspended=false,disposed=false,nodes=progressNodes(root);const win=document.defaultView||window,now=()=>(typeof performance!=='undefined'?performance.now():0);
 function stop(){if(frame!==null)win.cancelAnimationFrame(frame);frame=null;}
 function tick(){frame=null;if(suspended||disposed||document.hidden)return;let active=false;for(const n of nodes)active=n.__jobProgress.paint(now())||active;if(active)frame=win.requestAnimationFrame(tick);}
 return {refresh(){nodes=progressNodes(root);if(!suspended&&!disposed){stop();tick();}},suspend(){suspended=true;stop();},resume(){suspended=false;stop();tick();},dispose(){disposed=true;stop();}};
}
export function productionSnapshot(ctx,job,total,remaining_ms,label){return {job_id:job.job_id,revision:ctx.data.view.revision,generation:ctx.data.view.generation,progress:job.progress_milli,total,remaining_ms,rate:job.work_rate_milli,status:job.status,paused:!!ctx.data.view.world?.paused,pending:!!ctx.data.view.time.pending,label};}

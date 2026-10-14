export function testPageCache(source,lifecycleSource){
 const {pageCache}=new Function(source.replace(/^export /gm,'')+';return {pageCache};')();
 const {screenLifecycle}=new Function(lifecycleSource.replace(/^export /gm,'')+';return {screenLifecycle};')();
 let checks=0;const assert=(v,m)=>{if(!v)throw Error(m);checks++;};let disposed=0,paused=0,resumed=0;
 const make=()=>{const controller=()=>disposed++;controller.suspend=()=>paused++;controller.resume=()=>resumed++;return {node:{},ctx:{},controller};};
 const cache=pageCache(2),a=make(),b=make(),c=make(),life=screenLifecycle();cache.put('battle',a);life.mount(a.controller);life.detach();
 assert(paused===1&&disposed===0,'Leaving cached battle suspends without disposing');
 cache.put('sect',b);life.mount(b.controller);life.detach();assert(cache.get('battle')===a,'Revisit returns original DOM/controller');
 life.mount(a.controller);life.resume();assert(resumed===1&&disposed===0,'Cached controller resumes once');
 cache.put('inventory',c);assert(cache.size===2&&!cache.get('sect')&&disposed===1,'Cache bounded with oldest disposal');
 cache.clearExcept('battle');assert(cache.size===1&&cache.get('battle')===a&&disposed===2,'Asset reload can discard inactive views');
 life.detach();cache.delete('battle');assert(disposed===3&&cache.size===0,'Explicit redraw disposes old view once');
 return {tests:checks,status:'PASS'};
}

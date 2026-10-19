// Native JS behavior checks; no claim about Safari painting.
async function testStartup(source){
 const {waitForImages,startupScreen,enterSect}=new Function('setTimeout','clearTimeout',source.replace(/export /g,'')+';return {waitForImages,startupScreen,enterSect};')(setTimeout,clearTimeout);
 let checks=0;const assert=(ok,message)=>{if(!ok)throw Error(message);checks++;};
 const img=(complete=false)=>{const listeners={load:new Set(),error:new Set()};return {complete,listeners,addEventListener:(k,f)=>listeners[k].add(f),removeEventListener:(k,f)=>listeners[k].delete(f),emit(k){this.complete=true;for(const f of [...listeners[k]])f();}};};
 let target='';const state={existing:true};enterSect({pathname:'/game/',search:'?debug=icons',hash:'#settings'},{state,replaceState(s,unused,url){if(s!==state)throw Error('History state lost');target=url;}});assert(target==='/game/?debug=icons#sect','Fresh entry replaces settings hash, preserves query and history state');
 const cached=img(true);await waitForImages({querySelectorAll:()=>[cached]});assert(!cached.listeners.load.size,'Cached images finish immediately');
 const first=img(),second=img();let done=false;const task=waitForImages({querySelectorAll:()=>[first,second]}).then(()=>done=true);
 first.emit('load');await Promise.resolve();assert(!done,'Wait for every pending homepage image');assert(first.loading==='eager'&&second.loading==='eager','Start lazy homepage icons behind the cover');second.emit('error');await task;assert(done,'Image errors do not block entry');assert(!first.listeners.load.size&&!second.listeners.error.size,'Remove listeners after completion');
 const slow=img();await waitForImages({querySelectorAll:()=>[slow]},1);assert(!slow.listeners.load.size,'Timeout releases entry and listeners');
 const pending=img(),art=img(),cover={hidden:false,querySelectorAll:()=>[art]},shell={querySelectorAll:()=>[pending],removeAttribute(k){delete this[k];},inert:true,'aria-hidden':true},message={},retry={hidden:true},body={classList:{remove(k){this.removed=k;}}};
 const nodes={startup:cover,'startup-message':message,'startup-retry':retry};const doc={getElementById:id=>nodes[id],querySelector:()=>shell,body};const startup=startupScreen(doc);
 let entered=false;const finish=startup.finish().then(()=>entered=true);await Promise.resolve();assert(!entered&&!cover.hidden,'Keep splash while icons load');pending.emit('load');await Promise.resolve();assert(!cover.hidden,'Keep artwork visible until its own image is ready');art.emit('load');await finish;assert(cover.hidden&&!shell.inert&&!shell['aria-hidden'],'Reveal accessible homepage after images finish');await startup.finish();assert(entered,'Repeated finish is harmless');
 cover.hidden=false;const failed=startupScreen(doc);failed.fail({login:true});assert(!retry.hidden&&message.textContent.includes('重新登录'),'Expired login has recovery');failed.fail({transport:true});assert(message.textContent.includes('网络'),'Network failure has recovery');
 const review=startupScreen({...doc,getElementById:()=>null});await review.finish();review.fail({});assert(true,'Review without splash is unchanged');return {checks};
}

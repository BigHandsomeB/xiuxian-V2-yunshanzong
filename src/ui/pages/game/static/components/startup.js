export function enterSect(location,history){history.replaceState(history.state,'',location.pathname+location.search+'#sect');}
// Initial entry only: wait for the mounted homepage icons, with a bounded wait.
export function waitForImages(root,timeout=6000){
 const mounted=[...root.querySelectorAll('img')];
 for(const image of mounted)image.loading='eager';
 const images=mounted.filter(image=>!image.complete);
 if(!images.length)return Promise.resolve();
 return new Promise(resolve=>{
  let remaining=images.length,finished=false;const cleanups=[];
  const done=()=>{if(finished)return;finished=true;clearTimeout(timer);for(const clean of cleanups)clean();resolve();};
  const timer=setTimeout(done,timeout);
  for(const image of images){
   let settled=false;const settle=()=>{if(settled)return;settled=true;if(--remaining===0)done();};
   image.addEventListener('load',settle);image.addEventListener('error',settle);
   cleanups.push(()=>{image.removeEventListener('load',settle);image.removeEventListener('error',settle);});
   if(image.complete)settle();
  }
 });
}
export function startupScreen(doc){
 const cover=doc.getElementById('startup'),shell=doc.querySelector('.game-shell');
 let ready=false;
 return {
  async finish(){if(ready||!cover)return;await waitForImages({querySelectorAll:selector=>[...shell.querySelectorAll(selector),...cover.querySelectorAll(selector)]});ready=true;cover.hidden=true;shell.removeAttribute('inert');shell.removeAttribute('aria-hidden');doc.body.classList.remove('game-starting');},
  fail(error){if(ready||!cover)return;doc.getElementById('startup-message').textContent=error.login?'登录已过期，请重新登录。':'加载暂未完成，请检查网络后重试。';doc.getElementById('startup-retry').hidden=false;},
 };
}

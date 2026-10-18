const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
let onClick,opened=0;
let completed,loads=0,created=0,fail=false;const window={};
function QWebChannel(transport,callback){callback({objects:{desktop:{completed:{connect:f=>completed=f},
 open_manager:(id)=>{opened++;queueMicrotask(()=>completed(id,'{"ok":true}'));},
 asset:(id,path)=>{loads++;queueMicrotask(()=>completed(id,JSON.stringify(fail?{status:404}:{status:200,mime:'image/png',base64:Buffer.from('png').toString('base64')})));},
 request:(id,payload)=>queueMicrotask(()=>completed(id,JSON.stringify({status:200,body:'{"ok":true}'})))
}}});}
vm.runInNewContext(fs.readFileSync('src/ui/pages/game/static/desktop-bridge.js','utf8'),{document:{addEventListener:(event,handler)=>{if(event==='click')onClick=handler;}},window,QWebChannel,qt:{webChannelTransport:{}},DOMException,atob,Uint8Array,Blob,URL:{createObjectURL:()=> 'blob:icon-'+(++created)}});
const {setIconSource}=new Function(fs.readFileSync('src/ui/pages/game/static/components/icon-loading.js','utf8').replace(/^export /gm,'')+';return {setIconSource};')();
const url='/game/runtime/icon.test/'+'a'.repeat(64),newURL=url.replace(/a{64}$/,'b'.repeat(64));
async function run(){
 let prevented=false;
 onClick({target:{closest:selector=>selector==='a[href="/tools/assets/"]'},preventDefault:()=>prevented=true});
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(opened,1,'game settings opens the native asset manager');assert.equal(prevented,true);

 const a=window.desktopIconURL(url),b=window.desktopIconURL(url);
 assert.equal(a,b,'concurrent icons share one load');
 const source=await a;assert.equal(loads,1);assert.equal(created,1);
 assert.equal(window.desktopIconURL(url),source,'warm icon URL returned synchronously');
 for(let i=0;i<30;i++){
  const image={dataset:{},ownerDocument:{defaultView:window}};setIconSource(image,url);
  assert.equal(image.src,source,'remounted icon keeps the same decoded source');assert.equal(image.loading,'eager');
 }
 assert.equal(loads,1,'page changes do not reload cached artwork');
 assert.notEqual(await window.desktopIconURL(newURL),source,'new digest loads updated artwork');assert.equal(loads,2);
 assert.equal(window.desktopIconURL('/game/api/view'),'/game/api/view','no API data enters artwork cache');
 fail=true;const missing=url.replace(/a{64}$/,'c'.repeat(64));await assert.rejects(window.desktopIconURL(missing));
 fail=false;await window.desktopIconURL(missing);assert.equal(loads,4,'failed load can retry');
 const image={dataset:{},ownerDocument:{defaultView:window}};
 setIconSource(image,url.replace(/a{64}$/,'d'.repeat(64)));setIconSource(image,newURL);
 await new Promise(r=>setTimeout(r,0));assert.equal(image.src,window.desktopIconURL(newURL),'late image completion cannot overwrite newer source');
 assert.equal((await (await window.fetch('/game/api/view')).json()).ok,true);
 console.log('desktop icons: coalescing, 30 remounts, version updates, failure retry, stale load and API isolation PASS');
}
run().catch(e=>{console.error(e);process.exitCode=1;});

const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
let complete,reply,requests=[];const window={};
function QWebChannel(transport,callback){callback({objects:{desktop:{completed:{connect:f=>complete=f},request:(id,raw)=>{requests.push(JSON.parse(raw));queueMicrotask(()=>complete(id,JSON.stringify(reply)));}}}});}
vm.runInNewContext(fs.readFileSync('src/ui/pages/game/static/desktop-bridge.js','utf8'),{window,document:{addEventListener(){}},QWebChannel,qt:{webChannelTransport:{}},DOMException,atob,Uint8Array,Blob,URL});
async function call(value){reply={status:200,body:JSON.stringify(value)};return (await window.fetch('/game/api/view')).json();}
(async()=>{
 const first=await call({view:{revision:1},presentation:{desktop_ref:1,projection:{icons:{test:'icon'}}}});
 const second=await call({view:{revision:2},presentation:{desktop_ref:1}});
 assert.equal(second.presentation,first.presentation,'immutable artwork is shared');assert.equal(second.view.revision,2,'gameplay data always comes from fresh authority');
 assert.equal(requests[0].presentation_ref,0);assert.equal(requests[1].presentation_ref,1);
 const third=await call({view:{revision:3},presentation:{desktop_ref:2,projection:{icons:{test:'new'}}}});assert.equal(third.presentation.icons.test,'new');
 reply={status:401,body:'<html>login</html>'};const response=await window.fetch('/game/api/view');assert.equal(response.status,401);await assert.rejects(()=>response.json());
 console.log('desktop projection: reuse, fresh state, invalidation and authentication error semantics PASS');
})().catch(e=>{console.error(e);process.exitCode=1;});

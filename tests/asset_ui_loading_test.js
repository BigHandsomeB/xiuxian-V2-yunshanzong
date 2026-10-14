// Actual startup functions with a delayed API, including navigation before first load.
async function testAssetUiLoading(source) {
 const refresh=source.slice(source.indexOf('async function refresh()'),source.indexOf('function open('));
 const route=source.match(/async function route\(\)\{[^\n]+/)[0];
 const body='let state,stateRequest;'+refresh+route+'\nreturn {route,refresh};';
 let release,calls=0,renders=0;
 const payload={templates:[{template_id:'character_compact_v1'}]};
 const pending=new Promise(resolve=>release=resolve);
 const ui=new Function('api','location','promptPage',body)(async()=>{calls++;return pending;},{hash:'#prompt'},()=>renders++);
 const first=ui.refresh(),second=ui.route();
 await Promise.resolve();
 if(renders!==0||calls!==1)throw Error('Navigation rendered before shared state loaded');
 release(payload);await Promise.all([first,second]);
 if(renders!==1)throw Error('Prompt route did not render after loading');
 let attempts=0;
 const retry=new Function('api','location','promptPage',body)(async()=>{if(++attempts===1)throw Error('network unavailable');return payload;},{hash:'#prompt'},()=>{});
 try{await retry.route();throw Error('Expected initial loading failure');}catch(e){if(e.message!=='network unavailable')throw e;}
 await retry.route();if(attempts!==2)throw Error('Failed loading could not retry');
 return 'PASS: early navigation waits, state fetch is shared, failed loading can retry';
}

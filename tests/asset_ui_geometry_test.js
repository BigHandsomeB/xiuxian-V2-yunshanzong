// Drives actual staticSlice handlers in native JS. Not a real phone visual test.
async function testAssetUiGeometry(source,fixture){
 const clone=x=>JSON.parse(JSON.stringify(x));
 const nodes=new Map(),grid=[],maps=[],coordinates=[],buttons=[],drawn=[];
 const attrs=s=>Object.fromEntries([...s.matchAll(/([\w-]+)="([^"]*)"/g)].map(m=>[m[1],m[2]]));
 function node(){return {value:'',disabled:false,dataset:{},textContent:'',isConnected:true,_html:'',querySelectorAll(selector){if(this===find('#static-grid'))return grid;if(selector==='[data-static-map]')return maps;if(selector==='[data-coordinate]')return coordinates;return buttons.filter(n=>{let key=selector.slice(6,-1).replace(/-([a-z])/g,(_,c)=>c.toUpperCase());return n.dataset[key]!==undefined;});},get innerHTML(){return this._html;},set innerHTML(html){this._html=html;parse(html,this===find('#static-mapping'));}};}
 function find(s){if(!nodes.has(s))nodes.set(s,node());return nodes.get(s);}
 function parse(html,mapping){if(mapping){maps.length=0;coordinates.length=0;buttons.length=0;}for(let m of html.matchAll(/<(input|select|button|canvas|p|section|details)\b([^>]*)>/g)){const a=attrs(m[2]);let n=node();n.value=a.value||'';n.name=a.name;for(let [k,v] of Object.entries(a))if(k.startsWith('data-'))n.dataset[k.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase())]=v;if(a.id)nodes.set('#'+a.id,n);if(m[1]==='select'){const options=html.slice(m.index).match(/^<select[^>]*>([\s\S]*?)<\/select>/)?.[1]||'';n._html=options;const opts=[...options.matchAll(/<option value="([^"]*)"([^>]*)>/g)];n.value=(opts.find(m=>m[2].includes('selected'))||opts[0])?.[1]||'';}if(n.dataset.staticMap!==undefined)maps.push(n);if(n.dataset.coordinate!==undefined)coordinates.push(n);if(Object.keys(n.dataset).some(k=>k.startsWith('region')||k.startsWith('polygon')))buttons.push(n);for(let [k,v] of Object.entries(a))if(k.startsWith('data-polygon-'))nodes.set(`[${k}="${v}"]`,n);if(n.name&&fixture.source.frozen_spec.grid_spec[n.name]!==undefined)grid.push(n);if(m[1]==='canvas'){n.getBoundingClientRect=()=>({left:0,top:0,width:300,height:200});n.setPointerCapture=()=>{};n.getContext=()=>({drawImage(){},beginPath(){},moveTo(){},lineTo(){},closePath(){},stroke(){},strokeRect(...a){drawn.push(a);},fillRect(){},fillText(text){drawn.push(text);},measureText(text){return {width:text.length*12};}});}}}
 const timers=new Map();let timerID=0,quickCalls=0;let calls=0,pending=false,lastPlan=null,lastLocate=null;const api=async(path,body)=>{if(path==='auto-locate'){lastLocate=clone(body);calls++;if(pending)await new Promise(resolve=>{pending=resolve;});return clone(fixture.detection);}if(path==='quick-preview'){quickCalls++;return {preview_id:'isolated-preview'};}if(path==='plan'){lastPlan=clone(body);return {...body,static_collection:true};}throw Error('Unexpected API '+path);};
 class ImageStub{set src(v){Promise.resolve().then(()=>this.onload());}}
 const block=source.slice(source.indexOf('function staticSlice('),source.indexOf('async function route('));
 const page=new Function('$','close','specSummary','options','field','label','esc','Image','BASE','api','run','setTimeout','clearTimeout','quickReview',block+';return staticSlice;')(find,()=>{},()=>'',(items,value)=>items.map(([id,name])=>`<option value="${id}" ${id===value?'selected':''}>${name}</option>`).join(''),(id,name,v)=>`<input name="${id}" value="${v}">`,x=>x,x=>String(x),ImageStub,'/tools/assets',api,fn=>Promise.resolve().then(fn),fn=>{timers.set(++timerID,fn);return timerID;},id=>timers.delete(id),(preview,container)=>{container.innerHTML='预览已返回';});
 const flush=async()=>{for(let i=0;i<20;i++)await Promise.resolve();};
 const flushTimers=async()=>{const batch=[...timers.values()];timers.clear();for(const fn of batch)await fn();await flush();};
 page(fixture.source);await flush();await flushTimers();if(quickCalls!==1||!find('#static-quick').innerHTML.includes('预览已返回'))throw Error('Automatic preview did not complete');
 if(find('#static-import-mode').value!=='auto'||calls!==1)throw Error('Auto Locate must be default');
 if(!find('#locate-status').textContent.includes('6 / 6')||!drawn.includes('玄铁矿'))throw Error('Missing actual boxes or frozen Chinese names');
 let canvas=find('#static-canvas'),event=(x,y)=>({pointerId:1,clientX:x,clientY:y,preventDefault(){}});
 const panel=find('#static-quick');panel.innerHTML='已生成的预览';canvas.onpointerdown(event(55,65));if(panel.innerHTML.includes('裁切变更'))throw Error('Selecting a crop cleared preview before geometry changed');canvas.onlostpointercapture();if(panel.innerHTML.includes('裁切变更'))throw Error('Lost pointer capture left unchanged crop without preview');await flushTimers();if(quickCalls!==1)throw Error('Selection started a redundant preview request');find('#static-retry-preview').onclick();await flushTimers();if(quickCalls!==2||!panel.innerHTML.includes('预览已返回'))throw Error('Explicit retry did not restore preview');canvas.onpointerdown(event(55,65));canvas.onpointermove(event(65,70));canvas.onpointerup(event(65,70));
 const x=coordinates.find(n=>n.dataset.region==='0'&&n.dataset.coordinate==='0');if(Number(x.value)!==90)throw Error('Touch drag did not move selected actual crop');
 canvas.onpointerdown(event(103,125));canvas.onpointermove(event(120,140));canvas.onpointerup(event(120,140));
 const w=coordinates.find(n=>n.dataset.region==='0'&&n.dataset.coordinate==='2');if(Number(w.value)<=130)throw Error('Touch resize did not change crop');
 buttons.find(n=>n.dataset.polygonToggle==='0').onclick();buttons.find(n=>n.dataset.polygonAdd==='0').onclick();if(!find('[data-polygon-vertex="0"]').innerHTML.includes('顶点 5'))throw Error('Polygon edge insertion missing');let px=Number(coordinates[0].value),py=Number(coordinates[1].value);canvas.onpointerdown(event(px/2,py/2));canvas.onpointermove(event((px+6)/2,(py+6)/2));canvas.onpointerup(event((px+6)/2,(py+6)/2));await find('#static-validate').onclick();await flush();if(lastPlan.regions[0].polygon[0][0]!==px+6||lastPlan.regions[0].polygon[0][1]!==py+6)throw Error('Touch polygon vertex did not reach preview payload');buttons.find(n=>n.dataset.polygonRemove==='0').onclick();buttons.find(n=>n.dataset.polygonToggle==='0').onclick();
 await find('#static-validate').onclick();await flush();if(find('#static-confirm').disabled)throw Error('Corrected region cannot be validated');
 x.value='95';x.oninput();if(!find('#static-confirm').disabled)throw Error('Coordinate change must invalidate confirmation');
 find('#static-frozen').onclick();if(find('#static-import-mode').value!=='grid'||Number(coordinates[0].value)!==0)throw Error('Frozen grid fallback broken');
 find('#static-clear').onclick();if(find('#static-import-mode').value!=='manual')throw Error('Manual fallback unavailable');
 canvas.onpointerdown(event(10,10));canvas.onpointermove(event(70,70));canvas.onpointerup(event(70,70));if(maps.length!==1)throw Error('Manual region creation broken');
 fixture.detection.status='FAILED';fixture.detection.regions=[];await find('#static-auto').onclick();if(find('#static-import-mode').value!=='manual'||maps.length)throw Error('Failed detection must enter manual mode without guessed mappings');
 fixture.detection.status='PASS';fixture.detection.regions=clone(fixture.regions);pending=true;find('#static-auto').onclick();await Promise.resolve();find('#static-frozen').onclick();let resolve=pending;pending=false;resolve();await flush();if(find('#static-import-mode').value!=='grid'||Number(coordinates[0].value)!==0)throw Error('Late auto request overwrote chosen grid mode');
 await find('#static-contours').onclick();await flush();if(lastLocate.contours!==true)throw Error('Contour button did not request layout contour strategy');
 return 'PASS: default localization, frozen Chinese labels, touch drag/resize, boundary edits, validation invalidation, grid/manual fallbacks and stale request guard';
}

// Drives actual staticSlice handlers in native JS. Not a real phone visual test.
async function testAssetUiSheetFrames(source,fixture){
 const clone=x=>JSON.parse(JSON.stringify(x));
 const nodes=new Map(),grid=[],maps=[],coordinates=[],buttons=[],drawn=[];
 const attrs=s=>Object.fromEntries([...s.matchAll(/([\w-]+)="([^"]*)"/g)].map(m=>[m[1],m[2]]));
 function node(){return {value:'',disabled:false,dataset:{},textContent:'',isConnected:true,_html:'',querySelectorAll(selector){if(this===find('#static-grid'))return grid;if(selector==='[data-static-map]')return maps;if(selector==='[data-coordinate]')return coordinates;return buttons.filter(n=>{let key=selector.slice(6,-1).replace(/-([a-z])/g,(_,c)=>c.toUpperCase());return n.dataset[key]!==undefined;});},get innerHTML(){return this._html;},set innerHTML(html){this._html=html;parse(html,this===find('#static-mapping'));}};}
 function find(s){if(!nodes.has(s))nodes.set(s,node());return nodes.get(s);}
 function parse(html,mapping){if(mapping){maps.length=0;coordinates.length=0;buttons.length=0;}for(let m of html.matchAll(/<(input|select|button|canvas|p|section|details)\b([^>]*)>/g)){const a=attrs(m[2]);let n=node();n.value=a.value||'';n.name=a.name;for(let [k,v] of Object.entries(a))if(k.startsWith('data-'))n.dataset[k.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase())]=v;if(a.id)nodes.set('#'+a.id,n);if(m[1]==='select'){const options=html.slice(m.index).match(/^<select[^>]*>([\s\S]*?)<\/select>/)?.[1]||'';n._html=options;const opts=[...options.matchAll(/<option value="([^"]*)"([^>]*)>/g)];n.value=(opts.find(m=>m[2].includes('selected'))||opts[0])?.[1]||'';}if(n.dataset.staticMap!==undefined)maps.push(n);if(n.dataset.coordinate!==undefined)coordinates.push(n);if(Object.keys(n.dataset).some(k=>k.startsWith('region')||k.startsWith('polygon')))buttons.push(n);for(let [k,v] of Object.entries(a))if(k.startsWith('data-polygon-'))nodes.set(`[${k}="${v}"]`,n);if(n.name&&fixture.source.frozen_spec.grid_spec[n.name]!==undefined)grid.push(n);if(m[1]==='canvas'){n.getBoundingClientRect=()=>({left:0,top:0,width:300,height:200});n.setPointerCapture=()=>{};n.getContext=()=>({drawImage(){},beginPath(){},moveTo(){},lineTo(){},closePath(){},stroke(){},strokeRect(...a){drawn.push(a);},fillRect(){},fillText(text){drawn.push(text);},measureText(text){return {width:text.length*12};}});}}}
 let captured=null,calls=0,pending=false;const api=async(path,body)=>{if(path==='auto-locate'){calls++;if(pending)await new Promise(resolve=>{pending=resolve;});return clone(fixture.detection);}if(path==='plan'){captured=clone(body);return {...body,sheet_mapping:true};}throw Error('Unexpected API '+path);};
 class ImageStub{set src(v){Promise.resolve().then(()=>this.onload());}}
 const block=source.slice(source.indexOf('function staticSlice('),source.indexOf('async function route('));
 const page=new Function('$','close','specSummary','options','field','label','esc','Image','BASE','api','run','setTimeout','clearTimeout','quickReview',block+';return staticSlice;')(find,()=>{},()=>'',(items,value)=>items.map(([id,name])=>`<option value="${id}" ${id===value?'selected':''}>${name}</option>`).join(''),(id,name,v)=>`<input name="${id}" value="${v}">`,x=>x,x=>String(x),ImageStub,'/tools/assets',api,fn=>Promise.resolve().then(fn),()=>0,()=>{},()=>{});
 const flush=async()=>{for(let i=0;i<20;i++)await Promise.resolve();};
 page(fixture.source);await flush();
 if(fixture.frame_collection){
   if(find('#static-import-mode').value!=='auto'||calls!==1)throw Error('Effect frame collections must default to frame localization');
   if(maps.length!==8||!drawn.includes('剑气斩击 · 4帧')||!drawn.includes('命中闪光 · 1帧'))throw Error('Named effect/frame labels lost');
   await find('#static-validate').onclick();await flush();
   if(captured.mode!=='auto'||captured.regions.length!==8||new Set(captured.regions.map(r=>r.asset_id)).size!==2)throw Error('Effect frames merged across assets');
   if(new Set(captured.regions.map(r=>r.asset_id+':'+r.action+':'+r.frame)).size!==8)throw Error('Effect frame keys collide');
   if(!find('#locate-status').textContent.includes('个特效帧'))throw Error('Effect cells mislabeled as subjects');
   return 'PASS: effect group defaults to auto and preserves two named four-frame assets';
 }
 if(find('#static-import-mode').value!=='auto'||calls!==1)throw Error('Action sheets must use the common localization page');
 if(maps.length!==20||!drawn.includes('待机 · 1帧')||!drawn.includes('行走 · 4帧'))throw Error('Frame cell labels/keys lost for a shared character Asset');
 await find('#static-validate').onclick();await flush();
 if(captured.regions.length!==20||new Set(captured.regions.map(r=>r.asset_id)).size!==1)throw Error('Frame Count was confused with Asset Count');
 if(new Set(captured.regions.map(r=>r.action+':'+r.frame)).size!==20)throw Error('Distinct action/frame mappings lost');
 find('#static-frozen').onclick();await find('#static-validate').onclick();await flush();
 if(captured.mode!=='grid'||captured.regions.length!==20||!captured.regions.some(r=>r.action==='walk'&&r.frame===4))throw Error('Common frozen grid failed for action frames');
 if(captured.regions.some(r=>r.row===0&&r.column===2))throw Error('Blank idle cells assigned');
 return 'PASS: common Sheet page shows20 distinct action-frame labels under one Asset, localization/grid mapping and blank-cell exclusion';
}

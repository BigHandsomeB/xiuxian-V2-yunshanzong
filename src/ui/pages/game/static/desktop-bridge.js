// Loaded only by the native desktop shell; gameplay transport remains unchanged.
(() => {
 window.desktopTransport=true;
 const pending=new Map();let serial=0,presentationRef=0,presentation=null;
 const ready=new Promise(resolve=>new QWebChannel(qt.webChannelTransport,channel=>{
  const bridge=channel.objects.desktop;
  bridge.completed.connect((id,raw)=>{const entry=pending.get(id);if(!entry)return;pending.delete(id);entry.cleanup();
   try{const result=JSON.parse(raw);if(result.error)throw Error(result.error);entry.resolve(result);}catch(error){entry.reject(error);}
  });resolve(bridge);
 }));
 async function invoke(method,payload,signal){
  const bridge=await ready;if(signal?.aborted)throw new DOMException('Cancelled','AbortError');
  return new Promise((resolve,reject)=>{
   const id=String(++serial),abort=()=>{pending.delete(id);reject(new DOMException('Cancelled','AbortError'));};
   const cleanup=()=>signal?.removeEventListener('abort',abort);
   pending.set(id,{resolve,reject,cleanup});signal?.addEventListener('abort',abort,{once:true});
   bridge[method](id,payload);
  });
 }
 window.fetch=async(path,options={})=>{
  if(typeof path!=='string'||!path.startsWith('/game/api/'))throw Error('桌面版仅允许内部游戏调用');
  const result=await invoke('request',JSON.stringify({path,method:options.method||'GET',headers:options.headers||{},body:options.body??null,presentation_ref:presentationRef}),options.signal);
  return {ok:result.status>=200&&result.status<300,status:result.status,json:async()=>{
   const body=JSON.parse(result.body),reference=body.presentation;
   if(Number.isSafeInteger(reference?.desktop_ref)){
    if(reference.projection){presentation=reference.projection;presentationRef=reference.desktop_ref;}
    if(!presentation||presentationRef!==reference.desktop_ref)throw Error('素材展示已变化，请重新同步');
    body.presentation=presentation;
   }
   return body;
  }};
 };
 document.addEventListener('click',event=>{
  if(!event.target.closest?.('a[href="/tools/assets/"]'))return;
  event.preventDefault();
  invoke('open_manager','').catch(error=>window.alert(error.message));
 });
 // Keep immutable artwork alive for this window. Never cache saves or API responses.
 // Entries are bounded; existing blob URLs stay valid for retained/offscreen pages.
 const icons=new Map();let bytes=0;
 window.desktopIconURL=url=>{
  if(typeof url!=='string'||!/^\/game\/runtime\/[a-z][a-z0-9_.]*\/[a-f0-9]{64}$/.test(url))return url;
  const cached=icons.get(url);if(cached)return cached;
  if(icons.size>=1024||bytes>=64*1024*1024)return url;
  const task=invoke('asset',url).then(result=>{
   if(result.status!==200||!result.mime?.startsWith('image/')||typeof result.base64!=='string')throw Error('图标暂不可用');
   const binary=atob(result.base64);
   if(bytes+binary.length>64*1024*1024){icons.set(url,url);return url;}
   const data=Uint8Array.from(binary,c=>c.charCodeAt(0));
   const source=URL.createObjectURL(new Blob([data],{type:result.mime}));
   bytes+=data.length;icons.set(url,source);return source;
  }).catch(error=>{icons.delete(url);throw error;});
  icons.set(url,task);return task;
 };
})();

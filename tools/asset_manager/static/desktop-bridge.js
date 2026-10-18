// Native-only transport: JSON and image form data travel through QWebChannel.
(() => {
 const pending=new Map();let serial=0;
 const ready=new Promise(resolve=>new QWebChannel(qt.webChannelTransport,channel=>{
  const bridge=channel.objects.assets;
  bridge.completed.connect((id,raw)=>{
   const entry=pending.get(id);if(!entry)return;
   pending.delete(id);entry.cleanup();
   try{const result=JSON.parse(raw);if(result.error)throw Error(result.error);entry.resolve(result);}
   catch(error){entry.reject(error);}
  });resolve(bridge);
 }));
 window.fetch=async(path,options={})=>{
  if(typeof path!=='string'||!path.startsWith('/api/'))throw Error('仅允许内部素材管理调用');
  const signal=options.signal,check=()=>{if(signal?.aborted)throw new DOMException('Cancelled','AbortError');};
  check();
  const payload={path,method:options.method||'GET',headers:Object.fromEntries(new Headers(options.headers)),body:options.body??null};
  if(payload.body instanceof FormData){
   const entries=[];let size=0;
   for(const [name,value] of payload.body.entries()){
    size+=value instanceof Blob?value.size:new TextEncoder().encode(value).length;
    if(size>13*1024*1024)throw Error('上传图片和表单不能超过 13 MiB');
    if(value instanceof Blob){
     const bytes=new Uint8Array(await value.arrayBuffer());check();let binary='';
     for(let i=0;i<bytes.length;i+=32768)binary+=String.fromCharCode(...bytes.subarray(i,i+32768));
     entries.push({name,filename:value.name,type:value.type,base64:btoa(binary)});
    }else entries.push({name,value});
   }
   payload.body=null;payload.multipart=entries;
  }
  const raw=JSON.stringify(payload);if(raw.length>18*1024*1024)throw Error('上传数据过大');
  const bridge=await ready;check();
  const result=await new Promise((resolve,reject)=>{
   const id=String(++serial),abort=()=>{pending.delete(id);reject(new DOMException('Cancelled','AbortError'));};
   const cleanup=()=>signal?.removeEventListener('abort',abort);
   pending.set(id,{resolve,reject,cleanup});signal?.addEventListener('abort',abort,{once:true});
   bridge.request(id,raw);
  });
  return {ok:result.status>=200&&result.status<300,status:result.status,json:async()=>JSON.parse(result.body)};
 };
})();

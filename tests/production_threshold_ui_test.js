// Native DOM checks for the actual automationControls function; no browser claim.
export function runProductionThresholdTests(automationControls){
 let checks=0;const check=(v,m)=>{checks++;if(!v)throw new Error(m);};
 const all=n=>[n,...n.children.flatMap(all)];
 const el=(tag,className='',textContent='')=>({tagName:tag.toUpperCase(),className,textContent,children:[],append(...nodes){this.children.push(...nodes);}});
 const button=(text,onclick,cls)=>({...el('button',cls,text),onclick});
 const controls=automationControls(el,button,()=>el('span'));
 for(const width of [320,390,430])for(const theme of ['light','dark']){
  let sheet,sent;const ctx={width,theme,data:{view:{economy:{automation:{production:{b:{enabled:true,recipe_id:'ore',target:200,reserves:{herb:99},max_consumption:1}}}}}},sheet(title,body){sheet=body;},economyAction(name,payload){sent={name,payload};}};
  const box=controls(ctx,'b','ore');all(box).find(n=>n.textContent==='配置自动生产').onclick();
  const inputs=all(sheet).filter(n=>n.tagName==='INPUT');check(inputs.length===1,'one threshold input');check(inputs[0].value==='200','retains existing target');check(inputs[0].min==='1'&&inputs[0].max==='10000','valid target bounds');
  check(!all(sheet).some(n=>/保留量|消耗上限/.test(n.textContent)||n.textContent==='自动续产'),'obsolete settings removed');
  inputs[0].value='123';all(sheet).find(n=>n.textContent==='保存并开启').onclick();check(sent.name==='automation_production','real command');check(JSON.stringify(sent.payload)==='{"building_id":"b","policy":{"enabled":true,"recipe_id":"ore","target":123}}','threshold-only payload');
  all(sheet).find(n=>n.textContent==='关闭自动生产').onclick();check(sent.payload.policy.enabled===false&&sent.payload.policy.target===200,'disable existing policy');
  controls(ctx,'b','wood').children.find(n=>n.tagName==='BUTTON').onclick();check(all(sheet).find(n=>n.tagName==='INPUT').value==='30','different recipe default');check(!all(sheet).some(n=>n.textContent==='关闭自动生产'),'other recipe cannot disable current policy');
 }
 return {checks,status:'PASS',scope:'Native DOM contexts; phone rendering pending'};
}

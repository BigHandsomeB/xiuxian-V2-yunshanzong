function testStopReasonUI(dom,report,adventure){
 let checks=0;const check=(v,m)=>{if(!v)throw Error(m);checks++;};
 const document={createElement:tag=>({tagName:tag.toUpperCase(),children:[],dataset:{},attrs:{},textContent:'',append(...xs){this.children.push(...xs);},setAttribute(k,v){this.attrs[k]=v;},addEventListener(){}})};
 const d=new Function('document',dom.replace(/^export /gm,'')+';return {el,heading,link,status,button};')(document);
 const labels=new Function('el','button','resourceIcon',report.replace(/^import .*$/gm,'').replace(/^export /gm,'')+';return {stopReasonName,simulationStamp};')(d.el,d.button,()=>d.el('span'));
 const globals={...d,...labels,itemIcon:()=>d.el('span'),featureTab:()=>d.el('div'),detailSheet:()=>{},recipeCard:()=>d.el('div')};
 const render=new Function(...Object.keys(globals),adventure.replace(/^import .*$/gm,'').replace(/^export /gm,'')+';return render;')(...Object.values(globals));
 const all=n=>[n,...n.children.flatMap(all)];
 for(const width of [320,390,430])for(const theme of ['light','dark'])for(const reason of ['DEFEATED','STORAGE_FULL','WORLD_PAUSED']){
  const v={time:{day_length_ms:120000},world:{paused:reason==='WORLD_PAUSED'},combat:{encounter:{name:'试炼'},status:'SETTLED',stop_reason:reason,stop_sim_ms:300000}};
  const tree=render({data:{view:v},ui:{adventureTab:'事件'}}),notice=all(tree).find(n=>n.id==='battle-stop-notice');
  const text=all(notice).map(n=>n.textContent).join('\n');check(notice.attrs.role==='status','Permanent status at '+width+'/'+theme);
  check(text.includes(labels.stopReasonName[reason])&&text.includes('第3日'),'Cause/time comes from authoritative projection');
  if(reason==='STORAGE_FULL')check(all(notice).some(n=>n.href==='#inventory/trade')&&all(notice).some(n=>n.href==='#settings'),'Storage advice has actionable navigation');
 }
 return {checks,status:'PASS'};
}

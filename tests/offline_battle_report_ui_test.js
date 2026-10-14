async function testOfflineBattleReportUI(dom,source){
 let checks=0;const check=(v,m)=>{if(!v)throw Error(m);checks++;};
 function node(tag){return {tagName:tag.toUpperCase(),children:[],dataset:{},textContent:'',attrs:{},events:{},append(...rows){this.children.push(...rows);},setAttribute(k,v){this.attrs[k]=v;},addEventListener(k,f){(this.events[k]??=[]).push(f);},async click(){for(const f of this.events.click||[])await f({});}};}
 const document={createElement:node};const d=new Function('document',dom.replace(/^export /gm,'')+';return {el,button};')(document);
 const r=new Function('el','button','resourceIcon',source.replace(/^import .*$/gm,'').replace(/^export /gm,'')+';return {offlineBattleContent,offlineReportPresenter};')(d.el,d.button,(_,id)=>d.el('span','item-icon',id));
 const all=n=>[n,...n.children.flatMap(all)];
 const row={report_id:'save:1:r:1',duration_ms:3600000,from_sim_ms:0,end_sim_ms:3600000,battles:10,wins:9,win_rate_bps:9000,coins:40,overflow_coins:2,equipment_count:3,materials:{wood:4},converted_materials:{wood:2},stop_reason:'STORAGE_FULL',stop_sim_ms:300000};
 const data={view:{save_id:'save',generation:1,time:{pending:false,day_length_ms:120000},latest_battle_report:row,offline_report_names:{items:{wood:'灵木'}},inventory:{},offline_reports:[]}};
 for(const width of [320,390,430])for(const theme of ['light','dark']){
  const n=r.offlineBattleContent(data,row,()=>{}),text=all(n).map(n=>n.textContent).join('\n');
  check(text.includes('共 10 场')&&text.includes('90.0%')&&text.includes('满仓'),'Summary at '+width+'/'+theme);
  check(text.includes('材料溢出折算 2')&&text.includes('灵木')&&text.includes('停机时间：第3日'),'Stored monetary/material/time values');
  check(all(n).some(x=>x.textContent==='关闭战报'),'Close action available');
 }
 let opened=0,open=false,content;const values=new Map();const storage={getItem:k=>values.get(k),setItem:(k,v)=>values.set(k,v)};
 const options={sheet:(title,n)=>{opened++;open=true;content=n;},isOpen:()=>open,canPresent:()=>true,acknowledge:()=>{throw Error('Battle dismissal must not send a command');},close:()=>open=false,storage};
 const presenter=r.offlineReportPresenter(options);presenter.update({...data,view:{...data.view,time:{pending:true}}});check(!opened,'No report while pending');
 presenter.update(data);check(opened===1,'Completion opens report');await all(content).find(n=>n.textContent==='关闭战报').click();
 presenter.update(data);check(opened===1&&!open,'Closing suppresses repeat in session');r.offlineReportPresenter(options).update(data);check(opened===1,'Persisted read marker survives new presenter');
 presenter.update({...data,view:{...data.view,latest_battle_report:{...row,report_id:'save:1:r:2'}}});check(opened===2,'New report can appear');
 let count=0;const broken=r.offlineReportPresenter({...options,storage:{getItem(){throw Error('blocked');},setItem(){throw Error('quota');}},isOpen:()=>false,sheet:()=>count++});broken.update(data);broken.dismiss();broken.update(data);check(count===1,'Storage failures never block display or cause a repeated popup in session');
 const old=r.offlineReportPresenter({...options,isOpen:()=>false,sheet:()=>{throw Error('Old save has no report');}});old.update({...data,view:{...data.view,latest_battle_report:null}});check(true,'Missing field stays hidden');
 return {checks,status:'PASS'};
}

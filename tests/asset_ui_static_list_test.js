// Actual ordered-list component and text parser in a native DOM adapter; not Safari acceptance.
const BULK_ORES=['凡铁矿','赤铁矿','黑铁矿','青铁矿','精铁矿','赤铜矿','青铜矿','黄铜矿','紫铜矿','锡矿','铅矿','银矿','金矿','乌金矿','白石矿','青石矿','黑石矿','赤石矿','黄石矿','云母石','石英矿','白玉矿','青玉矿','墨玉矿','赤玉矿','玛瑙矿','硫磺矿','寒石矿','火纹石','磁石矿'];
function listTestFunctions(source){const begin=source.indexOf('function analyseAssetNames('),end=source.indexOf('function sourcePolicy(',begin);return new Function('esc',source.slice(begin,end)+';return {assetNameList,parseAssetNames};')(s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])));}
function listTestDom(){
 const decode=s=>s.replace(/&quot;/g,'"').replace(/&#39;/g,"'").replace(/&#10;/g,'\n').replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&amp;/g,'&');
 function node(tag='section',attributes={}){
  return {tag,attributes,dataset:Object.fromEntries(Object.entries(attributes).filter(([k])=>k.startsWith('data-')).map(([k,v])=>[k.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase()),v])),value:attributes.value||'',disabled:Object.hasOwn(attributes,'disabled'),hidden:Object.hasOwn(attributes,'hidden'),textContent:'',children:[],focus(){this.focused=true;},_html:'',get innerHTML(){return this._html;},set innerHTML(html){this._html=html;this.children=[];const stack=[this];for(const m of html.matchAll(/<\/?([a-z0-9]+)\b([^>]*)>|([^<]+)/gi)){if(m[3]!==undefined){const text=decode(m[3]);stack.at(-1).textContent+=text;if(stack.at(-1).tag==='textarea')stack.at(-1).value+=text;continue;}if(m[0].startsWith('</')){if(stack.length>1)stack.pop();continue;}const attrs={};for(const a of m[2].matchAll(/([\w-]+)(?:="([^"]*)")?/g))attrs[a[1]]=decode(a[2]||'');const n=node(m[1],attrs);stack.at(-1).children.push(n);if(!['input','br','hr','img','meta'].includes(m[1]))stack.push(n);}},querySelectorAll(selector){const matches=n=>selector.split(',').some(s=>{s=s.trim();if(s.startsWith('#'))return n.attributes.id===s.slice(1);const m=s.match(/^\[([^=\]]+)(?:="([^"]*)")?\]$/);return m?Object.hasOwn(n.attributes,m[1])&&(m[2]===undefined||n.attributes[m[1]]===m[2]):n.tag===s;});const all=[];const visit=n=>{for(const child of n.children){if(matches(child))all.push(child);visit(child);}};visit(this);return all;},querySelector(s){return this.querySelectorAll(s)[0]||null;}};
 }
 return node();
}
function testAssetUiStaticList(source){
 const container=listTestDom(),factory=listTestFunctions(source).assetNameList,read=factory(container,['玄铁矿'],()=>{});
 for(let i=1;i<6;i++){container.querySelector('#add-asset-name').onclick();const n=container.querySelector(`[data-name-index="${i}"]`);n.value=['','赤铜矿','寒铁矿','灵晶矿','赤炎矿','星陨矿'][i];n.oninput();}
 if(read().length!==6||!container.innerHTML.includes('共 6 个独立素材'))throw Error('Cannot add six independent assets');
 container.querySelector('[data-up="5"]').onclick();if(read()[4]!=='星陨矿')throw Error('Move-up failed');container.querySelector('[data-down="4"]').onclick();if(read()[5]!=='星陨矿')throw Error('Move-down failed');
 container.querySelector('[data-remove="2"]').onclick();if(read().length!==5||read().includes('寒铁矿'))throw Error('Delete failed');
 const stable=factory(container,[{asset_id:'icon.resource.one',name_zh:'玄铁矿'}],()=>{}),n=container.querySelector('[data-name-index="0"]');n.value='玄铁矿石';n.oninput();if(stable.entries()[0].asset_id!=='icon.resource.one')throw Error('Rename changed ID');
 return 'PASS: single-item add/delete/order and approved identity rename unchanged';
}
function testAssetBulkParser(source){
 const parse=listTestFunctions(source).parseAssetNames,eq=(a,b)=>{if(JSON.stringify(a)!==JSON.stringify(b))throw Error(JSON.stringify([a,b]));};
 for(const separator of ['\n','\r\n',',','，','、',';','；','\t'])eq(parse(['凡铁矿','赤铁矿','黑铁矿'].join(separator)).names,['凡铁矿','赤铁矿','黑铁矿']);
 eq(parse(' 凡铁矿， 赤铁矿\n\n黑铁矿、青铁矿；精铁矿\t ; ， ').names,BULK_ORES.slice(0,5));
 const duplicates=parse('凡铁矿\n赤铁矿\n凡铁矿');eq(duplicates.names,['凡铁矿','赤铁矿']);eq(duplicates.duplicates,[{name:'凡铁矿',count:2}]);if(duplicates.skipped_count!==1)throw Error('Duplicate count incorrect');
 const existing=parse('凡铁矿\n黑铁矿\n青铁矿',[' 凡铁矿 ','赤铁矿']);eq(existing.names,['黑铁矿','青铁矿']);eq(existing.existing,['凡铁矿']);
 eq(parse('1. 凡铁矿\n2、赤铁矿\n3)黑铁矿\n4）青铁矿\n5.精铁矿').names,BULK_ORES.slice(0,5));
 eq(parse('- 凡铁矿\n* 赤铁矿\n- 3. 黑铁矿').names,BULK_ORES.slice(0,3));
 eq(parse('九转丹\n3号矿\n1.5号矿\n矿石2.0\n-铜矿').names,['九转丹','3号矿','1.5号矿','矿石2.0','-铜矿']);
 eq(parse('\t ,，、;;；\n\r\n  ').names,[]);eq(parse(BULK_ORES.join('\n')).names,BULK_ORES);
 eq(parse(' 赤铁矿,凡铁矿,黑铁矿 ').names,['赤铁矿','凡铁矿','黑铁矿']);
 return 'PASS: eight separators/mixed whitespace/duplicates/existing names/order/numbered and Markdown lists; real30 ore names';
}
function testAssetBulkUi(source){
 const container=listTestDom(),factory=listTestFunctions(source).assetNameList;let emits=0,read=factory(container,[''],()=>emits++);
 const q=s=>container.querySelector(s),paste=text=>{q('[data-bulk-open]').onclick();q('[data-bulk-text]').value=text;q('[data-bulk-parse]').onclick();};
 paste(BULK_ORES.join('\n'));if(q('[data-bulk-panel]').hidden||!q('[data-bulk-text]').focused)throw Error('Bulk control not usable');
 if(read().length!==1||emits!==0||q('[data-bulk-confirm]').textContent!=='确认添加 30 个素材')throw Error('Parse must preview without mutation');
 if(q('[data-bulk-items]').querySelectorAll('[data-batch-index]').length!==30)throw Error('Missing30 editable preview rows');
 const once=q('[data-bulk-confirm]');once.onclick();once.onclick();if(JSON.stringify(read())!==JSON.stringify(BULK_ORES)||emits!==1||!container.innerHTML.includes('共 30 个独立素材'))throw Error('Single confirmation failed');
 if(read.entries().some(n=>n.asset_id)||container.innerHTML.includes('Machine ID'))throw Error('UI must not mint machine IDs');
 // Existing identity survives; initial input duplicate report and already-present report are explicit.
 emits=0;read=factory(container,[{asset_id:'icon.resource.existing',name_zh:'凡铁矿'}],()=>emits++);
 paste('凡铁矿\n黑铁矿\n青铁矿\n黑铁矿');if(!q('[data-bulk-preview]').innerHTML.includes('黑铁矿 ×2')||!q('[data-bulk-preview]').innerHTML.includes('已存在：凡铁矿'))throw Error('Missing duplicate/existing report');
 q('[data-batch-up="1"]').onclick();if(q('[data-batch-index="0"]').value!=='青铁矿')throw Error('Preview reorder failed');
 let n=q('[data-batch-index="0"]');n.value='精铁矿';n.oninput();q('[data-batch-remove="1"]').onclick();
 q('[data-bulk-confirm]').onclick();if(JSON.stringify(read())!==JSON.stringify(['凡铁矿','精铁矿'])||read.entries()[0].asset_id!=='icon.resource.existing')throw Error('Preview edit/delete/ID preservation failed');
 paste('金矿\n银矿');q('[data-bulk-cancel]').onclick();if(read().length!==2||q('[data-bulk-preview]').innerHTML)throw Error('Cancel mutated list');
 q('[data-bulk-text]').value='黑铁矿\n黑铁矿';q('[data-bulk-parse]').onclick();n=q('[data-batch-index="0"]');n.value='凡铁矿';n.oninput();if(!q('[data-bulk-confirm]').disabled)throw Error('Edited duplicate was not rejected');
 // Current main list can change after parse; confirmation rechecks it, without overwriting IDs.
 q('[data-bulk-text]').value='银矿';q('[data-bulk-parse]').onclick();n=q('[data-name-index="1"]');n.value='银矿';n.oninput();if(!q('[data-bulk-confirm]').disabled)throw Error('Stale duplicate could be added');
 q('[data-bulk-text]').value='';q('[data-bulk-text]').oninput();if(q('[data-bulk-preview]').innerHTML)throw Error('Changed raw text left stale confirmation');
 return 'PASS:30-item paste/preview/once-only addition, duplicate feedback, preview editing/reorder/delete/cancel, identity and stale-input guards';
}

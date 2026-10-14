// Native module/DOM checks; browser layout remains phone acceptance.
function testBulkBackpack(sources,fixture){
 let checks=0;const assert=(v,m)=>{if(!v)throw Error(m);checks++;};
 function node(tag){const n={tagName:tag.toUpperCase(),children:[],dataset:{},attrs:{},events:{},className:'',textContent:'',style:{},append(...xs){this.children.push(...xs);},setAttribute(k,v){this.attrs[k]=String(v);},getAttribute(k){return this.attrs[k];},addEventListener(k,f){this.events[k]=f;},remove(){},querySelectorAll(){return [];}};n.classList={add:k=>n.className+=' '+k,contains:k=>n.className.split(' ').includes(k)};return n;}
 const document={createElement:node,getElementById:()=>null},modules=new Map();
 function resolve(from,path){const parts=from.split('/');parts.pop();for(const x of path.split('/')){if(x==='..')parts.pop();else if(x!=='.')parts.push(x);}return parts.join('/');}
 function load(path){if(modules.has(path))return modules.get(path);let src=sources[path];if(src===undefined)throw Error('Missing '+path);const args={document},exports=[];
  src=src.replace(/import\s*\{([^}]+)\}\s*from\s*['"]([^'"]+)['"];?/g,(_,names,relative)=>{const dependency=load(resolve(path,relative));for(const name of names.split(',')){const [key,alias]=name.trim().split(/\s+as\s+/);args[alias||key]=dependency[key];}return '';});
  src=src.replace(/export\s+(function|const|class)\s+(\w+)/g,(_,kind,name)=>{exports.push(name);return kind+' '+name;});
  const result=new Function(...Object.keys(args),src+';return {'+exports.join(',')+'};')(...Object.values(args));modules.set(path,result);return result;
 }
 const all=n=>[n,...n.children.flatMap(all)],base='src/ui/pages/game/static/';
 const data=JSON.parse(JSON.stringify(fixture)),trades=[];let sheet;
 const preview=data.view.equipment.bulk;
 const ctx={data,ui:{bagSearch:'无结果',bagCategory:'pill'},route:{name:'cultivation'},busy:false,redraw(){},sheet:(title,body)=>sheet=body,economyAction:(name,payload)=>trades.push({name,payload})};
 const inventory=load(base+'screens/inventory.js');
 for(const [text,name]of [['一键分解','equipment_salvage_all'],['一键出售','equipment_sell_all']]){
  const page=inventory.render({...ctx,bag:true}),open=all(page).find(n=>n.textContent===text);
  assert(open&&!open.disabled,'Actual backpack exposes usable '+text+' even with no filtered results');
  const before=trades.length;open.events.click({});assert(trades.length===before,'Opening a sheet never mutates equipment');
  assert(all(sheet).some(n=>n.textContent.includes(`全部 ${preview.count} 件`)&&n.textContent.includes(`${preview.protected_count} 件装备保留`)&&n.textContent.includes('搜索和分类')),'Actual confirmation describes entire bag and protection');
  all(sheet).find(n=>n.textContent==='确认').events.click({});assert(trades.at(-1).name===name&&trades.at(-1).payload.selection_digest===preview.selection_digest&&!trades.at(-1).payload.instance_ids,'Actual confirmation routes the compact whole-bag command');
 }
 data.view.equipment.bulk.count=0;const empty=inventory.render({...ctx,bag:true});
 assert(all(empty).filter(n=>['一键分解','一键出售'].includes(n.textContent)).every(n=>n.disabled),'Nothing eligible disables both buttons');
 assert(all(empty).some(n=>n.textContent.includes('没有可处理')),'Empty preview explains protection');
 return {checks,status:'PASS'};
}

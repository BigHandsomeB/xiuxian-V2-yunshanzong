import {el,button} from './dom.js';

export function notesSummary(row,group){
 const box=el('span','catalog-notes-summary'),notes=row.annotation||{};
 for(const [label,value]of [['品阶',notes.grade||row.planned_grade||group.grade||'未标注'],['功能',notes.function||row.manual_function||'待填写'],['备注',notes.note||'待填写']]){
  const line=el('small','',label+'：'+(value.length>20?value.slice(0,20)+'…':value));line.title=value;box.append(line);
 }
 return box;
}

export function notesEditor(ctx,row,group){
 const initial=row.annotation||{},drafts=ctx.ui.catalogNoteDrafts??={};
 const draft=drafts[row.asset_id]??={revision:initial.revision||0,grade:initial.grade||row.planned_grade||group.grade||'',function:initial.function||row.manual_function||'',note:initial.note||''};
 const body=el('section','catalog-notes-editor');body.append(el('h3','','编辑素材说明'),el('p','muted','这些是策划说明，保存后可供Codex读取；不会直接改变实际品阶、属性或掉落。'));
 const fields={};
 for(const [key,label,limit]of [['grade','品阶说明',24],['function','功能说明',240],['note','备注',1000]]){
  const field=el('label','policy-field',label),input=el(key==='grade'?'input':'textarea');input.value=draft[key];input.maxLength=limit;input.setAttribute('aria-label',label);if(key!=='grade')input.rows=3;
  input.addEventListener('input',()=>{draft[key]=input.value;});field.append(input);fields[key]=input;body.append(field);
 }
 const message=el('p','muted');message.setAttribute('role','status');message.setAttribute('aria-live','polite');let saving=false;
 function busy(value){saving=value;save.disabled=value;read.disabled=value;for(const input of Object.values(fields))input.disabled=value;}
 const save=button('保存说明',async()=>{
  if(saving)return;busy(true);message.textContent='正在保存…';
  try{
   const response=await fetch('/game/api/catalog-notes',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':ctx.data.csrf},body:JSON.stringify({asset_id:row.asset_id,expected_revision:draft.revision,grade:draft.grade,function:draft.function,note:draft.note}),cache:'no-store'});
   const result=await response.json();if(!response.ok)throw Error(result.message||'说明保存失败，请重试。');
   row.annotation=result.entry;Object.assign(draft,result.entry);for(const [key,input]of Object.entries(fields))input.value=draft[key];message.textContent='已保存';ctx.redraw();
  }catch(error){message.textContent=error.message||'连接失败，编辑内容已保留。';}
  finally{busy(false);}
 },'primary block');
 const read=button('读取已保存说明',async()=>{
  if(saving)return;busy(true);
  try{
   const response=await fetch('/game/api/assets',{cache:'no-store'});const result=await response.json();if(!response.ok)throw Error(result.message||'读取失败');
   const fresh=result.presentation.catalog.groups.flatMap(g=>g.items).find(r=>r.asset_id===row.asset_id);if(!fresh)throw Error('此素材已不在图鉴中。');
   const entry=fresh.annotation||{};row.annotation=entry;Object.assign(draft,{revision:entry.revision||0,grade:entry.grade||fresh.planned_grade||group.grade||'',function:entry.function||fresh.manual_function||'',note:entry.note||''});
   for(const [key,input]of Object.entries(fields))input.value=draft[key];message.textContent='已读取保存内容';ctx.redraw();
  }catch(error){message.textContent=error.message;}
  finally{busy(false);}
 },'secondary');
 body.append(save,read,message);return body;
}

import {el,heading,link,button} from '../components/dom.js';
import {featureTab} from '../components/features.js';

export function storyEntry(ctx){
 const data=ctx.data.view.story;if(!data)return null;
 const entry=button(`主线记录${data.unread_count?' · '+data.unread_count+'段待阅读':''}`,()=>{location.hash='#story';},'secondary block');entry.dataset.id='story-entry';return entry;
}

export function render(ctx){
 const box=el('section','story-screen');box.append(heading('云山旧事','把查实的记下，没查明的另留一页。'));
 const data=ctx.data.view.story;
 if(!data){box.append(el('p','muted','剧情记录尚未开放'));return box;}
 const node=data.nodes.find(n=>n.id===ctx.route?.id);
 if(ctx.route?.id){
  box.append(link('返回剧情记录','#story','back-link'));
  if(!node?.can_read){box.append(el('p','muted',node?.reason||'未找到这段剧情'));return box;}
  const content=el('article','panel');content.dataset.id='story-'+node.id;content.append(el('h2','',node.title),el('p','muted',node.track==='independent'?'独立修行记事':node.track==='side'?'宗门生活片段':'往事回顾'));
  for(const [i,line]of node.lines.entries()){const row=el('section','row');row.dataset.id=node.id+'-line-'+i;row.append(el('h3','',line.speaker),el('p','',line.text));content.append(row);}
  const mark=button(node.read?'已阅读，可随时回看':'记为已读',()=>ctx.economyAction('story_read',{node_id:node.id}),'primary block');mark.disabled=node.read||ctx.busy||!!ctx.data.view.time.pending;
  content.append(mark);if(ctx.data.view.time.pending)content.append(el('p','muted','正在续算，可先阅读，完成后再标记。'));
  box.append(content);return box;
 }
 const tab=ctx.ui.storyTab||'pending';box.append(el('p','muted',`已阅读 ${data.read_count} / ${data.total} · 待阅读 ${data.unread_count}`),featureTab([['pending','待阅读'],['all','全部记录'],['read','已阅读']],tab,key=>{ctx.ui.storyTab=key;ctx.redraw();}));
 box.append(el('p','muted','主线依次阅读；宗门生活片段与筑基记事可独立阅读。已达到的旧进度可补看，不影响当前探索。'));
 let count=0;
 for(const chapter of data.chapters){
  const rows=data.nodes.filter(n=>n.chapter===chapter.id&&(tab==='all'||(tab==='read'?n.read:n.unlocked&&!n.read)));
  if(!rows.length)continue;
  const section=el('section','panel');section.dataset.id='story-group-'+chapter.id;section.append(el('h2','',chapter.title));
  for(const n of rows){
   const row=el('div','row');row.dataset.id='story-row-'+n.id;
   row.append(n.can_read?link(n.title,'#story/'+n.id,'external-link'):el('p','',n.title),el('p','muted',n.reason+(n.track==='side'?' · 生活片段':n.track==='independent'?' · 独立记事':'')));section.append(row);count++;
  }
  box.append(section);
 }
 if(!count)box.append(el('p','muted',tab==='read'?'暂无已阅读记录':'暂无待阅读剧情，继续按自己的节奏探索即可。'));
 return box;
}

function testAdventureStoryEntry({source,dom}){
 let checks=0;const assert=(ok,msg)=>{if(!ok)throw Error(msg);checks++;};
 function node(tag){return {tagName:tag.toUpperCase(),children:[],dataset:{},attrs:{},events:{},textContent:'',append(...n){this.children.push(...n);},setAttribute(k,v){this.attrs[k]=v;},addEventListener(k,f){this.events[k]=f;}};}
 const d=new Function('document',dom.replace(/^export /gm,'')+';return {el,heading,link,status,button};')({createElement:node});let opened=0;
 const storyEntry=ctx=>{if(!ctx.data.view.story)return null;const n=d.button('主线记录 · 2段待阅读',()=>opened++,'secondary block');n.dataset.id='story-entry';return n;};
 const featureTab=(tabs,selected,select)=>{const bar=d.el('div','feature-tabs');for(const [key,title]of tabs)bar.append(d.button(title,()=>select(key),'filter-chip'));return bar;};
 const render=new Function('renderExploration','renderEvents','storyEntry','stopReasonName','simulationStamp','el','heading','link','status','itemIcon','featureTab','recipeCard',source.replace(/^import .*$/gm,'').replace(/^export /gm,'')+';return render;')(()=>d.el('div'),()=>d.el('div'),storyEntry,{},()=>'',d.el,d.heading,d.link,d.status,()=>d.el('span'),featureTab,()=>d.el('div'));
 const ctx={data:{view:{story:{},world:{},time:{},combat:{dungeon:{id:'test',name:'测试',total_floors:100,cleared_floor:1},status:'SETTLED'}}},ui:{},redraw(){}};
 const all=n=>[n,...n.children.flatMap(all)];const page=render(ctx),bar=all(page).find(n=>n.className==='feature-tabs'),last=bar.children.at(-1);
 assert(bar.children.length===5,'Five top navigation entries');assert(bar.children.at(-2).textContent==='战斗记录'&&last.dataset.id==='story-entry','Story follows battle history');assert(last.className==='filter-chip','Story uses matching button style');assert(all(page).filter(n=>n.dataset.id==='story-entry').length===1,'One story entry, no footer duplicate');last.events.click({});assert(opened===1,'Click uses existing story navigation');delete ctx.data.view.story;assert(all(render(ctx)).find(n=>n.className==='feature-tabs').children.length===4,'Old view without story remains valid');return {checks};
}

import {systemIcon,iconLabel} from '../components/item-icon.js';
import {adapterFor} from '../building-adapters.js';
import {el,heading,link,status,button} from '../components/dom.js';
import {itemIcon,resourceIcon} from '../components/item-icon.js';
import {regions,definitionFor} from '../buildings.js';
const watches=['子','丑','寅','卯','辰','巳','午','未','申','酉','戌','亥'];
export function worldTimeBar(view){
 const host=el('section','panel sect-world-time'),time=view.time;
 host.setAttribute('aria-label','世界时间流转');
 const valid=Number.isFinite(time?.simulation_time_ms)&&time.simulation_time_ms>=0&&Number.isFinite(time?.day_length_ms)&&time.day_length_ms>0;
 const phase=valid?(time.simulation_time_ms%time.day_length_ms)/time.day_length_ms*12:0,index=Math.floor(phase);
 const caption=el('div','sect-time-caption');caption.append(el('span','','世界时间'),el('span','',valid?`第${Math.floor(time.simulation_time_ms/time.day_length_ms)+1}日 · ${watches[index]}时${view.world?.paused?' · 已暂停':''}`:'时间待同步'));host.append(caption);
 const track=el('div','sect-time-track');track.setAttribute('aria-hidden','true');
 for(const [i,name]of watches.entries()){
  const part=el('div',`sect-time-watch${valid&&i===index?' is-current':''}`),rail=el('progress','sect-time-rail');
  // Only committed simulation time drives this display, including pause and resync.
  const progress=valid?(i<index?1:i===index?phase-index:0):0;
  rail.setAttribute('max','1');rail.setAttribute('value',String(progress));part.append(rail,el('span','',name));track.append(part);
 }
 host.append(track);return host;
}
export function render(ctx){const host=el('section','sect-screen');host.append(worldTimeBar(ctx.data.view),heading('山中一日','照看宗门，静候大道。'));
 const summary=el('div','resource-strip sect-resource-overview');summary.setAttribute('aria-label','基础货币与资源');
 for(const row of ctx.data.presentation?.resource_overview||[]){const actual=row.gameplay_id?ctx.data.view.inventory[row.gameplay_id]:null;
 const part=button('',()=>{const body=el('div','item-detail');body.append(itemIcon({...row.visual,profile:'detail'}),el('p','',row.name));body.append(el('p','',actual?`真实库存：${actual.quantity}`:'素材概念已登记，玩法尚未接入；不代表持有。'));if(actual)body.append(link('查看真实仓库','#inventory','external-link'));ctx.sheet(row.name,body);},'resource-summary');part.dataset.overviewConcept=row.concept_id;
 part.append(actual?resourceIcon(ctx,row.gameplay_id):itemIcon({...row.visual,profile:'compact'}),el('span','resource-summary-name',row.name),el('small','',actual?String(actual.quantity):'未接入'));summary.append(part);}
 const workforce=ctx.data.view.work.total_count??ctx.data.view.work.assigned_count;const people=link('','#disciples','resource-summary people-summary');people.append(systemIcon(ctx,'disciples'),el('span','resource-summary-name','弟子'),el('small','',String(workforce)));summary.append(people);host.append(summary);
 const ridge=el('div','sect-ridge');ridge.append(el('span','ridge-inscription','云山宗'),el('p','','山门向云开 · 丹火待君来'));host.append(ridge);
 for(const region of regions){const section=el('section',`sect-region ${region.tone}`),title=el('header','region-heading');title.append(el('h2','',region.name),el('p','',region.flavor));section.append(title);
 const list=el('div','building-list');for(const [id,name,glyph]of region.buildings){const entry=link('',`#building/${id}`,'building-entry');entry.dataset.building=id;const visual=ctx.data.presentation?.building_icons?.[definitionFor(id)];const icon=visual?.asset?itemIcon({asset_id:visual.asset_id,asset:visual.asset,fallback:'building'}):el('span','building-glyph',glyph);entry.append(icon);const text=el('span','building-label');const available=adapterFor(id)?.kind==='real'||(id==='techniques'&&!!ctx.data.view.techniques?.open),paused=ctx.data.view.world?.paused;const caption=id==='alchemy'?`Lv${ctx.data.view.building.level} · ${paused?'世界暂停':ctx.data.view.alchemy.current.status==='WORKING'?'炼制中':'可经营'}`:available?'查看真实状态':'框架可查看';text.append(el('strong','card-title',name),el('small','',caption));entry.append(text,status(paused?'世界暂停':available?'可用':'后续开放'));list.append(entry);}section.append(list);host.append(section);}
 return host;
}

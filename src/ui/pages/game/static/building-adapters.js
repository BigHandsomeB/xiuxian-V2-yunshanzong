// Presentation registry. Future selections are ephemeral UI, never Save/Domain facts.
import {el,button,link,empty,facts} from './components/dom.js';
import {featureTab,detailSheet,productionSlot,queueRow,recipeCard,requirementRow,buildingStatus} from './components/features.js';
import {renderGate,renderHousing,renderHallServices,renderSupply,renderMaterials,renderFacility} from './screens/sect-management.js';
import {renderCrafting,upgradeControls} from './screens/sect-economy.js';
import {renderProduction,automationControls} from './screens/economy.js';
import {renderTrade,manager,equipmentGrid} from './screens/equipment.js';
import {renderAlchemy} from './screens/danding.js';
import {render as inventory} from './screens/inventory.js';
import {renderTechniqueLibrary} from './screens/techniques.js';
import {renderRefinement} from './screens/refinement.js';
import {renderArtifactLibrary} from './screens/artifacts.js';
import {render as cultivation} from './screens/cultivation.js';
import {render as disciples} from './screens/disciples.js';
import {renderGarden,renderHusbandry,renderMeals,renderFacilities} from './screens/ecology.js';
export const profiles={
 gate:{flavor:'云阶守一山，来者问仙踪。',sections:[['山门','入口状态','宗门信息'],['访客','访客名册','招募条件'],['护宗','防御槽位','护宗阵法']],description:'招募弟子，预留住房名额；完成后待命，可在弟子居安排岗位。访客与护宗尚未开放。'},
 hall:{flavor:'宗中有序，道业自兴。',sections:[['宗务','宗门总览','发展信息'],['事务','事务列表','目标与任务'],['政策','管理方向','宗门政策']],description:'宗门等级与发展进度由现有建筑和通关进度推导；宗门委托交付真实材料获得贡献，可在万宝楼兑换；政策尚未开放。'},
 house:{flavor:'同修一院，各守其职。',sections:[['居住','弟子分组','居住状态'],['分配','当前岗位','容量要求']],description:'查看未分配、已分配与各岗位弟子人数，直接安排宗门工作。'},
 kitchen:{flavor:'灵膳养气，烟火亦修行。',sections:[['食材','食材选择','材料槽'],['菜谱','膳食分类','效果说明'],['烹饪','烹饪槽','产物槽','生产队列']],description:'青灵谷与灵泉水可制作青灵米饭，用于每日基础供养；禽蛋、灵鱼等可制作其他灵膳，岗位餐提供对应工作加成。'},
 garden:{flavor:'一畦灵雨，草木含真。',sections:[['田地','田地槽位','生长详情'],['种植','种子与灵草','种植要求'],['收获','收获区','产物详情']],description:'灵草与灵谷种植连接真实弟子、生产时间与仓库；可配置自动续产，不消耗种子。'},
 pasture:{flavor:'灵兽栖山，与道相伴。',sections:[['灵兽','灵兽列表','灵兽槽位'],['喂养','喂养材料','培养要求'],['产物','产物区','状态详情']],description:'建设御兽苑，安排弟子用灵谷收集禽蛋，为宗门灵膳提供普通食材；灵兽培养尚未开放。'},
 abyss:{flavor:'灵渊映月，水脉藏珍。',sections:[['水域','水域槽位','灵鱼列表'],['养殖','养殖条件','喂养槽'],['捕捞','捕捞入口','产物区']],description:'建设灵渊，安排弟子捕捞灵鱼供宗门灵膳使用；不产出主角稀有核心。'},
 mountain:{flavor:'山林石脉，万物有所出。',sections:[['矿区','矿场','矿石资源'],['林区','林场','木材资源'],['采石','采石点','石材资源'],['探索','探索节点','区域说明']],description:'矿场、林场、采石与探索可查看。凡铁矿、灵木、普通木材、石材与下品灵石连接真实采集；其他区域后续开放。'},
 alchemy:{flavor:'药入丹炉，火候自有时。',sections:[['丹方','凝气丹与筑基丹','炼丹条件']],description:'查看凝气丹、筑基丹与五种筑基修炼丹、弟子、材料、炼制进度与库存。'},
 forge:{flavor:'百炼成器，锋藏道心。',sections:[['武器','剑器分类','材料槽'],['防具','护甲分类','锻造槽'],['法宝','法宝分类','产物区'],['强化','强化入口','强化条件']],description:'加工普通材料，使用主角副本矿物与兽材打造装备，并用炼器精华强化现有装备。法宝可在本阁炼制、装备、投喂升级与强化。'},
 workshop:{flavor:'匠心入物，百工济宗。',sections:[['制造','配方分类','制造槽'],['工具','工具分类','材料槽'],['加工','基础材料','加工产物','生产队列']],description:'通用制造、工具、加工品与队列预留；制造规则后续开放。'},
 construction:{flavor:'筑台开阁，宗门渐成。',sections:[['建筑','建筑列表','等级与状态'],['建设','升级要求','建设队列']],description:'集中查看全宗建筑等级、升级需求与条件；已开放的建筑可在此升级。'},
 warehouse:{flavor:'所藏皆有来处。',sections:[['仓库','真实库存','分类详情']],description:'复用真实Inventory，不建立第二套仓库。'},
 market:{flavor:'万宝汇聚，交换有道。',sections:[['购买','商品分类','商品详情'],['出售','持有物品','出售要求'],['兑换','兑换分类','兑换条件']],description:'材料按来源与价值定价，游戏每日限量随机20种已解锁商品，价格浮动±20.0%；可交付商会订单、与NPC竞拍或寄卖珍品。'},
 techniques:{flavor:'藏卷悟道，静修养真。',sections:[['收藏','功法分类','功法详情'],['修炼','功法修炼','主角闭关']],description:'按身法、防御、绝技、终极与被动分类收藏、装备功法；已装备功法随击杀获得经验，独立修炼和主角闭关后续开放。'},
 dao:{flavor:'服丹凝气，积修破境。',sections:[['修炼','真实境界','突破要求']],description:'连接真实Cultivation和Combat成长投影，不补资源或降低门槛。'}
};
export function placeholder(ctx,id){const p=profiles[id],box=el('div','framework-panel');const local=ctx.ui.buildingFramework??={};const state=local[id]??={tab:0};
 box.append(el('p','',p.description),buildingStatus('COMING_SOON'),featureTab(p.sections.map((s,i)=>[String(i),s[0]]),String(state.tab),key=>{state.tab=Number(key);ctx.redraw();}));
 const section=p.sections[state.tab]||p.sections[0],slots=el('div','framework-slots');for(const title of section.slice(1))slots.append(productionSlot(ctx,title,`${p.description}此位置是交互布局预留，不代表已获得槽位或产物。`));box.append(slots);
 const selection=button('选择查看项目',()=>{const sheet=el('div');sheet.append(el('p','','只选择界面查看项目，不投入材料。'));for(const title of section.slice(1))sheet.append(button(title,()=>{state.selected=title;ctx.redraw();ctx.sheet('已选择查看',el('p','',title+'：规则尚未开放，不会投入材料或产生收益。'));},'secondary'));ctx.sheet(section[0]+'选择',sheet);},'secondary');box.append(selection);if(state.selected)box.append(el('p','selected-preview','正在查看：'+state.selected));
 box.append(queueRow(ctx),recipeCard(ctx,'功能与条件',p.description),button('尚未开放',null,'primary'));box.children[box.children.length-1].disabled=true;return box;}
function construction(ctx){const box=el('div','construction-list');box.append(el('p','muted','全宗建筑升级在此办理，按真实库存扣除材料。'));for(const row of Object.values(ctx.data.view.buildings))box.append(upgradeControls(ctx,row));return box;}
function affairs(ctx){
 const v=ctx.data.view,rank=v.sect_development;
 if(!rank)return placeholder(ctx,'hall');
 const box=el('section','panel');box.dataset.systemIcon='sect-development';
 box.append(el('h2','',`宗门等级 ${rank.level}`));
 if(rank.next){const r=rank.next;
  box.append(el('h3','',`下一级：${r.level}级`),el('p','',`任意 ${r.building_count} 栋可升级建筑达到 ${r.building_level} 级：${Math.min(r.current_building_count,r.building_count)} / ${r.building_count}`),el('p','',`荆棘古道通关 ${r.cleared_floor} 层：${Math.min(r.current_cleared_floor,r.cleared_floor)} / ${r.cleared_floor}`));
 }else box.append(el('p','','已达到当前宗门等级上限'));
 for(const opened of [true,false]){const list=rank.unlocks.filter(r=>r.unlocked===opened);box.append(el('h3','',opened?'已解锁内容':'未解锁内容'));if(!list.length)box.append(el('p','muted','暂无'));for(const r of list)box.append(el('p','',`${r.name}（宗门 ${r.level} 级）`));}
 box.append(el('p','muted','宗门 3–5 级本批仅展示等级，不追加解锁内容。'),facts([['宗门建筑',String(Object.keys(v.buildings).length)],['弟子人数',String(v.work.total_count)],['仓容',String(v.capacity.effective)]]));
 for(const name of ['任务','政策']){const item=el('div','locked-module');item.append(el('strong','',name),el('span','status-badge','尚未开放'));box.append(item);}
 return box;
}
export const buildingAdapters=Object.fromEntries(Object.keys(profiles).map(id=>[id,{kind:'framework',render:ctx=>placeholder(ctx,id)}]));
Object.assign(buildingAdapters,{techniques:{kind:'framework',realWhen:ctx=>!!ctx.data.view.techniques?.open,render:renderTechniqueLibrary},garden:{kind:'framework',realWhen:ctx=>!!ctx.data.view.economy,render:ctx=>ctx.data.view.economy?renderProduction(ctx,['garden']):placeholder(ctx,'garden')},mountain:{kind:'framework',realWhen:ctx=>!!ctx.data.view.economy,render:ctx=>ctx.data.view.economy?renderProduction(ctx,['mine','forest','quarry']):placeholder(ctx,'mountain')},forge:{kind:'framework',realWhen:ctx=>!!ctx.data.view.economy,render:ctx=>{if(!ctx.data.view.economy)return placeholder(ctx,'forge');if(!ctx.data.view.economy.crafting)return renderProduction(ctx,['forge']);const state=ctx.ui.forge??={tab:'equipment'},host=el('section');host.append(featureTab([['equipment','冶炼与装备'],['refinement','精炼'],['artifacts','法宝']],state.tab,key=>{state.tab=key;ctx.redraw();}));if(state.tab==='refinement'){host.append(renderRefinement(ctx));return host;}if(state.tab==='artifacts'){host.append(renderArtifactLibrary(ctx));return host;}const node=renderProduction(ctx,['smelter']);node.append(renderCrafting(ctx));if(ctx.data.view.sect_services)node.append(el('h2','','装备强化'),el('p','muted','选择已有装备查看强化消耗与条件。'),equipmentGrid(ctx));host.append(node);return host;}},market:{kind:'framework',realWhen:ctx=>!!ctx.data.view.equipment,render:ctx=>ctx.data.view.sect_services?renderMaterials(ctx):ctx.data.view.equipment?renderTrade(ctx):placeholder(ctx,'market')},alchemy:{kind:'real',render:ctx=>{if(ctx.data.view.alchemy.recipes.length>1&&ctx.data.view.economy)return renderProduction(ctx,['alchemy']);const node=renderAlchemy(ctx);if(ctx.data.view.economy)node.append(automationControls(ctx,ctx.data.view.building.instance_id,'pill'));return node;}},warehouse:{kind:'real',render:ctx=>inventory({...ctx,embedded:true})},dao:{kind:'real',render:ctx=>ctx.data.view.cultivation?cultivation({...ctx,embedded:true}):placeholder(ctx,'dao')},house:{kind:'real',render:ctx=>{const node=disciples({...ctx,embedded:true});if(ctx.data.view.sect_services)node.prepend(renderHousing(ctx));return node;}},construction:{kind:'real',render:construction},hall:{kind:'real',render:ctx=>{const node=affairs(ctx);if(ctx.data.view.sect_services)node.append(renderHallServices(ctx));return node;}}});
for(const [id,render] of Object.entries({gate:renderGate,kitchen:renderSupply,pasture:ctx=>renderFacility(ctx,'pasture'),abyss:ctx=>renderFacility(ctx,'spring')}))buildingAdapters[id]={kind:'framework',realWhen:ctx=>!!ctx.data.view.sect_services,render:ctx=>ctx.data.view.sect_services?render(ctx):placeholder(ctx,id)};
export function adapterFor(id){
 const adapter=buildingAdapters[id],render={garden:renderGarden,kitchen:renderMeals,pasture:ctx=>renderHusbandry(ctx,'pasture'),abyss:ctx=>renderHusbandry(ctx,'spring')}[id];
 if(render)return {...adapter,render:ctx=>ctx.data.view.ecology?render(ctx):adapter.render(ctx)};
 if(id==='construction')return {...adapter,render:ctx=>{const node=adapter.render(ctx);if(ctx.data.view.ecology)node.append(el('h2','','四建筑设施营造'),renderFacilities(ctx));return node;}};
 return adapter;
}

import {patchPanel} from './patch.js';
import {systemIcon} from './item-icon.js';
// Explicit presentation label bindings. No Gameplay command or timing logic.
const labels={"宗门": "sect", "弟子": "nav_disciples", "修炼": "nav_cultivation", "仓库": "inventory", "冒险": "adventure", "刷新": "refresh", "设置": "settings", "返回": "back", "关闭": "close", "帮助": "help", "功能": "function", "资源需求": "requirements", "人员安排": "workers", "规则说明": "rules", "丹炉": "furnace", "种植": "plant", "收获": "harvest", "采矿": "mine", "伐木": "logging", "采石": "quarry", "烹饪": "cooking", "喂养": "feeding", "培养": "breeding", "捕捞": "fishing", "制造": "craft", "建设": "construction", "搜索": "search", "排序": "sort", "图鉴": "catalog", "穿戴": "equip", "卸下": "unequip", "装备比较": "compare", "出售": "sell", "分解": "salvage", "材料槽": "material_slot", "产物槽": "output_slot", "生产队列": "queue", "库存保留": "reserve", "服丹": "train", "突破": "breakthrough", "基础攻击": "basic_attack", "领取战利品": "claim", "地图": "map", "秘境塔": "tower", "副本": "dungeon", "Boss": "boss", "探索": "exploration", "事件": "event", "战斗记录": "battle_log", "功法": "technique", "人员": "workers", "说明": "rules", "‹ 返回": "back", "使用凝气丹修炼": "train", "确认突破": "breakthrough", "开始炼制": "furnace", "开始生产": "production", "查看图鉴": "catalog", "查看战斗记录": "battle_log", "任务 / 工作": "workers"};
Object.assign(labels,{'烹饪槽':'cooking','喂养材料':'feeding','喂养槽':'feeding','培养要求':'breeding','捕捞入口':'fishing','制造槽':'craft','建设队列':'construction','矿场':'mine','矿区':'mine','林场':'logging','林区':'logging','采石点':'quarry','收获区':'harvest','产物区':'output_slot','加工产物':'output_slot','锻造槽':'craft','强化入口':'craft','探索节点':'exploration','突破要求':'breakthrough','安排工作弟子':'workers','自动续产':'automation','配置自动生产':'automation','库存保留量':'reserve'});
export function decorateControls(root,data){
 const ctx={data};
 for(const node of root.querySelectorAll('button,a,h2,summary,label')){
  const existing=node.querySelector('.system-icon');if(node.querySelector('img')&&!existing)continue;
  const name=node.textContent.trim();const childLabel=Array.from(node.children).find(n=>['SPAN','STRONG'].includes(n.tagName)&&labels[n.textContent.trim()]);const key=node.dataset.controlIcon||labels[name]||labels[childLabel?.textContent.trim()];if(!key||!data.presentation?.system_icons?.[key]?.asset)continue;
  if(existing){const row=data.presentation.system_icons[key];if(existing.__runtimeURL===row.asset.url&&existing.dataset.assetId===(row.asset_id||''))continue;const fresh=systemIcon(ctx,key),kept=patchPanel(existing,fresh);if(kept!==existing)existing.replaceWith(kept);continue;}
  const placeholder=node.querySelector('.item-icon');if(placeholder)placeholder.replaceWith(systemIcon(ctx,key));
  else node.prepend(systemIcon(ctx,key));
  node.classList.add('approved-control');
 }
}
export function decorateShell(data){
 const ctx={data};
 for(const [selector,key] of [['#refresh','refresh'],['.game-top a[href="#settings"]','settings'],['#close-sheet','close'],...['sect','disciples','cultivation','inventory','adventure'].map(id=>['#main-nav [data-tab="'+id+'"]',({disciples:'nav_disciples',cultivation:'nav_cultivation'})[id]||id])]){
  const node=document.querySelector(selector);if(!node)continue;
  if(!data.presentation?.system_icons?.[key]?.asset)continue;
  const existing=node.querySelector('.system-icon'),row=data.presentation.system_icons[key];if(existing?.__runtimeURL===row.asset.url&&existing.dataset.assetId===(row.asset_id||''))continue;
  const icon=systemIcon(ctx,key);
  if(node.closest('#main-nav'))node.querySelector('span')?.replaceWith(icon);else node.replaceChildren(icon);
  node.dataset.approvedIcon=key;
 }
}

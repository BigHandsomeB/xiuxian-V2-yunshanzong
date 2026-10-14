import {iconLabel} from '../components/item-icon.js';
import {manager} from './equipment.js';
import {el,heading,button,link} from '../components/dom.js';
import {MAX_SAVE_BYTES} from '../save/codec.js';
export function saveControls(ctx){
 const saves=ctx.saves,box=el('section','panel');box.dataset.savePanel='main';box.append(el('h2','','存档与备份'),el('p','',saves.describe()),el('p','muted','当前游戏进度仍由服务器管理。导入和存档选择只改变备份副本。'));
 const info=saves.row.current;if(info)box.append(el('p','muted',`版本 ${info.version} · ${new Date(info.updatedAt).toLocaleString()} · ${saves.storage.mode}`));
 box.append(el('p','muted',saves.persistent?'已取得持久存储许可。':'浏览器未保证长期保留；建议定期导出文件。'));
 function message(text){ctx.sheet('存档提示',el('p','',text));}
 const run=fn=>Promise.resolve().then(fn).catch(error=>message(error.message));
 function textSheet(text){const body=el('div','save-text'),field=el('textarea');field.dataset.saveInput='text';field.value=text;field.readOnly=true;field.rows=8;field.setAttribute('aria-label','存档文本');body.append(el('p','','长按全选并复制，保存在安全的位置。'),field);ctx.sheet('复制存档',body);}
 function download(which){try{const text=saves.exportText(which),url=URL.createObjectURL(new Blob([text],{type:'application/json'})),a=el('a');a.href=url;a.download=`yunshan-save-${saves.saveId}-${which}.json`;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);}catch(error){message(error.message);}}
 function copy(which){let text;try{text=saves.exportText(which);}catch(error){message(error.message);return;}if(navigator.clipboard?.writeText)navigator.clipboard.writeText(text).then(()=>message('存档文本已复制。'),()=>textSheet(text));else textSheet(text);}
 function exports(which,title){const row=el('div','inventory-filters');row.dataset.saveCopy=which;const dl=button('导出'+title,()=>download(which),'secondary'),cp=button('复制'+title,()=>copy(which),'secondary');dl.disabled=cp.disabled=!info&&which==='current';row.append(dl,cp);return row;}
 box.append(exports('current','存档'));if(saves.row.previous)box.append(exports('previous','上一份副本'));
 if(saves.row.conflict){
  for(const [which,title]of [['local','本地副本'],['cloud','云端副本']]){const candidate=saves.row.conflict[which];box.append(el('p','',`${title}：版本 ${candidate.version} · ${new Date(candidate.updatedAt).toLocaleString()}`),exports(which,title));const choose=button('保留'+title,()=>{const body=el('div');body.append(el('p','','选择将更新备份；当前服务器游戏进度不变。两份副本可在选择前导出，另一份仍保留为上一份副本。'),button('确认保留'+title,()=>run(()=>saves.choose(which).then(()=>message(saves.describe()))),'primary'));ctx.sheet('选择存档',body);},'secondary');choose.disabled=!saves.owner.writable;box.append(choose);}
 }
 const fileLabel=el('label','policy-field','从文件导入'),file=el('input');file.type='file';file.accept='.json,application/json,text/plain';file.disabled=!saves.canWrite;file.setAttribute('aria-label','选择存档文件');file.addEventListener('change',event=>{const chosen=event.target.files?.[0];if(!chosen)return;run(async()=>{if(chosen.size>MAX_SAVE_BYTES)throw new Error('存档文件过大。');confirmImport(await chosen.text());});event.target.value='';});fileLabel.append(file);box.append(fileLabel);
 function confirmImport(text){const body=el('div');body.append(el('p','','导入将替换备份副本，并保留上一份。不会修改当前服务器游戏进度。'),button('校验并导入',()=>run(()=>saves.importText(text).then(()=>message(saves.describe()))),'primary'));ctx.sheet('确认导入',body);}
 const paste=button('粘贴文本导入',()=>{const body=el('div','save-text'),field=el('textarea');field.dataset.saveInput='text';field.rows=8;field.setAttribute('aria-label','粘贴完整存档文本');body.append(field,button('检查并导入',event=>confirmImport(event.currentTarget.parentNode.querySelector('[data-save-input]').value),'primary'));ctx.sheet('粘贴存档',body);},'secondary');paste.disabled=!saves.canWrite;box.append(paste);
 box.append(button('重试存档备份',()=>run(()=>saves.refreshServer().then(()=>saves.flush()).then(()=>message(saves.describe()))),'secondary'));
 if(info?.source==='import'){const resume=button('恢复备份当前游戏进度',()=>{const body=el('div');body.append(el('p','','导入副本将保留为上一份，之后继续备份服务器当前进度。'),button('确认恢复',()=>run(()=>saves.resumeServerBackup().then(()=>message(saves.describe()))),'primary'));ctx.sheet('恢复备份',body);},'secondary');resume.disabled=!saves.canWrite;box.append(resume);}
 return box;
}
export function render(ctx){const node=el('section','settings-screen');node.append(heading('宗门杂记','设置与帮助','#sect'));node.append(el('h2','','游戏状态'),el('p','','炼丹、仓库和岗位来自真实存档。修炼和基础战斗已接真实存档；未来系统入口仅供查看。'));
 node.append(el('p','',`离线结算上限 ${(ctx.data.view.time.offline_cap_ms??86400000)/3600000} 小时；已接受的追赶进度继续完成。`));
 if(ctx.saves)node.append(saveControls(ctx));
 if(ctx.theme){const themeBox=el('section','theme-controls');themeBox.append(el('h2','','界面外观'),el('p','muted','只改变屏幕配色，独立于世界昼夜与暂停状态。'));for(const [mode,title,id]of [['SYSTEM','跟随系统','light'],['LIGHT','日间','light'],['DARK','夜间','dark']]){const b=button('',()=>{ctx.theme.set(mode);ctx.redraw();},'filter-chip');b.dataset.themeMode=mode;b.setAttribute('aria-pressed',String(ctx.theme.mode===mode));b.append(iconLabel(ctx,id,title));themeBox.append(b);}node.append(themeBox);}
 node.append(button('更新游戏状态',()=>ctx.sync(true),'secondary'),button('重新加载素材',()=>ctx.reloadAssets(),'secondary'));
 const economy=ctx.data.view.economy;
 if(economy?.material_caps){const box=el('section','panel'),toggle=button(economy.material_overflow?'关闭材料溢出折算':'开启材料溢出折算',()=>ctx.economyAction('material_overflow',{enabled:!economy.material_overflow}),'secondary');toggle.dataset.materialOverflow='toggle';toggle.setAttribute('aria-pressed',String(economy.material_overflow));toggle.disabled=ctx.busy||ctx.data.view.world?.paused||ctx.data.view.time.pending;box.append(el('h2','','挂机材料保留'),el('p','',economy.protected_material_ids?'仅战斗奖励超过保留上限时，普通材料按各自基准收购价折算；Boss材料始终保留。生产与手动操作保持原规则。':`仅战斗奖励超过保留上限时，每件折算 ${economy.overflow_coin_per_item} 灵钱；生产与手动操作保持原规则。`));for(const row of economy.material_cap_rows||[])box.append(el('p','',`${row.name}：${economy.protected_material_ids?.includes(row.resource_id)?'始终保留':`保留 ${row.cap}`}`));box.append(toggle,el('p','muted',`自动生产使用至多 ${economy.auto_production_capacity_ratio*100}% 仓容；手动生产可使用全仓容。`));node.append(box);}
 if(ctx.data.view.equipment)node.append(manager(ctx));
 node.append(link('万宝图鉴','#inventory/catalog','external-link'));
 node.append(el('h2','','如何照看宗门'),el('p','','进入丹鼎阁，查看材料与岗位，开始炼制。丹成后产物进入万宝库。世界运行时重新打开会续算真实进度；暂停世界后生产时间冻结，恢复时不会补算暂停时间。'));
 node.append(link('打开素材管理器','/tools/assets/','external-link'),el('p','muted','已有建筑内景保留为插画与特殊展示。日常经营以图标与进度呈现。'));return node;}

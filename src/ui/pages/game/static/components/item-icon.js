import {setIconSource} from './icon-loading.js';
import {el} from './dom.js';
const glyphs={resource:'◆',herb:'叶',pill:'丹',equipment:'剑',character:'人',building:'阁',other:'◇'};
export function iconModel({asset_id=null,asset=null,fallback='resource',quality='common',quantity=null,selected=false,locked=false,disabled=false,obtained=true}={}){return {asset_id,asset,fallback:glyphs[fallback]?fallback:'resource',quality:({white:'common',green:'uncommon',blue:'rare'})[quality]||(['common','uncommon','rare','epic','legendary'].includes(quality)?quality:'common'),quantity,selected:!!selected,locked:!!locked,disabled:!!disabled,obtained:!!obtained};}
export function itemIcon(options={}){
 const model=iconModel(options),box=el('span',`item-icon quality-${model.quality}`);if(options.framed)box.classList.add('catalog-framed');box.__runtimeURL=model.asset?.url||null;if(['compact','comfortable','detail'].includes(options.profile))box.dataset.profile=options.profile;box.dataset.assetId=model.asset_id||'';box.dataset.fallback=model.fallback;
 for(const key of ['selected','locked','disabled'])if(model[key])box.classList.add(key);if(!model.obtained)box.classList.add('unobtained');
 const placeholder=el('span','icon-placeholder',glyphs[model.fallback]);placeholder.setAttribute('aria-hidden','true');box.append(placeholder);
 if(model.asset?.url){const image=el('img','runtime-icon');image.alt='';image.loading='lazy';image.decoding='async';image.width=model.asset.width||48;image.height=model.asset.height||48;placeholder.hidden=true;image.addEventListener('error',()=>{image.remove();placeholder.hidden=false;box.dataset.assetFallback='true';},{once:true});setIconSource(image,model.asset.url);box.append(image);}
 else box.dataset.assetFallback='true';
 const enhancement=options.enhancement_level;
 if(model.fallback==='equipment'&&Number.isSafeInteger(enhancement)&&enhancement>0){box.append(el('span','icon-quantity',`+${enhancement}`));}
 else if(model.quantity!==null)box.append(el('span','icon-quantity',`×${model.quantity}`));if(model.locked)box.append(el('span','icon-lock','锁'));return box;
}
export function resourceIcon(ctx,id,quantity=null,profile=null){const row=ctx.data.presentation?.icons?.[id]||{},item=ctx.data.view.inventory[id]||{};return itemIcon({asset_id:row.asset_id,asset:row.asset,fallback:item.category==='pill'?'pill':item.category==='herb'?'herb':id==='pill'?'pill':id==='herb'?'herb':'resource',quality:item.quality||'common',quantity,profile:profile||ctx.ui?.iconProfile||'compact'});}

// All system/function icons use the same approved presentation map and image fallback.
export function systemIcon(ctx,id){const row=ctx.data?.presentation?.system_icons?.[id]||{};const icon=itemIcon({...row,fallback:'other',profile:'compact'});icon.classList.add('system-icon');icon.dataset.systemIcon=id;return icon;}
export function iconLabel(ctx,id,name,className=''){const label=el('span',`icon-label ${className}`);label.append(systemIcon(ctx,id),el('span','',name));return label;}
export function equipmentIcon(ctx,definitionId,options={}){const row=ctx.data?.presentation?.equipment_icons?.[definitionId]||ctx.data?.presentation?.icons?.[definitionId]||{};return itemIcon({...row,...options,fallback:'equipment',profile:options.profile||ctx.ui?.iconProfile||'compact'});}

export function portraitIcon(ctx,group=null){const key=group?({ordinary_farm:'farm',ordinary_cook:'cook',ordinary_gather:'gather',ordinary_alchemy:'alchemy',ordinary_build:'build'})[group.definition_id]:'player';const row=ctx.data?.presentation?.system_icons?.['portrait_'+key]||{};return itemIcon({...row,fallback:'character'});}

import {systemIcon} from './item-icon.js';
export function updateWorldControl(control,data,busy){
 if(!control)return;
 const world=data.view.world,paused=!!world?.paused,label=paused?'继续运行':'暂停世界';
 const settling=!!data.view.time?.pending&&!paused;
 control.disabled=busy||!world||(!world.can_pause&&!world.can_resume&&!settling);
 control.setAttribute('aria-label',label);control.setAttribute('title',label);control.setAttribute('aria-pressed',String(paused));control.dataset.paused=String(paused);
 const key=paused?'resume':'pause',row=data.presentation?.system_icons?.[key],id=row?.asset_id||'';
 if(!control.__stateIcon||control.__stateIcon.dataset.assetId!==id||control.__stateIcon.__runtimeURL!==(row?.asset?.url||null)){const icon=systemIcon({data},key);control.replaceChildren(icon);control.__stateIcon=icon;}
}

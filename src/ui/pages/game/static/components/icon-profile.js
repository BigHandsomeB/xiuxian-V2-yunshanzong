import {el,button} from './dom.js';
export const iconProfiles={compact:48,comfortable:64,detail:96};
export function displayProfile(ui){return ui.iconProfile==='comfortable'?'comfortable':'compact';}
export function profileControls(ctx){const row=el('div','icon-profiles');row.setAttribute('aria-label','图标显示尺寸');for(const [key,label]of [['compact','紧凑 · 48'],['comfortable','舒适 · 64']]){const control=button(label,()=>{ctx.ui.iconProfile=key;ctx.redraw();},'filter-chip');control.setAttribute('aria-pressed',String(displayProfile(ctx.ui)===key));row.append(control);}return row;}

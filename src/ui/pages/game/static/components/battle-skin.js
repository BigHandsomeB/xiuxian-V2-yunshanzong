import {runtimeURL} from '../battle/metadata.js';
// Approved runtime-only skin. Missing art retains CSS colors, text and controls.
export function battleSkin(node,ui={}){
 let available=false;
 for(const [role,row] of Object.entries(ui)){
  if(!['panel','reward','item','selected','primary','secondary','track','player_fill','enemy_fill','health_0','health_20','health_40','health_60','health_80','health_100'].includes(role)||!row?.asset)continue;
  try{const url=runtimeURL(row.asset.url);node.style.setProperty?.(`--battle-${role}`,`url("${url}")`);available=true;
   const inset=row.asset.nine_slice_insets;if(Array.isArray(inset)&&inset.length===4&&inset.every(v=>Number.isFinite(v)&&v>0))node.style.setProperty?.(`--battle-${role}-slice`,inset.join(' '));
  }catch{}
 }
 node.dataset.battleSkin=String(available);
}

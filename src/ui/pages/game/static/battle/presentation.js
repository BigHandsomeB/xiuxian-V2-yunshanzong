// Read committed facts only. No damage, HP, result or reward simulation here.
export function presentEvents(renderer,view,assets,{schedule=setTimeout,cancel=clearTimeout}={}){
 if(view.animation_allowed===false)return ()=>{};
 const timers=[];let disposed=false;const config=assets.fx_config;
 const criticals=new Set((view.latest_events||[]).filter(e=>e.kind==='critical').map(e=>e.actor));
 const playerAsset=assets.player?.asset_id,enemyAsset=assets.enemy?.asset_id;
 const duration=(role,action)=>{if(config){const p=role==='player'?config.hero:config.combat_fx_profiles[view.dungeon?.tier||'normal'];if(action==='attack'&&(role==='enemy'||config.hero_anim_mode==='effects'))return p.charge_ms+p.attack_ms+p.return_ms;if(action==='hit')return p.hit_ms;}const asset=role==='player'?playerAsset:enemyAsset,actions=assets.sprites?.[asset]?.actions,a=actions?.[action]||(action==='attack'?actions?.attack_combo:undefined);if(!a)return 360;return Array.isArray(a.duration)?a.duration.reduce((x,y)=>x+y,0):a.frameCount*a.duration;};
 const play=(role,action,key)=>renderer.play?.(role,action,key);
 const later=(fn,delay)=>timers.push(schedule(()=>{if(!disposed)fn();},delay));
 const shown=new Set();
 const effect=(role,key,at)=>{const stamp=role+':'+key;if(!assets.effects?.[key]||shown.has(stamp))return;shown.add(stamp);later(()=>renderer.effect?.(role,key),at);};
 const damageEffect=event=>{
  if(event.kind==='poison')return 'status_poison';
  if(event.kind==='dot')return {fire:'status_burn',poison:'status_poison',lightning:'lightning_arc'}[event.element];
  if(event.element==='lightning'&&['extra_hit','counter'].includes(event.kind))return 'lightning_arc';
  if(['fire','poison','ice','water','yin','lightning'].includes(event.element))return 'element_'+event.element;
  return event.damage_kind==='skill'?'spell_impact':undefined;
 };
 let cursor=0;
 for(const event of view.latest_events||[]){
  if(event.kind==='player_attack'||event.kind==='enemy_attack'){
   const role=event.actor,at=cursor;later(()=>play(role,'attack',`${view.battle_id}:${view.step}:${role}`),at);cursor+=duration(role,'attack');
   later(()=>play(role,'idle'),cursor);
  }else if(['damage','poison','dot','reflect','counter','extra_hit','heal','shield','lifesteal','revive'].includes(event.kind)){
   const at=Math.max(0,cursor-100);later(()=>{renderer.feedback?.({...event,effect_key:damageEffect(event),critical:event.kind==='damage'&&criticals.has(event.actor)},assets.slash?.asset);},at);
   if(event.kind==='revive')effect(event.target,'shield_fx',at);
  }else if(event.kind==='status_apply'){
   const key=event.status_id?.startsWith('charge_')||['skill_power','furnace_energy'].includes(event.status_id)?'cast_fx':event.status_id==='armor_down'?'impact':'status_'+event.status_id;
   effect(event.target,key,Math.max(0,cursor-100));
  }else if(event.kind==='skill'){effect(event.actor,'cast_fx',Math.max(0,cursor-100));
  }else if(event.kind==='cleanse'){effect(event.target,'heal_fx',Math.max(0,cursor-100));
  }else if(event.kind==='block'){effect(event.actor,'shield_fx',Math.max(0,cursor-100));
  }else if(event.kind==='miss'){const at=Math.max(0,cursor-100);later(()=>{play(event.target,'dodge',`${view.battle_id}:${view.step}:dodge`);renderer.feedback?.(event);},at);effect(event.target,'status_evade',at);later(()=>play(event.target,'idle'),at+(config?.hero.dodge_ms||200));
  }else if(event.kind==='player_hit'||event.kind==='enemy_hit'){
   const role=event.target,at=Math.max(0,cursor-100);later(()=>play(role,'hit',`${view.battle_id}:${view.step}:${role}:hit`),at);if(view[role].hp>0)later(()=>play(role,'idle'),at+duration(role,'hit'));
  }else if(event.kind==='enemy_defeated'||event.kind==='player_defeated'){
   const role=event.target,profile=role==='player'?config?.hero:config?.combat_fx_profiles[view.dungeon?.tier||'normal'];later(()=>play(role,'death',`${view.battle_id}:${view.step}:death`),cursor+180);later(()=>renderer.deathEffect?.(role),cursor+180+(profile?.death_fx_delay_ms||0));
  }
 }
 return ()=>{disposed=true;for(const timer of timers)cancel(timer);renderer.clearFeedback?.();};
}

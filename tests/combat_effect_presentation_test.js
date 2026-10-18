// Pure committed-event checks; no browser, network or game commands.
export function testCombatEffectPresentation(source){
 const present=new Function(source.replace(/^export /gm,'')+';return presentEvents;')();
 let checks=0;const assert=(v,msg)=>{if(!v)throw Error(msg);checks++;};
 const keys=['cast_fx','spell_impact','impact','heal_fx','shield_fx','element_fire','element_poison','element_ice','element_water','element_yin','element_lightning','lightning_arc','status_freeze','status_fire_down','status_burn','status_poison','status_chill','status_evade','status_speed','status_seal'];
 const assets={effects:Object.fromEntries(keys.map(k=>[k,{asset_id:k}]))};
 const run=(events,options={})=>{
  const timers=[],calls=[],cancelled=[];let clears=0;
  const view={battle_id:'fixture',step:1,latest_events:events,...options};const before=JSON.stringify(view);
  const stop=present({feedback:e=>calls.push(['feedback',e]),effect:(role,key)=>calls.push(['effect',role,key]),play:()=>{},clearFeedback:()=>clears++},view,assets,{schedule:f=>(timers.push(f),timers.length),cancel:id=>cancelled.push(id)});
  return {calls,timers,stop,cancelled,clears:()=>clears,view,before};
 };
 for(const [element,key] of [['fire','element_fire'],['poison','element_poison'],['ice','element_ice'],['water','element_water'],['yin','element_yin'],['lightning','element_lightning'],['neutral','spell_impact']]){
  const r=run([{kind:'damage',actor:'player',target:'enemy',element,damage_kind:'skill',damage:12}]);r.timers.forEach(f=>f());assert(r.calls[0][1].effect_key===key,'actual element '+element);assert(JSON.stringify(r.view)===r.before,'read-only');r.stop();
 }
 for(const [kind,element,key] of [['dot','fire','status_burn'],['dot','poison','status_poison'],['poison',undefined,'status_poison'],['extra_hit','lightning','lightning_arc'],['counter','lightning','lightning_arc']]){
  const r=run([{kind,element,actor:'player',target:'enemy',damage:2},{kind:'critical',actor:'player'}]);r.timers.forEach(f=>f());assert(r.calls[0][1].effect_key===key&&!r.calls[0][1].critical,'secondary effect without critical');r.stop();
 }
 for(const status of ['freeze','fire_down','burn','poison','chill','evade','speed','seal']){
  const r=run([{kind:'status_apply',target:'enemy',status_id:status},{kind:'status_apply',target:'enemy',status_id:status}]);r.timers.forEach(f=>f());assert(r.calls.length===1&&r.calls[0][2]==='status_'+status,'bounded status '+status);r.stop();
 }
 for(const [event,key,role] of [[{kind:'skill',actor:'player'},'cast_fx','player'],[{kind:'cleanse',target:'player'},'heal_fx','player'],[{kind:'block',actor:'enemy'},'shield_fx','enemy'],[{kind:'status_apply',target:'player',status_id:'charge_3'},'cast_fx','player'],[{kind:'status_apply',target:'enemy',status_id:'armor_down'},'impact','enemy']]){
  const r=run([event]);r.timers.forEach(f=>f());assert(r.calls.some(c=>c[0]==='effect'&&c[1]===role&&c[2]===key),'reuse '+key);r.stop();
 }
 const old=run([{kind:'damage',actor:'player',target:'enemy',damage:3}]);old.timers.forEach(f=>f());assert(old.calls[0][1].effect_key===undefined,'legacy facts remain valid');old.stop();
 const offline=run([{kind:'skill',actor:'player'}],{animation_allowed:false});assert(offline.timers.length===0,'compressed results never play');offline.stop();
 const cancelled=run([{kind:'skill',actor:'player'}]);cancelled.stop();cancelled.timers.forEach(f=>f());assert(cancelled.calls.length===0&&cancelled.cancelled.length===1&&cancelled.clears()===1,'cleanup cancels effects');
 return {checks,status:'PASS',device_visual_verified:false};
}

import { validateSprite, runtimeURL, frameAt } from './metadata.js';
export const BATTLE_CSS_PATH = 'battle/battle.css';

export function mountBattle(host, options = {}) {
  const doc = host.ownerDocument, win = doc.defaultView;
  const make = (tag, cls, text = '') => { const n = doc.createElement(tag); n.className = cls; n.textContent = text; return n; };
  const root = make('section', 'battle-scene');
  root.setAttribute('aria-label', '战斗场景');
  const layers = {};
  for (const name of ['background', 'player', 'enemy', 'effect', 'hud']) {
    layers[name] = make('div', `battle-layer battle-layer--${name}`); root.append(layers[name]);
  }
  layers.background.append(make('div', 'battle-landscape'));
  if (!options.combat) {
    layers.effect.append(make('small', 'battle-effect-placeholder', '灵气特效待接入'));
    layers.hud.append(make('p', 'battle-status', '战斗系统开发中'));
  }
  const health = make('div', 'battle-health-slots'), hpNodes = {};
  for (const [role,label] of [['player','主角'],['enemy','妖兽']]) {
    const slot=make('div','battle-health-slot'),name=make('span','battle-actor-name',label),stats=make('div','battle-actor-stats'),values={};
    for(const [key,title,glyph] of [['hp','生命','♥'],['attack','攻击','⚔'],['defense','护甲','盾']]){
      const stat=make('span','battle-stat'),icon=make('span','battle-stat-icon'),fallback=make('span','',glyph),value=make('span','battle-stat-value','—');
      stat.setAttribute('aria-label',title);icon.setAttribute('aria-hidden','true');icon.append(fallback);
      const asset=options.statIcons?.[key]?.asset;
      if(asset?.url){try{const image=make('img','');image.alt='';image.width=20;image.height=20;image.src=runtimeURL(asset.url);fallback.hidden=true;const error=()=>{image.remove();fallback.hidden=false;};image.addEventListener('error',error);icon.append(image);}catch{}}
      stat.append(icon,value);stats.append(stat);values[key]=value;
    }
    slot.append(name,stats);health.append(slot);hpNodes[role]={name,values};
  }
  layers.hud.append(health);
  if (!options.combat) {
    const skills = make('div', 'battle-skill-slots');
    for (const label of ['普攻', '身法', '技能', '绝技']) { const slot = make('button', 'battle-skill-slot', label); slot.disabled = true; slot.type = 'button'; slot.setAttribute('aria-label', label + '尚未开放'); skills.append(slot); }
    layers.hud.append(skills);
  }
  const headings = Array.from(host.children).filter(child => /^H[1-6]$/.test(child.tagName));
  host.replaceChildren(...headings, root);
  let assets = options.assets || {};const sprites = {}, failed = new Set(), listeners = [], transients=new Set();
  const fxPool=[],numberPool=[];let fxSerial=0;
  const config=()=>assets.fx_config;
  const mode=()=>options.hero_anim_mode||config()?.hero_anim_mode||'frames';
  const online=()=>state.online??options.online??true;
  const cap=()=>config()?.max_effects||8;
  const fxCount=()=>actors.filter(a=>a.role==='effect').length+numberPool.filter(n=>!n.hidden).length;
  const report = (id, error) => options.onMetadataError?.({ id, error });
  for (const [id, data] of Object.entries(assets.sprites || {})) {
    try { sprites[id] = validateSprite(data); } catch (error) { report(id, error); }
  }
  let backgroundNode=null,backgroundKey=null,backgroundDetach=()=>{};
  listeners.push(()=>backgroundDetach());
  function updateBackground(){
    const row=assets.background,key=row?.url||null;
    if(key===backgroundKey)return; // Floors in the same dungeon retain the loaded image.
    backgroundDetach();backgroundNode?.remove();backgroundNode=null;backgroundKey=key;backgroundDetach=()=>{};
    if(!row)return;
    try {
      if (!(row.width > 0 && row.height > 0)) throw Error('Background runtime dimensions required');
      const url=runtimeURL(row.url),background=make('img','battle-background');background.alt='';background.width=row.width;background.height=row.height;
      const box=row.content_box;
      if(Array.isArray(box)&&box.length===4&&box.every(Number.isFinite)&&box[0]>=0&&box[1]>=0&&box[2]<=row.width&&box[3]<=row.height&&box[2]>box[0]&&box[3]>box[1]){
        const w=box[2]-box[0],h=box[3]-box[1];background.style.width=`${row.width/w*100}%`;background.style.height=`${row.height/h*100}%`;background.style.left=`${-box[0]/w*100}%`;background.style.top=`${-box[1]/h*100}%`;background.style.objectFit='fill';
      }
      const error=()=>background.remove();background.addEventListener('error',error);backgroundDetach=()=>background.removeEventListener('error',error);
      background.src=url;layers.background.append(background);backgroundNode=background;
    }catch(error){report('background',error);}
  }
  updateBackground();
  let destroyed = false, visible = false, raf = null, last = null, state = {}, actors = [];
  const media = win.matchMedia?.('(prefers-reduced-motion: reduce)');
  const finite = (v, fallback) => Number.isFinite(v) ? v : fallback;
  function actionFor(role,sprite,name){
    if(config()&&role==='player'&&mode()==='effects')return sprite?.actions.idle;
    return sprite?.actions[name]||(name==='attack'?sprite?.actions.attack_combo:undefined)||
      (config()&&(sprite?.static||name==='dodge')?sprite?.actions.idle:undefined);
  }
  function actor(role, spec, index) {
    const position = make('div', 'battle-position');
    const viewport = make('div', 'battle-sprite');
    const placeholder = make('span', `battle-placeholder battle-placeholder--${role}`, role === 'player' ? '修士' : '妖兽');
    const image = make('img', 'battle-sheet'); image.alt = ''; image.draggable = false;
    viewport.append(image); position.append(viewport, placeholder); layers[role].append(position);
    const sprite = sprites[spec.asset], action = actionFor(role,sprite,spec.action||'idle');
    const a = { motionAction:role==='enemy'&&online()?'intro':spec.action||'idle',motionElapsed:0, role, spec, index, position, viewport, placeholder, image, sprite, action, elapsed: 0, started: false, cursor: 0, frame: -1 };
    const error = () => { failed.add(spec.asset); viewport.hidden = true; placeholder.hidden = false; };
    image.addEventListener('error', error); a.detach = () => image.removeEventListener('error', error);
    const scale = Math.max(.5, finite(spec.scale, 1)), facing = ((spec.facing || (role==='enemy'?'left':'right')) === 'left' ? -1 : 1) * (sprite?.authoredFacing==='left'?-1:1);
    position.style.left = `${finite(spec.x, role === 'player' ? 30 : 70)}%`;
    position.style.top = `${finite(spec.y, 70)}%`;
    position.style.zIndex = String(Math.round(finite(spec.z, index)));
    position.setAttribute('data-action',spec.action||'idle');
    position.setAttribute('data-role',role);
    if(sprite?.static)position.setAttribute('data-static','true');
    if (sprite && action && !failed.has(spec.asset)) {
      placeholder.hidden = true;
      viewport.style.width = `${sprite.width}px`; viewport.style.height = `${sprite.height}px`;
      viewport.style.transformOrigin = `${sprite.anchor.x}px ${sprite.anchor.y}px`;
      viewport.style.transform = `translate(${-sprite.anchor.x}px, ${-sprite.anchor.y}px) scale(${scale * facing}, ${scale})`;
      draw(a);
    } else { viewport.hidden = true; if (spec.asset && sprite && !action) report(spec.asset, Error('Unknown action')); }
    return a;
  }
  function draw(a) {
    if (!a.action || failed.has(a.spec.asset)) return;
    const staticHero=a.role==='player'&&mode()==='effects';
    const action=staticHero?(a.sprite.actions.idle||a.action):a.action;
    const frame = staticHero?0:frameAt(action, a.elapsed); if (frame === a.frame) return; a.frame = frame;
    const f = action.frames[frame];
    if (a.image.getAttribute('src') !== f.url) a.image.src = f.url;
    a.image.style.width = `${f.sheetWidth}px`; a.image.style.height = `${f.sheetHeight}px`;
    a.image.style.transform = `translate(${-f.x}px, ${-f.y}px)`;
  }
  function trigger(a, frame) {
    for (const t of a.action.triggers.filter(t => t.frame === frame)) {
      options.onEffectTrigger?.({ ...t, role: a.role, asset: a.spec.asset, x: finite(a.spec.x, 50) + t.x, y: finite(a.spec.y, 70) + t.y });
    }
  }
  function advance(a, delta) {
    if (!a.action) return;
    if (!a.started) { a.started = true; trigger(a, 0); }
    a.elapsed += delta;
    // Walk every crossed boundary, including repeated loops; elapsed is paused offscreen.
    let boundary = a.action.durations.slice(0, a.cursor % a.action.frameCount + 1).reduce((x, y) => x + y, 0);
    const total = a.action.durations.reduce((x, y) => x + y, 0);
    boundary += Math.floor(a.cursor / a.action.frameCount) * total;
    while (a.elapsed >= boundary && (a.action.loop || a.cursor < a.action.frameCount - 1)) {
      a.cursor++; trigger(a, a.cursor % a.action.frameCount);
      boundary += a.action.durations[a.cursor % a.action.frameCount];
      if (destroyed) return;
    }
    draw(a);
    if(a.role==='effect'&&!a.action.loop&&a.elapsed>=total){actors=actors.filter(x=>x!==a);if(config()){a.position.hidden=true;if(!fxPool.includes(a))fxPool.push(a);}else{a.detach();a.position.remove();}}
  }
  function profile(a){
    const cfg=config();if(!cfg)return {};
    return a.role==='player'?cfg.hero:cfg.combat_fx_profiles[a.spec.tier||'normal']||cfg.combat_fx_profiles.normal;
  }
  function phase(a){let h=0;for(const c of String(a.spec.id||a.spec.asset||''))h=(h*31+c.charCodeAt(0))>>>0;return (h+a.index*137)%2000;}
  function motion(a,delta){
    const cfg=config();if(!cfg)return;if(!online()){a.position.style.transform='translate(0px,0px) scale(1)';a.position.style.opacity='1';a.image.style.filter=a.spec.action==='death'?'grayscale(1)':'';a.flashLeft=0;return;}if(a.role==='player'&&mode()==='frames'&&!media?.matches){a.image.style.filter='';a.flashLeft=0;return;}
    const p=profile(a),moving=cfg.movement[a.spec.movement||'ground']||cfg.movement.ground;
    a.visualAge=(a.visualAge||0)+delta;a.motionElapsed=(a.motionElapsed||0)+delta;a.flashLeft=Math.max(0,(a.flashLeft||0)-delta);
    const t=Math.floor(a.motionElapsed/cfg.step_ms)*cfg.step_ms,dir=a.role==='player'?1:-1;
    let x=0,y=0,opacity=1,scale=1,filter=a.flashLeft>0?'brightness(0) invert(1)':'';
    if(!media?.matches){
      const period=p.idle_ms*moving.period_scale*(a.lowHp&&a.spec.tier==='boss'?p.phase_period_scale:1);
      const step=Math.floor((a.visualAge+phase(a))/period*8)%8;
      y=Math.round([0,-1,-2,-1,0,1,2,1][step]*p.idle_px/2*moving.idle_scale);
      if(a.motionAction==='attack'){
        if(t<p.charge_ms)x=t%100?1:-1;
        else if(t<p.charge_ms+p.attack_ms)x=dir*Math.round(p.attack_px*moving.attack_scale);
        else if(t<p.charge_ms+p.attack_ms+p.return_ms)x=dir*Math.round(p.attack_px*moving.attack_scale*(1-(t-p.charge_ms-p.attack_ms)/p.return_ms));
        if(p.shake_px&&t>=p.charge_ms&&t<p.charge_ms+p.attack_ms)root.style.transform=`translate(${t%100?p.shake_px:-p.shake_px}px,0)`;
        else root.style.transform='';
      }else if(a.motionAction==='hit'&&t<p.hit_ms)x=-dir*(a.critical?p.critical_hit_px:p.hit_px)*(t%100?1:-1);
      else if(a.motionAction==='dodge'&&t<p.dodge_ms){x=-dir*p.dodge_px;filter=`drop-shadow(${-dir*4}px 0 0 ${cfg.colors.hit})`;a.image.style.opacity=t%100?'.45':'1';}
      else if(a.motionAction==='death'){y=Math.round(p.death_sink_px*Math.min(1,t/p.death_ms));opacity=Math.max(0,1-t/p.death_ms);scale=a.role==='player'?1:Math.max(.2,opacity);filter=a.role==='player'?'grayscale(1)':t<p.flash_ms||(p.death_blink_ms&&t<p.death_ms&&Math.floor(t/p.death_blink_ms)%2===0)?'brightness(0) invert(1)':'';}
      if(a.role==='enemy'&&a.motionAction==='intro'&&t<p.entry_ms){if(a.spec.tier==='boss'){y=-Math.round(p.entry_px*(1-t/p.entry_ms));opacity=t/p.entry_ms;}else{x=Math.round(p.entry_px*(1-t/p.entry_ms));if(a.spec.tier==='elite'&&t<80)filter='brightness(0) invert(1)';}}
      const contour=a.spec.tier==='boss'&&a.lowHp?cfg.colors.boss_phase:a.spec.tier==='elite'&&step%2?cfg.colors.elite:null;
      if(contour&&!a.flashLeft){const radius=p.outline_px||1;filter+=(filter?' ':'')+[[radius,0],[-radius,0],[0,radius],[0,-radius]].map(([dx,dy])=>`drop-shadow(${dx}px ${dy}px 0 ${contour})`).join(' ');}
      a.image.style.outline='';
    }else{root.style.transform='';a.image.style.outline='';}
    a.position.style.transform=`translate(${x}px,${y}px) scale(${scale})`;a.position.style.opacity=String(opacity);a.image.style.filter=filter;
    if(a.motionAction!=='dodge')a.image.style.opacity='1';
    a.position.dataset.movement=a.spec.movement||'ground';
  }
  let hostSuspended=false;
  const running = () => !hostSuspended && !destroyed && visible && !doc.hidden && online();
  function tick(time) {
    raf = null; if (!running()) return;
    const delta = last === null ? 0 : Math.min(250, Math.max(0, time - last)); last = time;
    root.style.transform='';
    for (const a of actors.slice()) {
      if(!media?.matches&&!(a.role==='player'&&mode()==='effects'))advance(a, delta);
      if(config()&&a.role!=='effect')motion(a,delta);
      if (destroyed) return;
    }
    for(const n of numberPool)if(!n.hidden){n.fxElapsed+=delta;n.style.transform=`translate(-50%,${-Math.floor(n.fxElapsed/100)*2}px) scale(${n.fxScale||1})`;n.style.opacity=String(1-Math.floor(n.fxElapsed/100)/6);if(n.fxElapsed>=600){n.fxDone?.();n.hidden=true;}}
    schedule();
  }
  function schedule() {
    if (!running()) { if (raf !== null) win.cancelAnimationFrame(raf); raf = null; last = null; return; }
    if (raf === null && (config()&&!media?.matches||numberPool.some(n=>!n.hidden)||actors.some(a=>a.flashLeft>0)||!media?.matches&&actors.some(a => a.action && !failed.has(a.spec.asset) && (a.action.loop || a.elapsed < a.action.durations.reduce((x, y) => x + y, 0))))) raf = win.requestAnimationFrame(tick);
  }
  function configure(a,spec) {
    const changedIdentity=a.spec.id!==spec.id;
    const changed=(a.spec.action||'idle')!==(spec.action||'idle')||a.spec.playbackKey!==spec.playbackKey;
    if(changedIdentity&&a.role==='enemy'){a.motionAction=online()?'intro':'idle';a.motionElapsed=0;}
    a.spec=spec;a.sprite=sprites[spec.asset];const scale=Math.max(.5,finite(spec.scale,1)),facing=((spec.facing||(a.role==='enemy'?'left':'right'))==='left'?-1:1)*(a.sprite?.authoredFacing==='left'?-1:1);if(a.sprite)a.viewport.style.transform=`translate(${-a.sprite.anchor.x}px, ${-a.sprite.anchor.y}px) scale(${scale*facing}, ${scale})`;a.position.style.left=`${finite(spec.x,a.role==='player'?30:70)}%`;a.position.style.top=`${finite(spec.y,70)}%`;
    a.position.setAttribute('data-action',spec.action||'idle');
    if(changed){a.motionElapsed=0;a.motionAction=spec.action||'idle';if(a.motionAction==='idle')a.critical=false;if(a.motionAction==='hit')a.flashLeft=profile(a).flash_ms;}
    if(changed){a.action=actionFor(a.role,a.sprite,spec.action||'idle');a.elapsed=0;a.cursor=0;a.started=false;a.frame=-1;
      a.viewport.hidden=!a.action||failed.has(spec.asset);a.placeholder.hidden=!a.viewport.hidden;draw(a);
    }
  }
  function update(next = {}, nextAssets = null) {
    if (destroyed) return;
    if(nextAssets){assets=nextAssets;for(const [id,data] of Object.entries(assets.sprites||{})){try{sprites[id]=validateSprite(data);}catch(error){report(id,error);}}}
    updateBackground();
    const changedMode=root.dataset.heroAnimMode&&root.dataset.heroAnimMode!==mode();
    state=next;root.dataset.heroAnimMode=mode();root.dataset.fxFramework=String(!!config());root.dataset.suspended=String(hostSuspended||doc.hidden||!online());if(!online())clearFeedback();
    const specs=[['player',state.player||{},0],...(state.enemies||[{}]).map((s,i)=>['enemy',s,i]),...(online()?(state.effects||[]):[]).slice(0,cap()).map((s,i)=>['effect',s,i])],previous=actors.slice(),nextActors=[];
    for(const [role,spec,index] of specs){const old=previous.find(a=>a.role===role&&a.index===index&&a.spec.asset===spec.asset);
      if(old){configure(old,spec);if(changedMode&&role==='player'){old.position.style.transform='translate(0px,0px) scale(1)';old.position.style.opacity='1';old.image.style.filter='';old.frame=-1;draw(old);}nextActors.push(old);}else nextActors.push(actor(role,spec,index));
    }
    for(const old of previous)if(!nextActors.includes(old)){if(old.role==='effect'){old.position.hidden=true;if(!fxPool.includes(old))fxPool.push(old);}else{old.detach();old.position.remove();}}
    actors=nextActors;if(!online())for(const a of actors)motion(a,0);last=null;schedule();
  }
  function healthView(view){
    if(destroyed)return;
    for(const role of ['player','enemy']){
      const value=view[role],n=hpNodes[role];n.name.textContent=value.name;
      n.values.hp.textContent=`${Math.round(value.hp)} / ${Math.round(value.max_hp)}`;
      n.values.attack.textContent=Number.isFinite(value.attack)?String(Math.round(value.attack)):'—';
      const a=actors.find(x=>x.role===role);if(a)a.lowHp=value.max_hp>0&&value.hp/value.max_hp<(profile(a).phase_threshold||.5);
      n.values.defense.textContent=Number.isFinite(value.armor)?String(Math.round(value.armor)):'—';
    }
  }
  function play(role,action,playbackKey){
    if(destroyed||!online())return;const a=actors.find(a=>a.role===role&&a.index===0);if(!a)return;
    configure(a,{...a.spec,action,playbackKey});last=null;schedule();
  }
  function rest(view){for(const role of ['player','enemy'])play(role,view[role].hp===0?'death':'idle');}
  function clearFeedback(){for(const done of [...transients])done();for(const a of actors.filter(a=>a.role==='effect')){a.position.hidden=true;if(!fxPool.includes(a))fxPool.push(a);}actors=actors.filter(a=>a.role!=='effect');for(const n of numberPool)n.hidden=true;if(!config()){for(const child of Array.from(layers.effect.children))child.remove();for(const a of fxPool)a.detach();fxPool.length=0;numberPool.length=0;}schedule();}
  function effectAt(key,a){
    if(destroyed||hostSuspended||!online()||doc.hidden||media?.matches)return false;
    const id=assets.effects?.[key]?.asset_id||(key==='slash'?assets.slash?.asset_id:null),meta=sprites[id];
    if(!meta||fxCount()>=cap())return false;
    const action=Object.keys(meta.actions)[0],spec={asset:id,action,x:finite(a.spec.x,50),y:58,playbackKey:++fxSerial};
    let fx=fxPool.find(x=>x.spec.asset===id);
    if(fx){fxPool.splice(fxPool.indexOf(fx),1);configure(fx,spec);fx.position.hidden=false;}else{
      if(fxPool.length+actors.filter(x=>x.role==='effect').length>=cap()){
        const retired=fxPool.shift();if(!retired)return false;
        retired.detach();retired.position.remove();
      }
      fx=actor('effect',spec,actors.length);
    }
    actors.push(fx);schedule();return true;
  }
  function deathEffect(role){const a=actors.find(x=>x.role===role&&x.index===0);if(a&&online()&&!doc.hidden&&!media?.matches)effectAt('death_fx',a);}
  function feedback(event,effect){
    if(destroyed||doc.hidden||!online())return;
    const a=actors.find(a=>a.role===event.target&&a.index===0);if(!a)return;
    if(media?.matches){a.flashLeft=profile(a).flash_ms;motion(a,0);schedule();return;}
    if(fxCount()>=cap())return;
    let number=numberPool.find(n=>n.hidden);if(!number){if(numberPool.length>=cap())return;number=make('span','battle-damage-number');numberPool.push(number);}
    number.fxDone?.();number.hidden=false;number.fxElapsed=0;number.dataset.spark='';number.style.opacity='1';number.textContent=event.kind==='miss'?'闪避':`${['heal','lifesteal','revive','shield'].includes(event.kind)?'+':'−'}${Math.round(event.damage)}`;number.style.fontSize='var(--text-section)';number.fxScale=event.critical?(profile(a).critical_scale||1.5):1;number.style.left=a.position.style.left;number.style.top='48%';if(!Array.from(layers.effect.children).includes(number))layers.effect.append(number);
    let slash=null;
    if(event.kind==='miss'){a.motionAction='dodge';a.motionElapsed=0;}
    if(event.critical){a.critical=true;a.flashLeft=profile(a).flash_ms;effectAt('critical_fx',a);}
    if(!media?.matches){
      const helpful=['heal','lifesteal','revive','shield'].includes(event.kind);
      const custom=event.effect_key&&assets.effects?.[event.effect_key];
      const shown=effectAt(helpful?(event.kind==='shield'?'shield_fx':'heal_fx'):custom?event.effect_key:event.actor==='player'?'slash':'impact',a);
      if(shown&&!helpful&&!custom&&event.actor==='player')effectAt('impact',a);
      if(!shown){number.dataset.spark='generic';number.style.color=profile(a).color||config()?.colors.hit||'var(--accent-2)';}
    }
    const done=()=>{number.removeEventListener('animationend',done);transients.delete(done);number.hidden=true;slash?.remove();};transients.add(done);number.fxDone=done;number.addEventListener('animationend',done,{once:true});
    if(media?.matches)done();
  }
  function checkVisibility() {
    const rect = root.getBoundingClientRect();
    visible = rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.right > 0 && rect.top < win.innerHeight && rect.left < win.innerWidth;
    schedule();
  }
  const observer = win.IntersectionObserver ? new win.IntersectionObserver(entries => { visible = entries.some(e => e.isIntersecting); schedule(); }) : null;
  observer?.observe(root);
  const visibility = () => {root.dataset.suspended=String(hostSuspended||doc.hidden||!online());if(media?.matches){clearFeedback();root.style.transform='';for(const a of actors)if(a.role!=='effect')motion(a,0);}schedule();}; doc.addEventListener('visibilitychange', visibility);
  media?.addEventListener('change', visibility);
  if (!observer) { win.addEventListener('scroll', checkVisibility, true); win.addEventListener('resize', checkVisibility); }
  update(options.state);
  if (!observer) checkVisibility();
  function cleanup() {
    if (destroyed) return; destroyed = true;
    clearFeedback();
    if (raf !== null) win.cancelAnimationFrame(raf); raf = null;
    observer?.disconnect(); doc.removeEventListener('visibilitychange', visibility);
    media?.removeEventListener('change', visibility);
    if (!observer) { win.removeEventListener('scroll', checkVisibility, true); win.removeEventListener('resize', checkVisibility); }
    for (const a of [...actors,...fxPool]) a.detach(); for (const remove of listeners) remove(); actors = []; root.remove();
  }
  cleanup.suspend=()=>{hostSuspended=true;clearFeedback();schedule();root.dataset.suspended='true';};cleanup.resume=()=>{hostSuspended=false;schedule();root.dataset.suspended=String(doc.hidden||!online());};
  cleanup.effect=(role,key)=>{const a=actors.find(x=>x.role===role&&x.index===0);if(a&&online()&&!doc.hidden&&!media?.matches)effectAt(key,a);};
  cleanup.deathEffect=deathEffect;cleanup.update = update;cleanup.health=healthView;cleanup.play=play;cleanup.rest=rest;cleanup.feedback=feedback;cleanup.clearFeedback=clearFeedback;
  return cleanup;
}

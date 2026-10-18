// Native isolate harness, matching danding_ui_test.js; also usable as an ES module.
export function testArtifactBattle(metadataSource, battleSource, context={}) {
  const assert = (v, message) => { if (!v) throw Error(message); };
  const metadata = new Function(metadataSource.replace(/export /g, '') + ';return {validateSprite,runtimeURL,frameAt};')();
  const { validateSprite, runtimeURL, frameAt } = metadata;
  const frames = [0, 1, 2].map(i => ({ url: '/game/runtime/hero.png', x: i * 16, y: 0, sheetWidth: 48, sheetHeight: 24 }));
  const sprite = { width: 16, height: 24, anchor: { x: 8, y: 24 }, actions: { idle: { frameCount: 3, frames, duration: [50, 100, 50], loop: true, triggers: [{ frame: 1, effect: 'sword' }] } } };
  const action = validateSprite(sprite).actions.idle;
  assert(frameAt(action, 49) === 0 && frameAt(action, 50) === 1 && frameAt(action, 200) === 0, 'Duration and loop boundaries');
  assert(frameAt({ ...action, loop: false }, 999) === 2, 'Non-loop holds final frame');
  for (const bad of [ { ...sprite, anchor: { x: 100, y: 0 } }, { ...sprite, actions: { idle: { ...sprite.actions.idle, frameCount: 4 } } }, { ...sprite, actions: { idle: { ...sprite.actions.idle, duration: 0 } } }, { ...sprite, actions: { idle: { ...sprite.actions.idle, frames: frames.map(f => ({ ...f, x: 99 })) } } } ]) {
    let rejected = false; try { validateSprite(bad); } catch { rejected = true; } assert(rejected, 'Invalid metadata rejected');
  }
  for (const url of ['javascript:alert(1)', 'data:image/png;base64,abc', '//user:pass@example.com/a', 'https://example.com/source.png', '/game/runtime/../source.png']) { let rejected = false; try { runtimeURL(url); } catch { rejected = true; } assert(rejected, 'Unsafe URL rejected'); }
  const events = new Map(), requests = new Map(), observers = []; let serial = 0;
  const eventTarget = () => ({ addEventListener(k, f) { events.set(this.key + k, f); }, removeEventListener(k) { events.delete(this.key + k); } });
  const media = { ...eventTarget(), key: 'media', matches: false };
  const win = { ...eventTarget(), key: 'win', innerWidth: context.width||400, innerHeight: 800, matchMedia: () => media,
    requestAnimationFrame(f) { requests.set(++serial, f); return serial; }, cancelAnimationFrame(id) { requests.delete(id); },
    IntersectionObserver: class { constructor(f) { this.callback = f; observers.push(this); } observe() {} disconnect() { this.disconnected = true; } } };
  const doc = { ...eventTarget(), key: 'doc', hidden: false, defaultView: win, documentElement:{dataset:{theme:context.theme||'light'}}, createElement: () => node() };
  function node(tagName = 'div') { return { ...eventTarget(), key: String(++serial), tagName: tagName.toUpperCase(), ownerDocument: doc, style: {}, children: [], attrs: {}, dataset:{}, hidden: false,
    append(...nodes) { for (const n of nodes) { n.parent = this; this.children.push(n); } },
    replaceChildren(...nodes) { for (const n of this.children) n.parent = null; this.children = []; this.append(...nodes); },
    remove() { if (this.parent) this.parent.children = this.parent.children.filter(n => n !== this); },
    setAttribute(k, v) { this.attrs[k] = v; }, getAttribute(k) { return this.attrs[k]; }, removeAttribute(k) { delete this.attrs[k]; }, set src(v) { this.attrs.src = v; },
    getBoundingClientRect: () => ({ width: context.width||400, height: 500, top: 0, left: 0, right: context.width||400, bottom: 500 }) }; }
  const mountBattle = new Function('validateSprite', 'runtimeURL', 'frameAt', battleSource.replace(/^import[^\n]+\n/, '').replace(/export /g, '') + ';return mountBattle;')(validateSprite, runtimeURL, frameAt);

  let checks=0;const check=(v,m)=>{assert(v,m);checks++;};
  const host=node(),state={player:{asset:'hero',x:24,y:74},enemies:[{asset:'hero'}],online:true};
  const scene=mountBattle(host,{combat:true,assets:{sprites:{hero:sprite}},state});
  const health={player:{name:'主角',hp:90,max_hp:90,attack:12,armor:1},enemy:{name:'妖兽',hp:20,max_hp:20},battle_id:'one',step:0,latest_events:[]};
  observers[0].callback([{isIntersecting:true}]);
  scene.health(health);check(!host.children[0].children[1].children.some(n=>n.className==='battle-artifact'),'no floating artifact when unequipped');
  health.artifact={artifact_id:'slayer_sword',name:'斩妖飞剑',glyph:'剑',motion_profile_id:'strike'};scene.health(health);
  const treasureNode=host.children[0].children[1].children.find(n=>n.className==='battle-artifact');
  check(treasureNode&&!treasureNode.hidden&&treasureNode.attrs['aria-label']==='斩妖飞剑','equipped artifact has correct identity and accessible name');
  check(treasureNode.style.left==='15%'&&treasureNode.style.top==='42%','floats above and left of protagonist');
  const artAssets={sprites:{hero:sprite},artifact_icons:{slayer_sword:{asset:{url:'/game/runtime/artifact-v1.png'}}}};
  scene.update(state,artAssets);scene.health(health);
  const artImage=treasureNode.children[1];
  check(artImage?.attrs.src==='/game/runtime/artifact-v1.png'&&treasureNode.dataset.image==='true','published image replaces glyph');
  scene.health({...health,step:1});check(treasureNode.children[1]===artImage,'refresh retains image node');
  events.get(artImage.key+'error')();check(treasureNode.dataset.image==='false'&&!treasureNode.children[0].hidden,'failed image reveals glyph');
  artAssets.artifact_icons.slayer_sword.asset.url='/game/runtime/artifact-v2.png';scene.update(state,artAssets);scene.health(health);
  check(treasureNode.children[1]!==artImage&&treasureNode.children[1].attrs.src.endsWith('v2.png'),'new publication replaces image');
  artAssets.artifact_icons.slayer_sword.asset.url='javascript:alert(1)';scene.update(state,artAssets);scene.health(health);
  check(treasureNode.dataset.image==='false','unsafe artifact URL uses glyph fallback');
  const tick=time=>{const callbacks=[...requests.values()];requests.clear();for(const f of callbacks)f(time);};
  tick(0);tick(100);const idle=treasureNode.style.transform;
  for(const motion of ['strike','spin','absorb','pulse','pour']){
    health.step++;health.artifact.motion_profile_id=motion;health.latest_events=[{actor:'player',source_name:'斩妖飞剑',kind:'damage'}];scene.health(health);tick(200+health.step*100);
    check(treasureNode.style.transform!==idle,'programmed action '+motion);
    check(host.children[0].children[1].children.filter(n=>n.className==='battle-artifact').length===1,'one retained floating node');
  }
  scene.suspend();check(!requests.size,'world pause clears shared RAF');scene.resume();check(requests.size===1,'resume schedules one shared RAF');
  doc.hidden=true;events.get('docvisibilitychange')();check(!requests.size,'background pauses artifact animation');
  doc.hidden=false;events.get('docvisibilitychange')();
  observers[0].callback([{isIntersecting:false}]);check(!requests.size,'offscreen pauses artifact animation');
  observers[0].callback([{isIntersecting:true}]);media.matches=true;events.get('mediachange')();scene.health(health);check(treasureNode.style.transform==='','reduced motion keeps static artifact');
  delete health.artifact;scene.health(health);check(treasureNode.hidden,'unequip hides floating artifact');
  scene();check(!requests.size&&!events.size&&!host.children.length,'exit releases artifact with scene');
  return {checks};
}

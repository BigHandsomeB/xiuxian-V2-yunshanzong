// Native isolate harness, matching danding_ui_test.js; also usable as an ES module.
export function testGameBattle(metadataSource, battleSource, effectConfig=null, context={}) {
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
  const host = node(), triggered = [], errors = [];
  const state = { player: { asset: 'hero', x: 25, y: 70, scale: 2, facing: 'left', z: 7 }, effects: [{ asset: 'hero', x: 50 }] };
  const cleanup = mountBattle(host, { assets: { sprites: { hero: sprite, bad: {} } }, state, onEffectTrigger: e => triggered.push(e), onMetadataError: e => errors.push(e) });
  assert(host.children[0].children.length === 5 && !requests.size && errors.length === 1, 'Five layers; offscreen has no RAF; invalid asset isolated');
  observers[0].callback([{ isIntersecting: true }]);
  const tick = time => { const [id, f] = [...requests][0]; requests.delete(id); f(time); };
  tick(0); tick(160); assert(triggered.length === 2, 'Crossed trigger emitted for player and independent effect');
  const playerLayer = host.children[0].children[1];
  assert(playerLayer.children[0].style.zIndex === '7', 'Metadata z order');
  cleanup.update({ ...state, player: { ...state.player, x: 40 } });
  assert(playerLayer.children[0].style.left === '40%' && playerLayer.children[0].children[0].children[0].style.transform === 'translate(-32px, 0px)', 'Movement independent of frame progression');
  doc.hidden = true; events.get('docvisibilitychange')(); assert(!requests.size, 'Hidden document stops RAF');
  doc.hidden = false; events.get('docvisibilitychange')(); assert(requests.size === 1, 'Visible resumes one RAF');
  observers[0].callback([{ isIntersecting: false }]); assert(!requests.size, 'Offscreen cancels RAF');
  cleanup(); cleanup(); assert(!requests.size && !events.size && !host.children.length && observers[0].disconnected, 'Destroy clears observers listeners DOM and animation');
  const fallback = mountBattle(host); assert(host.children[0].children[4].children[0].textContent === '战斗系统开发中', 'Honest development HUD'); fallback();
  const heading = node('h2'), stale = node('div'); heading.textContent = '秘境'; host.append(heading, stale);
  const preserved = mountBattle(host);
  assert(host.children.length === 2 && host.children[0] === heading && !stale.parent, 'Mount preserves heading and replaces stale contents');
  preserved(); assert(host.children.length === 1 && host.children[0] === heading, 'Cleanup preserves parent heading');
  const pose={frameCount:1,frames:[{url:'/game/runtime/static.png',x:0,y:0,sheetWidth:128,sheetHeight:128}],duration:100,loop:false};
  const still={width:128,height:128,anchor:{x:64,y:102},static:true,authoredFacing:'left',actions:{idle:{...pose,loop:true},attack:pose,hit:pose,death:pose}};
  const fx={width:128,height:128,anchor:{x:64,y:64},actions:{effect:{...pose,frameCount:2,frames:[pose.frames[0],pose.frames[0]],duration:50}}};
  const staticScene=mountBattle(host,{combat:true,assets:{sprites:{still,fx},ui:{player_fill:{asset:{url:'/game/runtime/hp.png'}},enemy_fill:{asset:{url:'/game/runtime/hp-enemy.png'}}},effects:{slash:{asset_id:'fx'},impact:{asset_id:'fx'}}},state:{player:{asset:'still'},enemies:[{asset:'still'}]}});
  const scene=host.children.find(n=>n.className==='battle-scene'),enemy=scene.children[2].children[0];
  staticScene.health({player:{name:'修士',hp:25,max_hp:100,attack:12,armor:3},enemy:{name:'妖兽',hp:0,max_hp:100,attack:8,armor:2}});
  const hp=scene.children[4].children[0].children;
  const statValue=(role,index)=>hp[role].children[1].children[index].children[1].textContent;
  assert(statValue(0,0)==='25 / 100'&&statValue(1,0)==='0 / 100','Actor stats show exact health without bars');
  assert(statValue(0,1)==='12'&&statValue(0,2)==='3'&&statValue(1,1)==='8'&&statValue(1,2)==='2','Both actors show actual attack and armor');
  staticScene.play('enemy','hit','step1');assert(enemy.attrs['data-static']==='true'&&enemy.attrs['data-action']==='hit'&&enemy.children[1].hidden,'Static enemy hit uses actual artwork');
  assert(enemy.children[0].style.transform.includes('-102px'),'Approved alpha foot anchor aligns to ground');
  assert(enemy.children[0].style.transform.endsWith('scale(1, 1)'),'Already-left-facing monster remains facing the protagonist');
  observers[observers.length-1].callback([{isIntersecting:true}]);
  staticScene.feedback({target:'enemy',actor:'player',damage:12});assert(scene.children[3].children.filter(n=>n.className==='battle-position').length===2,'Slash and impact use independent effect frames');
  const fxTick=time=>{const batch=[...requests];requests.clear();for(const [,f]of batch)f(time);};fxTick(0);fxTick(150);
  assert(!scene.children[3].children.some(n=>n.className==='battle-position'),'Finished effects release DOM and RAF actors');
  staticScene.health({player:{name:'修士',hp:73,max_hp:80,attack:14,armor:4},enemy:{name:'新妖兽',hp:10,max_hp:30}});
  assert(statValue(0,0)==='73 / 80'&&statValue(0,1)==='14'&&hp[1].children[0].textContent==='新妖兽','Stats refresh on committed facts');
  assert(statValue(1,1)==='—'&&statValue(1,2)==='—','Missing stats never fabricate numbers');
  staticScene.suspend();assert(!requests.size&&!scene.children[3].children.length,'Pause clears transient effects');staticScene();
  assert(!events.size&&!requests.size,'Static scene cleanup leaves no listeners or animation');
  const backgroundHost=node(),backgroundOne={url:'/game/runtime/background-one.png',width:320,height:180},backgroundTwo={url:'/game/runtime/background-two.png',width:320,height:180};
  const backgroundScene=mountBattle(backgroundHost,{assets:{background:backgroundOne},state:{}}),layer=backgroundHost.children[0].children[0],first=layer.children.find(n=>n.className==='battle-background');
  backgroundScene.update({}, {background:backgroundOne});assert(layer.children.includes(first),'Same dungeon keeps loaded background node');
  backgroundScene.update({}, {background:backgroundTwo});const second=layer.children.find(n=>n.className==='battle-background');assert(second!==first&&second.attrs.src===backgroundTwo.url&&!layer.children.includes(first),'Changing dungeon replaces background once');
  backgroundScene.update({}, {background:backgroundTwo});assert(layer.children.includes(second),'New dungeon background remains stable on refresh');
  backgroundScene.update({}, {});assert(!layer.children.some(n=>n.className==='battle-background'),'Missing background uses landscape fallback');backgroundScene();
  assert(!events.size&&!requests.size,'Background switch cleanup releases listeners');
  let extra=0;
  if(effectConfig){
    const effectHost=node(),sprites={still},effects={};
    for(let i=0;i<13;i++){sprites['fx'+i]={...fx,actions:{effect:{...fx.actions.effect,frames:fx.actions.effect.frames.map(f=>({...f,url:'/game/runtime/fx'+i+'.png'}))}}};effects['effect'+i]={asset_id:'fx'+i};}
    const reuse=mountBattle(effectHost,{combat:true,assets:{sprites,effects,fx_config:effectConfig},state:{player:{asset:'still'},enemies:[{asset:'still'}]}}),effectLayer=effectHost.children[0].children[3];
    observers[observers.length-1].callback([{isIntersecting:true}]);
    let clock=1000;
    for(let i=0;i<13;i++){
      reuse.effect('enemy','effect'+i);
      assert(effectLayer.children.some(n=>!n.hidden&&n.children?.[0]?.children?.[0]?.attrs.src==='/game/runtime/fx'+i+'.png'),'New effect remains playable after pool fills');extra++;
      for(let j=0;j<4;j++){clock+=100;fxTick(clock);}
      assert(effectLayer.children.length<=effectConfig.max_effects,'Pool remains bounded');extra++;
    }
    reuse.clearFeedback();reuse.feedback({kind:'damage',target:'enemy',actor:'player',damage:2,effect_key:'effect12'});
    assert(effectLayer.children.filter(n=>n.className==='battle-position'&&!n.hidden).length===1,'Elemental feedback uses custom effect without generic slash');extra++;
    reuse.suspend();const count=effectLayer.children.length;reuse.effect('enemy','effect0');assert(effectLayer.children.length===count&&!requests.size,'Suspended scene cannot spawn new effects');extra++;
    reuse();assert(!requests.size&&!events.size,'Expanded effect pool cleans up listeners and RAF');extra++;
  }
  return { tests: 33+extra, status: 'PASS' };
}

// sources = {metadata: metadata.js text, renderer: renderer.js text}.
// No Node main, filesystem access or automatic execution.
export function testBattleRenderer(sources) {
  return testGameBattle(sources.metadata, sources.renderer);
}

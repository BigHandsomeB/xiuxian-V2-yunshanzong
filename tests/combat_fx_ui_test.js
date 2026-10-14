// Native isolate harness, matching danding_ui_test.js; also usable as an ES module.
export function testCombatFX(metadataSource, battleSource, presentationSource, config) {
  let checks=0; const assert = (v, message) => { checks++; if (!v) throw Error(message); };
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
  const win = { ...eventTarget(), key: 'win', innerWidth: 400, innerHeight: 800, matchMedia: () => media,
    requestAnimationFrame(f) { requests.set(++serial, f); return serial; }, cancelAnimationFrame(id) { requests.delete(id); },
    IntersectionObserver: class { constructor(f) { this.callback = f; observers.push(this); } observe() {} disconnect() { this.disconnected = true; } } };
  const doc = { ...eventTarget(), key: 'doc', hidden: false, defaultView: win, createElement: () => node() };
  function node(tagName = 'div') { return { ...eventTarget(), key: String(++serial), tagName: tagName.toUpperCase(), ownerDocument: doc, style: {}, children: [], attrs: {}, dataset:{}, hidden: false,
    append(...nodes) { for (const n of nodes) { n.parent = this; this.children.push(n); } },
    replaceChildren(...nodes) { for (const n of this.children) n.parent = null; this.children = []; this.append(...nodes); },
    remove() { if (this.parent) this.parent.children = this.parent.children.filter(n => n !== this); },
    setAttribute(k, v) { this.attrs[k] = v; }, getAttribute(k) { return this.attrs[k]; }, removeAttribute(k) { delete this.attrs[k]; }, set src(v) { this.attrs.src = v; },
    getBoundingClientRect: () => ({ width: 400, height: 500, top: 0, left: 0, right: 400, bottom: 500 }) }; }
  const mountBattle = new Function('validateSprite', 'runtimeURL', 'frameAt', battleSource.replace(/^import[^\n]+\n/, '').replace(/export /g, '') + ';return mountBattle;')(validateSprite, runtimeURL, frameAt);
  const host=node(),still={...sprite,static:true,actions:{idle:sprite.actions.idle,attack:{...sprite.actions.idle,loop:false},hit:{...sprite.actions.idle,loop:false},death:{...sprite.actions.idle,loop:false}}};
  const fx={...still,actions:{effect:{...sprite.actions.idle,loop:false}}};
  const assets={fx_config:config,sprites:{hero:still,enemy:still,fx},background:{url:'/game/runtime/bg.png',width:100,height:100},effects:{slash:{asset_id:'fx'},impact:{asset_id:'fx'},critical_fx:{asset_id:'fx'},death_fx:{asset_id:'fx'}}};
  let state={player:{asset:'hero'},enemies:[{asset:'enemy',id:'a',tier:'boss',movement:'ground'}]};
  const render=mountBattle(host,{combat:true,assets,state}),root=host.children[0],hero=root.children[1].children[0],enemy=root.children[2].children[0],img=hero.children[0].children[0],background=root.children[0].children.find(n=>n.className==='battle-background');
  observers.at(-1).callback([{isIntersecting:true}]);let now=0;
  function tick(dt=50){now+=dt;const pending=[...requests];requests.clear();for(const [,fn]of pending)fn(now);}
  function wait(ms){for(let i=0;i<ms;i+=50)tick();}
  const heroSrc=img.attrs.src;wait(1400);assert(img.attrs.src===heroSrc,'effects uses fixed idle frame');
  render.play('player','attack','one');tick();tick(100);assert(hero.style.transform.includes('12px'),'hero stepped forward 12px');wait(250);assert(hero.style.transform.includes('translate(0px'),'hero returns');
  render.play('player','hit','two');tick();assert(img.style.filter.includes('invert'),'white hit flash');wait(200);assert(!img.style.filter,'flash ends');
  render.play('player','dodge','three');tick();assert(img.style.filter.includes('drop-shadow'),'dodge afterimage');assert(!hero.children[0].hidden&&img.attrs.src===heroSrc,'dodge keeps idle artwork without a dodge frame');wait(250);
  render.health({player:{name:'hero',hp:100,max_hp:100},enemy:{name:'boss',hp:49,max_hp:100}});tick();assert(enemy.children[0].children[0].style.filter.includes(config.colors.boss_phase),'boss below50 visual phase');
  for(const tier of ['normal','elite','boss'])for(const movement of ['ground','flying','heavy']){state={...state,enemies:[{asset:'enemy',id:tier+movement,tier,movement}]};render.update(state);render.play('enemy','attack',tier+movement);wait(300);assert(enemy.dataset.movement===movement,'movement profile '+tier+movement);}
  render.update({...state,enemies:[{...state.enemies[0],asset:'enemy',id:'new'}]});assert(root.children[0].children.includes(background),'same background retained');assert(root.children[1].children[0]===hero&&img.attrs.src===heroSrc,'hero node and src retained');
  for(let i=0;i<30;i++)render.feedback({actor:'player',target:'enemy',damage:5,critical:true});
  const active=root.children[3].children.filter(n=>!n.hidden);assert(active.length<=config.max_effects,'effect count cap');
  wait(900);const pooled=root.children[3].children.length;for(let i=0;i<30;i++){render.feedback({actor:'player',target:'enemy',damage:6});wait(650);}assert(root.children[3].children.length<=pooled,'reuse effect and number nodes');
  render.play('player','attack','reduce-mid-attack');tick();tick(100);render.feedback({actor:'enemy',target:'player',damage:7});media.matches=true;events.get('mediachange')();assert(root.children[3].children.every(n=>n.hidden),'reduce setting hides existing effects and numbers');assert(hero.style.transform==='translate(0px,0px) scale(1)','reduce setting immediately resets active pose');render.play('player','hit','reduced');tick();assert(img.style.filter.includes('invert'),'reduced motion retains white flash');assert(hero.style.transform==='translate(0px,0px) scale(1)','reduced no displacement');wait(200);assert(!requests.size,'reduced motion stops idle RAF');
  media.matches=false;events.get('mediachange')();doc.hidden=true;events.get('docvisibilitychange')();assert(!requests.size,'hidden paused');doc.hidden=false;events.get('docvisibilitychange')();assert(requests.size===1,'visible resumes');
  const present=new Function(presentationSource.replace(/^export /gm,'')+';return presentEvents;')();let scheduled=0;
  present(render,{animation_allowed:false,latest_events:[{kind:'player_attack',actor:'player'}]},assets,{schedule:()=>{scheduled++;},cancel:()=>{}});assert(!scheduled,'offline schedules no animation');render.update({...state,online:false,enemies:[{...state.enemies[0],id:'offline-next'}]});render.play('enemy','attack','offline');assert(!requests.size&&enemy.style.transform==='translate(0px,0px) scale(1)','offline update pauses idle and entry without remount');render.update({...state,online:true});
  render.play('player','attack','mode-mid-attack');tick();tick(100);config.hero_anim_mode='frames';render.update(state);assert(hero.style.transform==='translate(0px,0px) scale(1)','frames switch resets effects pose');wait(100);assert(root.dataset.heroAnimMode==='frames','frames mode');media.matches=true;events.get('mediachange')();render.play('player','hit','frames-reduced');tick();assert(img.style.filter.includes('invert'),'frames mode reduced motion retains white flash');wait(200);assert(!img.style.filter,'frames reduced flash ends');media.matches=false;events.get('mediachange')();config.hero_anim_mode='effects';render.update(state);wait(100);assert(img.attrs.src===heroSrc,'switch back to idle image');
  render.play('player','death','death');wait(250);assert(img.style.filter==='grayscale(1)'&&Number(hero.style.opacity)<1,'defeat grey sink fade');
  render();assert(!requests.size&&!events.size,'cleanup');return {checks,status:'PASS'};
}

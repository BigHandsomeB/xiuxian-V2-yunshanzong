// Native JS behavior check with a minimal DOM adapter, not real browser visual acceptance.
async function testAssetProfileUi(source, fixture) {
  const nodes=new Map(), named=new Map(), actionNodes=[];
  const attributes = text => Object.fromEntries([...text.matchAll(/([\w-]+)="([^"]*)"/g)].map(m=>[m[1],m[2]]));
  function parse(html) {
    for(const match of html.matchAll(/<(input|select|textarea|section|form|div|fieldset|button)\b([^>]*)>/g)) {
      const a=attributes(match[2]), n=node();n.value=a.value||'';n.name=a.name;n.type=a.type;n.disabled=/\bdisabled\b/.test(match[2]);n.checked=/\bchecked\b/.test(match[2]);
      if(a.id)nodes.set('#'+a.id,n);if(a.name)named.set(a.name,n);
      if(a['data-action']){n.dataset.action=a['data-action'];actionNodes.push(n);}
      if(a['data-count']){n.dataset.count=a['data-count'];nodes.set('[data-count="'+a['data-count']+'"]',n);}
      if(match[1]==='select')n.innerHTML=html.slice(match.index).match(/^<select[^>]*>([\s\S]*?)<\/select>/)?.[1]||'';
    }
  }
  function node(){return {value:'',checked:false,disabled:false,open:false,dataset:{},textContent:'',focus(){this.focused=true;},scrollIntoView(){this.scrolled=true;},_html:'',querySelector:find,querySelectorAll(selector){if(selector==='[data-action]:checked')return actionNodes.filter(n=>n.checked);if(selector==='input,select')return actionNodes;return [];},showModal(){this.open=true;},close(){this.open=false;},get innerHTML(){return this._html;},set innerHTML(html){this._html=html;if(html.includes('<option')){let opts=[...html.matchAll(/<option value="([^"]*)"([^>]*)>/g)];if(opts.length)this.value=(opts.find(m=>m[2].includes('selected'))||opts[0])[1];}parse(html);}};}
  function find(selector){if(selector==='meta[name="asset-base"]')return {content:'/tools/assets'};const m=selector.match(/\[name="([^"]+)"\]/);if(m)return named.get(m[1])||node();if(!nodes.has(selector))nodes.set(selector,node());return nodes.get(selector);}
  class Form {constructor(){this.entries=[...named].filter(([k,n])=>!n.disabled).map(([k,n])=>[k,n.value]);}get(k){return this.entries.find(([name])=>name===k)?.[1]??null;}*[Symbol.iterator](){yield* this.entries;}}
  const document={querySelector:find};
  let promptCalls=0;const submittedPrompts=[];const fetch=async(url,request)=>{if(url.split('?')[0].endsWith('/state'))return {ok:true,json:async()=>fixture};const body=JSON.parse(request.body);if(url.endsWith('/create-named')){fixture.assets.push({asset_id:'character.native_test',name_zh:body.name_zh,template_id:body.template_id,family:'default',state:null,set_id:null,versions:[]});return {ok:true,json:async()=>fixture.assets.at(-1)};}if(url.endsWith('/prompts')){promptCalls++;submittedPrompts.push(body);return {ok:true,json:async()=>({prompt_id:'saved-test',template_version:fixture.specs[body.template_id].template_version,frozen_spec:fixture.specs[body.template_id],text:'English prompt'})};}return {ok:true,json:async()=>fixture.specs[body.template_id]};};
  const prefix=source.slice(0,source.indexOf("$('#close').onclick"));
  const page=new Function('document','FormData','fetch',prefix+'\nstate=arguments[3]; promptPage.create=newAsset; promptPage.setDetail=setDetail; return promptPage;')(document,Form,fetch,fixture);
  for(const [template,logic,cell] of [['character_compact_v1','48×64','128×128'],['pill_icon_v1','48×48','96×96'],['building_interior_scene_v1','256×144','256×144'],['monster_static_v1','128×128','160×160'],['boss_static_v1','256×256','288×288'],['battle_ui_component_v1','96×96','128×128']]){
    named.clear();actionNodes.length=0;
    page(null,{template_id:template});
    for(let i=0;i<8;i++)await Promise.resolve();
    const html=find('#pixel-spec').innerHTML;
    if(template==='character_compact_v1'){const walk=actionNodes.find(n=>n.dataset.action==='walk');if(!walk||!walk.checked||find('[data-count="walk"]').value!=='4')throw Error('Walk default must be enabled and four frames');}
    if(template==='character_compact_v1'&&(find('#source-container').value!=='sheet'||!find('#sheet-content').textContent.includes('动作帧')))throw Error('Character must default to action-frame Sheet');
    if(template==='building_interior_scene_v1'&&(find('#source-container').value!=='sheet'||!find('#sheet-content').textContent.includes('完整场景状态')))throw Error('Interior must allow complete-scene Sheet');
    if(!html.includes(logic)||!html.includes(cell))throw Error('Missing automatic size for '+template+': '+find('#notice').textContent);
    if(find('#view').innerHTML.includes('name="runtime_size"'))throw Error('Independent runtime size input remains');
    if(template==='pill_icon_v1'&&find('#structure').innerHTML.includes('动作 / 状态与帧数'))throw Error('Static icon exposes animation frame controls');
    if(['monster_static_v1','boss_static_v1'].includes(template)){
      if(find('#structure').innerHTML||named.get('mode').value!=='static'||named.get('mode').innerHTML.includes('value="dynamic"'))throw Error('Static monster offers animation actions');
      if(find('#static-scope').value!=='set'||find('#source-container').value!=='sheet')throw Error('Monster does not default to an independent collection sheet');
      if(find('#prompt-template').innerHTML.includes('value="monster_compact_v1"')||find('#prompt-template').innerHTML.includes('value="boss_v1"'))throw Error('Legacy enemy action template offered for new art');
    }
    if(!find('#override-fields').disabled)throw Error('Advanced override enabled by default');
    if(template==='character_compact_v1'){
      const form=find('#prompt-form');form.onsubmit({preventDefault(){}});
      if(!find('#generate-prompt').disabled||!find('#prompt-status').textContent.includes('正在生成'))throw Error('No immediate generation feedback');
      form.onsubmit({preventDefault(){}});
      for(let i=0;i<30;i++)await Promise.resolve();
      if(promptCalls!==1)throw Error('Repeated click created duplicate prompt');
      if(!find('#prompt-result').scrolled||!find('#prompt-result').focused||!find('#prompt-result').innerHTML.includes('English prompt'))throw Error('Generated prompt not brought into view');
      if(find('#generate-prompt').disabled)throw Error('Generate button remained disabled');
    }
  }
  page.create(true);find('#create [name="template"]').value='resource_icon_v1';find('#create [name="template"]').onchange();
  const creation=find('#dialog-body').innerHTML,ordinary=creation.split('<details>')[0];
  if(ordinary.includes('name="machine_id"')||ordinary.includes('name="family"')||creation.includes('状态 / 动作 ID（逗号分隔）'))throw Error('Ordinary creation exposes machine fields');
  if(find('#create-states').innerHTML.includes('data-create-action'))throw Error('Static creation exposes action frame controls');
  if(!find('#create-list').innerHTML.includes('添加一个'))throw Error('Static Set cannot add members');
  find('#create [name="template"]').value='character_compact_v1';find('#create [name="template"]').onchange();
  if(find('#create [name="scope"]').value!=='single_asset'||find('#create [name="source_container"]').value!=='sheet')throw Error('Character creation incorrectly rejects/defaults away from Sheet');
  if(!find('#create-states').innerHTML.includes('data-create-action="walk"')||find('#create-sheet-content').textContent!=='素材表内容：动作帧')throw Error('Character frame/semantic controls missing');
  fixture.assets.push({asset_id:'character.worker.idle',name_zh:'工作弟子 · 待机',template_id:'character_compact_v1',family:'working_disciple',state:'idle',set_id:'character.worker.set',versions:[]});
  fixture.sets.push({set:{set_id:'character.worker.set',name_zh:'工作弟子',template_id:'character_compact_v1',family:'working_disciple',states:['idle'],asset_prefix:'character.worker',source_container:'image_set'}});
  named.clear();actionNodes.length=0;
  page(null,{template_id:'character_compact_v1',family:'working_disciple',asset_set_id:'character.worker.set',source_container:'image_set'});
  for(let i=0;i<8;i++)await Promise.resolve();
  if(!find('#generate-prompt').disabled)throw Error('Independent group must select a single target before generation');
  find('#choose-independent').onclick();
  for(let i=0;i<8;i++)await Promise.resolve();
  if(find('#source-container').value!=='image_set')throw Error('Character action fallback selected forbidden single_image container');
  const interiorGroup={set_id:'scene.current.set',name_zh:'当前丹鼎阁',template_id:'building_interior_scene_v1',family:'default',states:['prepare','measure','add_herbs','stable','high_fire','finish'],asset_prefix:'scene.current',source_container:'image_set'};
  fixture.sets.push({set:interiorGroup});
  for(const action of ['master',...interiorGroup.states])fixture.assets.push({asset_id:'scene.current.'+action,name_zh:action==='master'?'视觉基准':action,template_id:interiorGroup.template_id,family:'default',state:action,set_id:interiorGroup.set_id,versions:[],current_approved_version:null});
  named.clear();actionNodes.length=0;
  page(null,{template_id:interiorGroup.template_id,asset_set_id:interiorGroup.set_id});
  for(let i=0;i<10;i++)await Promise.resolve();
  if(!find('#independent-target').innerHTML.includes('scene.current.master'))throw Error('Fresh interior set omits Master from independent targets');
  if(find('#independent-target').value!=='scene.current.master')throw Error('Fresh interior must begin with its unconfirmed Master');
  find('#choose-independent').onclick();for(let i=0;i<10;i++)await Promise.resolve();
  if(find('#source-container').value!=='single_image'||!find('#source-container').disabled)throw Error('Master must generate one independent image');
  find('#prompt-form').onsubmit({preventDefault(){}});for(let i=0;i<35;i++)await Promise.resolve();
  let request=submittedPrompts.at(-1);if(request.asset_id!=='scene.current.master'||request.options.state!=='master'||request.options.master_reference)throw Error('Master generation incorrectly requires or binds an existing reference');
  fixture.assets.find(a=>a.asset_id==='scene.current.master').current_approved_version=1;
  named.clear();actionNodes.length=0;
  page(fixture.assets.find(a=>a.asset_id==='scene.current.high_fire'),{source_container:'single_image'});
  for(let i=0;i<10;i++)await Promise.resolve();
  if(find('#prompt-form [name="master_reference"]').value!=='scene.current.master')throw Error('State prompt must auto-select approved Master from same set');
  find('#prompt-form').onsubmit({preventDefault(){}});for(let i=0;i<35;i++)await Promise.resolve();
  request=submittedPrompts.at(-1);if(request.asset_id!=='scene.current.high_fire'||request.options.master_reference!=='scene.current.master')throw Error('State request lost its confirmed Master');
  page.create(true);find('#create [name="template"]').value='effect_compact_v1';find('#create [name="template"]').onchange();
  if(find('#create [name="scope"]').value!=='asset_set'||!find('#create-list').innerHTML.includes('添加一个'))throw Error('Named effect group has no editable names');
  if(!find('#create-states').innerHTML.includes('data-create-action="effect"')||!find('#create-states').innerHTML.includes('4 帧'))throw Error('Effect group lost animation frame controls');
  if(find('#create [name="source_container"]').value!=='sheet'||find('#create [name="source_container"]').innerHTML.includes('image_set'))throw Error('Batch effects must use mapped frame sheet');
  const fxGroup={set_id:'effect.native.set',name_zh:'战斗特效',template_id:'effect_compact_v1',family:'default',kind:'effect_collection',asset_ids:['effect.native.slash','effect.native.hit'],source_container:'sheet',generation_defaults:{counts:{effect:4}}};
  fixture.sets.push({set:fxGroup,total:2,complete:0,approved:0,runtime:0,slots:Object.fromEntries(fxGroup.asset_ids.map(aid=>[aid,{asset_id:aid,status:'missing_source'}]))});for(const [i,aid] of fxGroup.asset_ids.entries())fixture.assets.push({asset_id:aid,name_zh:['剑气斩击','命中闪光'][i],template_id:fxGroup.template_id,family:'default',state:'effect',set_id:fxGroup.set_id,versions:[],generation_defaults:{counts:{effect:4},source_container:'sheet'}});
  page.setDetail(fxGroup.set_id);if(!find('#view').innerHTML.includes('2 个独立特效 · 每个4帧')||find('#view').innerHTML.includes('视觉基准 missing_source'))throw Error('Effect group detail assumes a Master');
  named.clear();actionNodes.length=0;page(null,{template_id:fxGroup.template_id,asset_set_id:fxGroup.set_id});for(let i=0;i<10;i++)await Promise.resolve();
  if(!find('#static-generation').innerHTML.includes('剑气斩击')||!find('#static-generation').innerHTML.includes('命中闪光'))throw Error('Bound FX names not shown');
  if(find('[data-count="effect"]').value!=='4')throw Error('Bound FX creation frame count not preserved');
  if(find('#source-container').innerHTML.includes('image_set'))throw Error('Bound FX group exposes unsupported image_set');
  named.clear();actionNodes.length=0;page(fixture.assets.find(a=>a.asset_id==='effect.native.slash'));for(let i=0;i<10;i++)await Promise.resolve();
  if(find('[data-count="effect"]').value!=='4'||find('#source-container').value!=='sheet')throw Error('Single member prompt lost its own frames');
  fixture.collections=[{collection_id:'collection.native',name_zh:'通用集合'}];
  page.create(true,'collection.native');
  if(find('#create [name="collection_id"]').value!=='collection.native')throw Error('Creation lost collection parent');
  find('#create [name="template"]').value='dungeon_icon_v1';find('#create [name="template"]').onchange();
  if(find('#create [name="scope"]').value!=='asset_set'||find('#create [name="source_container"]').value!=='sheet')throw Error('Dungeon icons must default to batch sheet');
  const dungeon=fixture.templates.find(t=>t.template_id==='dungeon_icon_v1');
  if(!dungeon.transparent||dungeon.pixel_size_profile.runtime_profile.frame_size.join('x')!=='128x128')throw Error('Dungeon profile not transparent native 128');
  return 'PASS: existing profile/actions/Master behavior and named animated FX creation/group/member controls';
}

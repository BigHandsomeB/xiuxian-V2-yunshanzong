// Run against shipped list component in the existing native DOM adapter.
function testAssetAppearanceDirections(source, harnessSource){
 const names=['斩妖飞剑','镇岳鼎','噬魂幡','寒魄印','赤焰葫'];
 const looks=['青白剑刃、獠牙护手','赤铜三足鼎，双耳；厚重','墨青幡面与幽青魂纹','寒玉方印与螭龙钮','赤红葫芦、铜箍与系绳'];
 const harness=new Function(harnessSource+';return {listTestDom};')();
 const begin=source.indexOf('function analyseAssetNames('),end=source.indexOf('function sourcePolicy(',begin);
 const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const {assetNameList,parseAppearanceDirections}=new Function('esc',source.slice(begin,end)+';return {assetNameList,parseAppearanceDirections};')(esc);
 let checks=0;const check=(v,m)=>{if(!v)throw Error(m);checks++;};
 let report=parseAppearanceDirections(looks.join('\n'),names);
 check(!report.errors.length&&report.directions.length===5,'five ordered directions');
 check(report.directions[1].appearance_direction===looks[1],'punctuation within descriptions never splits a direction');
 for(const text of [looks.slice(1).join('\n'),looks.concat('多余').join('\n'),[looks[0],'',...looks.slice(2)].join('\n')])check(parseAppearanceDirections(text,names).errors.length,'quantity mismatch or empty direction rejected');
 report=parseAppearanceDirections('赤焰葫：火红葫芦\n斩妖飞剑\t白玉飞剑',names,'named');
 check(!report.errors.length&&report.directions[0].name_zh==='赤焰葫','named input may have independent order');
 for(const text of ['不存在：方向','斩妖飞剑：甲\n斩妖飞剑：乙','斩妖飞剑：'])check(parseAppearanceDirections(text,names,'named').errors.length,'unknown duplicate or missing direction rejected');
 check(parseAppearanceDirections('方向',['剑','剑']).errors.length,'ambiguous existing names rejected');
 check(parseAppearanceDirections('方向',[]).errors.length,'names must be imported first');
 for(const width of [320,390,430])for(const theme of ['light','dark']){
  const container=harness.listTestDom(),initial=names.map((name_zh,i)=>({name_zh,asset_id:'artifact.'+i,appearance_direction:'旧方向'+i}));
  let changes=0;const read=assetNameList(container,initial,()=>changes++,{appearance:true});
  check(container.querySelectorAll('[data-appearance-index]').length===5,width+'/'+theme+' each artifact has a direction input');
  const input=container.querySelector('[data-appearance-text]');input.value=looks.join('\n');input.oninput();container.querySelector('[data-appearance-parse]').onclick();
  check(read.entries()[0].appearance_direction==='旧方向0','preview does not apply changes');
  check(!!container.querySelector('[data-appearance-apply]'),'valid mapping requires explicit confirmation');
  container.querySelector('[data-appearance-apply]').onclick();
  check(read.entries().every((r,i)=>r.appearance_direction===looks[i]&&r.asset_id==='artifact.'+i),'directions bind to identities');
  container.querySelector('[data-up="4"]').onclick();check(read.entries()[3].appearance_direction===looks[4]&&read.entries()[3].asset_id==='artifact.4','reorder keeps appearance with asset');
  let field=container.querySelector('[data-appearance-text]');field.value='只有一条';field.oninput();container.querySelector('[data-appearance-parse]').onclick();check(!container.querySelector('[data-appearance-apply]'),'mismatch cannot apply');
  const mode=container.querySelector('[data-appearance-mode]');mode.value='named';mode.onchange();field.value='镇岳鼎：青铜古鼎、三足';field.oninput();container.querySelector('[data-appearance-parse]').onclick();container.querySelector('[data-appearance-apply]').onclick();
  check(read.entries().find(r=>r.name_zh==='镇岳鼎').appearance_direction==='青铜古鼎、三足','named partial update finds matching name after reorder');
  check(read.entries().find(r=>r.name_zh==='赤焰葫').appearance_direction===looks[4],'partial update keeps other artifact directions');
  field=container.querySelector('[data-appearance-text]');field.value='镇岳鼎：<script>bad</script>';field.oninput();container.querySelector('[data-appearance-parse]').onclick();check(!container.querySelector('[data-appearance-preview]').innerHTML.includes('<script>'),'preview escapes pasted markup');
  container.querySelector('[data-name-index="0"]').value='改名';container.querySelector('[data-name-index="0"]').oninput();check(!container.querySelector('[data-appearance-apply]'),'name changes invalidate pending direction preview');
 }
 const container=harness.listTestDom(),read=assetNameList(container,[''],()=>{},{appearance:true});
 const bulk=container.querySelector('[data-bulk-text]');bulk.value=names.join('\n');bulk.oninput();container.querySelector('[data-bulk-parse]').onclick();container.querySelector('[data-bulk-confirm]').onclick();
 check(read().join('|')===names.join('|'),'batch names can be imported before directions');
 const input=container.querySelector('[data-appearance-text]');input.value=looks.join('\n');input.oninput();container.querySelector('[data-appearance-parse]').onclick();container.querySelector('[data-appearance-apply]').onclick();
 check(read.entries().every((r,i)=>r.appearance_direction===looks[i]),'second independent batch fills directions');
 check(source.includes("artifact_static_v1:'法宝 · 透明128×128'"),'template has Chinese 128 label');
 return {checks,note:'Native DOM behavior only; no phone painting claim.'};
}

// Native JS behavior check with a minimal DOM adapter, not real browser visual acceptance.
async function testArtifactManagerForms(source, fixture) {
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
  let checks=0;const check=(v,m)=>{if(!v)throw Error(m);checks++;};
  page.create(true);find('#create [name="template"]').value='artifact_static_v1';find('#create [name="template"]').onchange();
  check(find('#create [name="scope"]').value==='asset_set','artifact template defaults to batch group');
  check(find('#create-list').innerHTML.includes('外观方向'),'batch member row includes direction');
  check(find('#create-list').innerHTML.includes('批量导入外观方向'),'batch directions is a separate second import');
  find('#create [name="scope"]').value='single_asset';find('#create [name="scope"]').onchange();
  check(find('#create-appearance').innerHTML.includes('外观方向'),'single artifact gets appearance textarea');
  const artifact={asset_id:'artifact.static.native',name_zh:'斩妖飞剑',template_id:'artifact_static_v1',family:'default',state:'icon',set_id:null,versions:[],appearance_direction:'青白剑刃、獠牙护手'};
  fixture.assets.push(artifact);named.clear();actionNodes.length=0;page(artifact);
  for(let i=0;i<10;i++)await Promise.resolve();
  check(find('#artifact-appearance-row').innerHTML.includes(artifact.appearance_direction),'saved appearance prefills prompt form');
  check(find('#pixel-spec').innerHTML.includes('128×128'),'artifact prompt exposes native 128 profile');
  find('#prompt-form [name="appearance_direction"]').value='本次青玉剑身';
  await find('#prompt-form').onsubmit({preventDefault(){}});
  for(let i=0;i<10;i++)await Promise.resolve();
  check(submittedPrompts.at(-1).options.appearance_direction==='本次青玉剑身','per-prompt override is sent');
  const group={set_id:'artifact.native.group',name_zh:'法宝组',template_id:'artifact_static_v1',family:'default',kind:'static_collection',asset_ids:[artifact.asset_id],source_container:'sheet',generation_defaults:{counts:{icon:1}}};
  artifact.set_id=group.set_id;fixture.sets.push({set:group,total:1,complete:0,approved:0,runtime:0,slots:{[artifact.asset_id]:{asset_id:artifact.asset_id,status:'missing_source'}}});
  named.clear();actionNodes.length=0;page(null,{template_id:group.template_id,asset_set_id:group.set_id});
  for(let i=0;i<10;i++)await Promise.resolve();
  check(find('#artifact-appearance-row').innerHTML.includes(artifact.appearance_direction),'group prompt shows member-specific directions');
  named.clear();actionNodes.length=0;page(null,{template_id:'equipment_icon_v1'});
  for(let i=0;i<10;i++)await Promise.resolve();
  check(!find('#artifact-appearance-row').innerHTML,'ordinary equipment has no artifact-only field');
  return {checks};
}

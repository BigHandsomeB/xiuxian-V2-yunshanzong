// Existing real UI functions, tiny DOM parser; mobile painting is a separate check.
function testAssetCollectionsUi(source,domFactory){
 const root=domFactory(),fixed=new Map();
 for(const id of ['view','heading','editor','dialog-body','notice'])fixed.set('#'+id,domFactory());
 fixed.get('#editor').showModal=function(){this.open=true;};
 const find=s=>s==='meta[name="asset-base"]'?{content:'/tools/assets'}:fixed.get(s)||fixed.get('#view').querySelector(s)||fixed.get('#dialog-body').querySelector(s);
 const fixture={csrf:'test-only-csrf',collections:[{collection_id:'all.one',name_zh:'通用集合'}],assets:[],sets:[{set:{set_id:'a.one',name_zh:'集合内怪物',template_id:'monster_static_v1',collection_id:'all.one'},total:2,approved:1,runtime:1,slots:{}},{set:{set_id:'a.two',name_zh:'未归类装备',template_id:'equipment_icon_v1'},total:1,approved:0,runtime:0,slots:{}}]};
 const prefix=source.slice(0,source.indexOf("$('#close').onclick"));const ui=new Function('document','fixture',prefix+'\nstate=fixture;return {groups,collectionDetail,collectionOptions};')({querySelector:find},fixture);
 const assert=(v,m)=>{if(!v)throw Error(m);};
 ui.groups();assert(find('#collection-results').innerHTML.includes('通用集合'),'Root lists arbitrary collection');assert(!find('#set-results').innerHTML.includes('集合内怪物')&&find('#set-results').innerHTML.includes('未归类装备'),'Root separates assigned/unassigned groups');
 find('#group-search').value='怪物';find('#group-search').oninput();assert(find('#set-results').innerHTML.includes('集合内怪物'),'Global search reaches nested group');
 ui.collectionDetail('all.one');assert(find('#collection-groups').innerHTML.includes('集合内怪物')&&!find('#collection-groups').innerHTML.includes('未归类装备'),'Collection children only');
 assert(typeof find('#collection-new-set').onclick==='function'&&typeof find('#collection-add').onclick==='function','Create and existing organization wired');assert(ui.collectionOptions('all.one').includes('selected'),'New creation selects parent collection');
 return {tests:6,status:'PASS',kind:'native JS organization checks, not device layout'};
}

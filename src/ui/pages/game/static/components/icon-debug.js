// Read-only diagnostics: enable explicitly with ?debug=icons; no gameplay authority.
export function startIconDebug(win,root){
 const search=win.location?.search||'';if(!search)return;
 if(!new URLSearchParams(search).getAll('debug').includes('icons'))return;
 if(win.PerformanceObserver)try{new win.PerformanceObserver(list=>{for(const entry of list.getEntries())if(entry.initiatorType==='img')win.console?.debug('icon request',entry.name,entry.transferSize);}).observe({type:'resource'});}catch{}
 if(win.MutationObserver)new win.MutationObserver(records=>{for(const record of records)for(const node of record.removedNodes)if(node.nodeType===1&&(node.tagName==='IMG'||node.querySelector?.('img')))win.console?.debug('icon removed',node.dataset?.assetId||node.className);}).observe(root,{childList:true,subtree:true});
}

// Actual lightweight storage-page behavior; not real-phone visual acceptance.
async function testAssetStorageUi(source){
 const block=source.slice(source.indexOf('function formatStorageBytes('),source.indexOf('async function route()'));
 const nodes={'heading':{},'view':{},'storage-panel':{isConnected:true},'storage-refresh':{disabled:false},'storage-result':{textContent:'',innerHTML:''}};
 let calls=0,resolve;const api=async path=>{if(path!=='storage')throw Error('Unexpected mutation');calls++;return new Promise(r=>resolve=r);};
 const {storagePage,formatStorageBytes}=new Function('$','api','close','esc',block+';return {storagePage,formatStorageBytes};')(id=>nodes[id.slice(1)],api,()=>{},x=>String(x));
 storagePage();if(calls!==1||!nodes['storage-refresh'].disabled||!nodes['storage-result'].textContent.includes('正在统计'))throw Error('No visible pending status');nodes['storage-refresh'].onclick();if(calls!==1)throw Error('Duplicate refresh requests');
 const data={allocated_supported:true,allocated_bytes:1048576,file_count:6,size_bytes:5000,categories:[{name_zh:'原图',allocated_bytes:1048576,file_count:6}],volume:{total_bytes:1073741824,free_bytes:536870912},scanned_at:'2026-10-06T00:00:00Z',partial:false,skipped_links_or_special:0,duplicate_links:0};
 resolve(data);await Promise.resolve();await Promise.resolve();await Promise.resolve();
 const html=nodes['storage-result'].innerHTML;if(!html.includes('1.00 MB')||!html.includes('6 个文件')||!html.includes('所在磁盘可用')||html.includes('清理'))throw Error('Disk/read-only summary missing');if(nodes['storage-refresh'].disabled)throw Error('Refresh remains disabled');if(formatStorageBytes(0)!=='0 B'||formatStorageBytes(1024)!=='1.00 KB')throw Error('Units invalid');
 const again=nodes['storage-refresh'].onclick();nodes['storage-panel'].isConnected=false;const old=nodes['storage-result'].innerHTML;resolve({...data,partial:true});await again;if(nodes['storage-result'].innerHTML!==old)throw Error('Late scan overwrites another page');
 return 'PASS: disk totals/units and available space, visible loading, explicit read-only refresh, duplicate/stale-request guards';
}

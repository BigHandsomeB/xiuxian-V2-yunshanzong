// Fresh comparison trees do not start image loads until adopted into the live tree.
let deferred=0;
export function deferIconLoads(build){deferred++;try{return build();}finally{deferred--;}}
export function setIconSource(image,url){
 if(deferred){image.dataset.pendingIconSrc=url;return;}
 image.__requestedIconURL=url;
 const resolve=image.ownerDocument?.defaultView?.desktopIconURL;
 if(!resolve){image.src=url;return;}
 const apply=source=>{if(image.__requestedIconURL===url){image.loading='eager';image.src=source;}};
 const source=resolve(url);
 if(typeof source==='string')apply(source);else source.then(apply,()=>apply(url));
}
export function activateIconLoads(root){
 for(const image of root.querySelectorAll('img[data-pending-icon-src]')){const url=image.dataset.pendingIconSrc;delete image.dataset.pendingIconSrc;setIconSource(image,url);}
}

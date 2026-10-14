// Fresh comparison trees do not start image loads until adopted into the live tree.
let deferred=0;
export function deferIconLoads(build){deferred++;try{return build();}finally{deferred--;}}
export function setIconSource(image,url){if(deferred)image.dataset.pendingIconSrc=url;else image.src=url;}
export function activateIconLoads(root){
 for(const image of root.querySelectorAll('img[data-pending-icon-src]')){const url=image.dataset.pendingIconSrc;delete image.dataset.pendingIconSrc;image.src=url;}
}

import {deferIconLoads,activateIconLoads} from './icon-loading.js';
import {patchPanel} from './patch.js';
// Controllers with animation keep their own update; other screens retain their DOM.
export function retainScreen(node,ctx,render,decorate=()=>{}){
 const cleanup=()=>{};
 cleanup.update=(data,busy)=>{ctx.data=data;ctx.busy=busy;const fresh=deferIconLoads(()=>{const panel=render(ctx);decorate(panel);return panel;});patchPanel(node,fresh);activateIconLoads(node);};
 return cleanup;
}

import {animateWorldTime} from './world-time.js';
import {deferIconLoads,activateIconLoads} from './icon-loading.js';
import {patchPanel} from './patch.js';
// Controllers with animation keep their own update; other screens retain their DOM.
export function retainScreen(node,ctx,render,decorate=()=>{}){
 const clock=animateWorldTime(node);clock.refresh();
 const cleanup=()=>clock.dispose();cleanup.dispose=()=>clock.dispose();cleanup.suspend=()=>clock.suspend();cleanup.resume=()=>clock.resume();
 cleanup.update=(data,busy)=>{ctx.data=data;ctx.busy=busy;const fresh=deferIconLoads(()=>{const panel=render(ctx);decorate(panel);return panel;});patchPanel(node,fresh);activateIconLoads(node);clock.refresh();};
 return cleanup;
}

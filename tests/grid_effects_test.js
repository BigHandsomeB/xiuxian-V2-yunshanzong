function testGridEffects(source){
 const make=new Function(source.replace(/export\s+/g,'')+';return observeGridEffects;')();
 const fx=make();for(const name of ['refresh','suspend','resume','dispose'])fx[name]();
 if(/IntersectionObserver|addEventListener|requestAnimationFrame|setTimeout|setInterval/.test(source))throw Error('disabled effects must not allocate background work');
 return {checks:2,scope:'disabled compatibility module has no effects or background work'};
}

// Current-screen resources only. Background throttling never changes world state.
export function screenLifecycle(){let current=null,suspended=false;return {
 mount(controller){current?.dispose?.();if(typeof current==='function')current();current=controller;if(suspended)current?.suspend?.();},
 detach(){const saved=current;saved?.suspend?.();current=null;return saved;},
 refresh(...args){current?.update?.(...args);},
 suspend(){suspended=true;current?.suspend?.();},
 resume(){suspended=false;current?.resume?.();},
 dispose(){current?.dispose?.();if(typeof current==='function')current();current=null;},
 get suspended(){return suspended;}
};}
export function needsSimulationPoll(route,view){if(view.world?.paused)return false;if(view.time?.pending)return true;if(route?.name==='building'&&route.id==='market'&&view.sect_services?.market)return true;if(view.combat?.auto?.enabled)return true;if(view.economy&&['sect','building','inventory','settings','adventure'].includes(route?.name)&&view.economy.needs_poll)return true;return route?.name==='building'&&route.id==='alchemy'&&(view.alchemy.current.status==='WORKING'||view.time.pending);}

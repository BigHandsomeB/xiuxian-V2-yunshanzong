// UI preference only: never sends a Command or writes the Gameplay Save.
export const themeModes=['SYSTEM','LIGHT','DARK'];
export function themePreference(win=window){
 const key='xianxia-ui-theme';let mode='SYSTEM',media=null;
 try{const stored=win.localStorage?.getItem(key);if(themeModes.includes(stored))mode=stored;}catch{}
 try{media=win.matchMedia?.('(prefers-color-scheme: dark)');}catch{}
 let stopped=false;
 function apply(){if(stopped)return;const dark=mode==='DARK'||mode==='SYSTEM'&&!!media?.matches,root=win.document?.documentElement;root?.setAttribute('data-theme',dark?'dark':'light');root?.setAttribute('data-theme-mode',mode);const meta=win.document?.querySelector?.('meta[name="theme-color"]');if(meta)meta.setAttribute('content',dark?'#101f29':'#172d32');}
 function set(value){if(!themeModes.includes(value))return;mode=value;try{win.localStorage?.setItem(key,mode);}catch{}apply();}
 const changed=()=>{if(mode==='SYSTEM')apply();},visible=()=>{if(!win.document?.hidden)apply();};
 if(media?.addEventListener)media.addEventListener('change',changed);else media?.addListener?.(changed);
 win.document?.addEventListener('visibilitychange',visible);win.addEventListener?.('pageshow',apply);
 apply();return {get mode(){return mode;},set,refresh:apply,dispose(){stopped=true;if(media?.removeEventListener)media.removeEventListener('change',changed);else media?.removeListener?.(changed);win.document?.removeEventListener('visibilitychange',visible);win.removeEventListener?.('pageshow',apply);}};
}

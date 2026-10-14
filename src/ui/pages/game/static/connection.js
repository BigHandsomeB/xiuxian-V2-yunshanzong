// Connection health is independent of a normal query/command being in flight.
export function connectionState(){let state='INITIAL_LOADING',failures=0;return {
 get state(){return state;},get failures(){return failures;},
 begin(hasSnapshot){if(!hasSnapshot&&state!=='AUTH_REQUIRED'&&state!=='OFFLINE')state='INITIAL_LOADING';return state;},
 connected(){failures=0;state='CONNECTED';return state;},
 offline(){state='OFFLINE';return state;},
 failed(error,online=true){if(error.cancelled||error.name==='AbortError')return state;if(error.login){state='AUTH_REQUIRED';return state;}if(!online){state='OFFLINE';return state;}if(!error.transport)return state;failures++;state=failures===1?'DEGRADED':'RECONNECTING';return state;},
 retryDelay(){return failures>0&&failures<=3?[1000,3000,8000][failures-1]:null;},
 message(){return {INITIAL_LOADING:'连接世界中…',CONNECTED:'',DEGRADED:'',RECONNECTING:'正在重新连接世界…',AUTH_REQUIRED:'登录状态已失效，请重新登录。',OFFLINE:'当前离线，已读取的世界仍可查看。'}[state];}
};}

const routes=new Set(['sect','building','disciples','disciple_detail','cultivation','inventory','adventure','battle','settings']);
export function parseRoute(hash=''){const [name,raw='']=(hash.replace(/^#\/?/,'')||'sect').split('/');let id='';try{id=decodeURIComponent(raw);}catch{}return {name:routes.has(name)?name:'sect',id};}
export function mainTab(route){return {building:'sect',disciple_detail:'disciples',battle:'adventure',settings:null}[route.name]??(route.name==='settings'?null:route.name);}
export function routeKey(route){return route.name+'/'+route.id;}
export function navigate(name,id=''){location.hash=name+(id?'/'+encodeURIComponent(id):'');}

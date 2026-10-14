// The review client has no mutation transport, storage, pending replay or settlement.
export class ReviewClient {
 constructor({fetcher,search=''}){this.fetcher=fetcher;this.current=null;const value=/[?&]case=([^&]*)/.exec(search)?.[1];this.case=['normal','elite','boss','production'].includes(value)?value:'normal';}
 async api(path){if(!['view','assets'].includes(path))return this.blocked();const response=await this.fetcher('/game/review/api/'+path+(path==='view'?'?case='+this.case:''),{method:'GET',cache:'no-store'});if(!response.ok)throw new Error('预览暂不可用，请稍后重新打开。');return response.json();}
 async read(){this.current=await this.api('view');return this.current;}
 async sync(){return this.read();}
 async poll(){return this.read();}
 cancelRead(){}
 pending(){return null;}
 async blocked(){const error=new Error('只读 UI 预览：此按钮保留正式外观，不执行游戏操作。');error.status=422;error.code='REVIEW_READONLY';throw error;}
 async action(){return this.blocked();}
 async combat(){return this.blocked();}
 async cultivation(){return this.blocked();}
 async economy(){return this.blocked();}
 async world(){return this.blocked();}
}

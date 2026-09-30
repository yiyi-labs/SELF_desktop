import { http } from '@kit.NetworkKit';

export interface StoryTurn {userText:string;reply:string;productIds?:string[];}
export interface StoryRequest {
  schemaVersion:number;requestId:string;sessionId:string;assetId:string;userText:string;
  responseLanguage:string;turns:StoryTurn[];dismissedProducts:boolean;
  productContextIds?:string[];
}
export interface StoryResponse {
  schemaVersion:number;requestId:string;assetId:string;kind:string;message:string;
  evidenceRefs:string[];canOfferDigitalPreview:boolean;model:string;
}

/** This client has no image fields and no access to the GS asset bytes. */
export class StoryConversationClient {
  endpoint:string='http://127.0.0.1:8787';token:string='';
  private active:http.HttpRequest|undefined=undefined;
  private generation:number=0;
  cancel():void{this.generation++;if(this.active){this.active.destroy();this.active=undefined;}}
  async ask(input:StoryRequest):Promise<StoryResponse>{
    this.cancel();const generation=this.generation;
    if(!this.endpoint.startsWith('https://')&&this.endpoint!=='http://127.0.0.1:8787')
      throw new Error('文字服务需要 HTTPS；本机调试仅限回环端口');
    const request=http.createHttp();this.active=request;
    try{
      const response=await request.request(this.endpoint+'/v1/conversations',{
        method:http.RequestMethod.POST,
        header:{'Content-Type':'application/json','Authorization':this.token?'Bearer '+this.token:''},
        extraData:JSON.stringify(input),expectDataType:http.HttpDataType.STRING,
        connectTimeout:10000,readTimeout:45000,usingCache:false
      });
      if(generation!==this.generation)throw new Error('本次对话已取消');
      if(response.responseCode!==200)throw new Error('暂时没能接上这段对话（'+response.responseCode+'）');
      const result=JSON.parse(response.result as string) as StoryResponse;
      if(result.schemaVersion!==1||result.requestId!==input.requestId||result.assetId!==input.assetId||
        !['conversation','product','edit_entry','real_effect_boundary','closing'].includes(result.kind)||
        !result.message||result.message.length>400||!Array.isArray(result.evidenceRefs)||result.evidenceRefs.length>2)
        throw new Error('收到的对话与这颗星辰不匹配');
      return result;
    }finally{request.destroy();if(this.active===request)this.active=undefined;}
  }
}

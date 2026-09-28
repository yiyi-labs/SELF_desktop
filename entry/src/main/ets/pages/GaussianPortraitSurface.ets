import { fileIo as fs } from '@kit.CoreFileKit';
import { webview } from '@kit.ArkWeb';
import { RendererBridge, Envelope, MessagePayload, GsViewSnapshot } from '../bridge/RendererBridge';

export interface GsSelection {regionId:string;count:number;total:number;x:number;y:number;}
export interface GsCapture {width:number;height:number;images:number;view?:GsViewSnapshot;}

/** App-private 3DGS bytes served only to the bundled, offline viewer. */
@Component
export struct GaussianPortraitSurface {
  @Prop gaussianPath:string='';
  @Prop viewPath:string='';
  @Prop previewMode:boolean=false;
  @Prop @Watch('commandChanged') editCommand:string='';
  onReady:()=>void=()=>{};
  onFailure:(message:string)=>void=()=>{};
  onEditFailure:(message:string)=>void=()=>{};
  onInteraction:()=>void=()=>{};
  onSelection:(selection:GsSelection,mask:ArrayBuffer)=>void=()=>{};
  onCapture:(clean:ArrayBuffer,annotated:ArrayBuffer,width:number,height:number,view?:GsViewSnapshot)=>void=()=>{};
  onViewSnapshot:(view:GsViewSnapshot)=>void=()=>{};
  onApplied:(action:string)=>void=()=>{};
  onBackgroundTone:(light:boolean)=>void=()=>{};
  private controller:webview.WebviewController=new webview.WebviewController();
  private bridge:RendererBridge=new RendererBridge();
  private selection:GsSelection|undefined=undefined;
  private capture:GsCapture|undefined=undefined;
  private clean:ArrayBuffer|undefined=undefined;
  private lastCommand:string='';
  aboutToDisappear():void{this.bridge.dispose();this.clean=undefined;this.selection=undefined;this.capture=undefined;}

  private commandChanged():void {
    if(!this.bridge.ready||!this.editCommand||this.editCommand===this.lastCommand)return;
    try{this.bridge.send('GS_COMMAND',JSON.parse(this.editCommand) as MessagePayload);this.lastCommand=this.editCommand;}
    catch(error){this.onFailure('这次操作暂时无法继续：'+String(error));}
  }
  private connected():void {
    const match=/\/models\/([a-f0-9]{32})\//.exec(this.gaussianPath.replace(/\\/g,'/'));
    if(!match){this.onFailure('个人模型路径不正确');return;}
    this.bridge.assetId=match[1];this.bridge.assetVersion=match[1];
    this.lastCommand='';
    this.bridge.onMessage=(message:Envelope)=>{
      if(message.type==='READY'){this.onReady();this.commandChanged();}
      if(message.type==='GS_FAILED')this.onEditFailure(message.payload.message||'圈选暂时不可用');
      if(message.type==='GS_SELECTION'&&message.payload.count!==undefined&&message.payload.total!==undefined&&
        message.payload.x!==undefined&&message.payload.y!==undefined)
        this.selection={regionId:message.payload.regionId||'gs-selected',count:message.payload.count,total:message.payload.total,x:message.payload.x,y:message.payload.y};
      if(message.type==='GS_CAPTURE'&&message.payload.width!==undefined&&message.payload.height!==undefined&&message.payload.images!==undefined)
        this.capture={width:message.payload.width,height:message.payload.height,images:message.payload.images,view:message.payload.gsView};
      if(message.type==='GS_VIEW'&&message.payload.gsView)this.onViewSnapshot(message.payload.gsView);
      if(message.type==='GS_APPLIED')this.onApplied(message.payload.action||'');
      if(message.type==='GS_TONE'&&message.payload.light!==undefined)this.onBackgroundTone(message.payload.light);
    };
    this.bridge.onBytes=(kind:string,bytes:ArrayBuffer)=>{
      if(kind==='gs-mask'&&this.selection){
        const selection=this.selection;this.selection=undefined;
        if(bytes.byteLength!==selection.total)return;
        this.onSelection(selection,bytes);
      }
      if(kind==='gs-clean')this.clean=bytes;
      if(kind==='gs-annotated'&&this.clean&&this.capture){
        this.onCapture(this.clean,bytes,this.capture.width,this.capture.height,this.capture.view);
        this.clean=undefined;this.capture=undefined;
      }
    };
    this.bridge.attach(this.controller);
  }

  private intercept(event:OnInterceptRequestEvent):WebResourceResponse|null {
    const url=event.request.getRequestUrl();
    if(url!=='https://self.local/portrait.gaussian.ply'&&url!=='https://self.local/portrait.view.json')return null;
    try {
      const isView=url.endsWith('.json');
      const path=isView?this.viewPath:this.gaussianPath;
      const file=fs.openSync(path,fs.OpenMode.READ_ONLY);
      let bytes:ArrayBuffer;
      try {
        const size=fs.statSync(file.fd).size;
        if(size<(isView?128:4096)||size>(isView?4096:256*1024*1024))throw new Error('个人立体资产大小异常');
        bytes=new ArrayBuffer(size);
        if(fs.readSync(file.fd,bytes,{length:size})!==size)throw new Error('个人立体资产读取不完整');
      } finally {fs.closeSync(file);}
      const response=new WebResourceResponse();
      response.setResponseData(bytes);
      response.setResponseMimeType(isView?'application/json':'application/octet-stream');
      response.setResponseCode(200);
      response.setReasonMessage('OK');
      response.setResponseHeader([{headerKey:'Access-Control-Allow-Origin',headerValue:'*'}]);
      console.info('SELF_PERSONAL_ASSET_SERVED '+(isView?'view ':'ply ')+bytes.byteLength);
      return response;
    } catch(error) {
      console.error('SELF_PERSONAL_ASSET_FAILED '+String(error));
      this.onFailure('个人立体面容暂时无法打开。');
      return null;
    }
  }

  build(){
    Web({src:this.previewMode?$rawfile('gs-preview.html'):$rawfile('gs-viewer.html'),controller:this.controller})
      .width('100%').height('100%')
      .onInterceptRequest((event:OnInterceptRequestEvent)=>this.intercept(event))
      .onPageEnd(()=>{if(!this.previewMode)this.connected();})
      .onConsole((event:OnConsoleEvent)=>{
        const message=event.message.getMessage();
        if(this.previewMode&&message.startsWith('SELF_GS_VIEWER_READY'))this.onReady();
        if(message.startsWith('SELF_GS_VIEWER_ERROR'))this.onFailure(message.replace('SELF_GS_VIEWER_ERROR ',''));
        if(message.startsWith('SELF_GS_VIEWER_INTERACTION'))this.onInteraction();
        console.info('SELF_PERSONAL_VIEWER '+message);
        return false;
      })
  }
}

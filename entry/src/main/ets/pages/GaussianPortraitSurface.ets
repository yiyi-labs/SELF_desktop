import { fileIo as fs } from '@kit.CoreFileKit';
import { webview } from '@kit.ArkWeb';

/** App-private 3DGS bytes served only to the bundled, offline viewer. */
@Component
export struct GaussianPortraitSurface {
  @Prop gaussianPath:string='';
  @Prop viewPath:string='';
  @Prop previewMode:boolean=false;
  onReady:()=>void=()=>{};
  onFailure:(message:string)=>void=()=>{};
  onInteraction:()=>void=()=>{};
  private controller:webview.WebviewController=new webview.WebviewController();

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
      .onConsole((event:OnConsoleEvent)=>{
        const message=event.message.getMessage();
        if(message.startsWith('SELF_GS_VIEWER_READY'))this.onReady();
        if(message.startsWith('SELF_GS_VIEWER_ERROR'))this.onFailure(message.replace('SELF_GS_VIEWER_ERROR ',''));
        if(message.startsWith('SELF_GS_VIEWER_INTERACTION'))this.onInteraction();
        console.info('SELF_PERSONAL_VIEWER '+message);
        return false;
      })
  }
}

import { fileIo as fs } from '@kit.CoreFileKit';
import { webview } from '@kit.ArkWeb';

export interface GalaxyScene { jobId:string; name:string; viewPath:string; scenePath:string; }
interface GalaxyManifestItem { id:string; name:string; view:object; ready:boolean; }

/** One WebGL scene for nearby historical reconstructions; never one Webview per star. */
@Component
export struct GalaxyUniverseSurface {
  @Prop @Watch('itemsChanged') items:GalaxyScene[]=[];
  @Prop selectedId:string='';
  @Prop @Watch('navigationChanged') navigationSerial:number=0;
  @Prop @Watch('travelChanged') travelId:string='';
  @Prop @Watch('optionsChanged') motion:boolean=true;
  @Prop @Watch('optionsChanged') paused:boolean=false;
  @Prop @Watch('optionsChanged') language:string='zh';
  onSelection:(id:string)=>void=()=>{};
  onReady:()=>void=()=>{};
  onFailure:(message:string)=>void=()=>{};
  onInteraction:()=>void=()=>{};
  onApproach:(id:string)=>void=()=>{};
  private controller:webview.WebviewController=new webview.WebviewController();
  private loaded:boolean=false;

  private manifest():string {
    const records:GalaxyManifestItem[]=[];
    for(const item of this.items){
      if(!/^[a-f0-9]{32}$/.test(item.jobId))continue;
      try{
        const text=fs.readTextSync(item.viewPath);
        if(text.length>4096)continue;
        const view=JSON.parse(text) as object;
        records.push({id:item.jobId,name:item.name.slice(0,24),view,ready:!!item.scenePath&&fs.accessSync(item.scenePath)});
      }catch(_){/* A missing view is not a navigable model. */}
    }
    return JSON.stringify({items:records,selectedId:this.selectedId});
  }
  private itemsChanged():void{
    if(this.loaded)this.controller.runJavaScript('window.selfGalaxy && window.selfGalaxy.sync('+this.manifest()+')')
      .catch((error:Error)=>console.warn('SELF_GALAXY_SYNC_FAILED '+String(error)));
  }
  private navigationChanged():void{
    if(this.loaded&&/^[a-f0-9]{32}$/.test(this.selectedId))
      this.controller.runJavaScript('window.selfGalaxy && window.selfGalaxy.goTo('+JSON.stringify(this.selectedId)+')')
        .catch((error:Error)=>console.warn('SELF_GALAXY_NAV_FAILED '+String(error)));
  }
  private optionsChanged():void{
    if(this.loaded)this.controller.runJavaScript('window.selfGalaxy && window.selfGalaxy.configure('+
      JSON.stringify({motion:this.motion,language:this.language,embedded:true,paused:this.paused})+')')
      .catch((error:Error)=>console.warn('SELF_GALAXY_OPTIONS_FAILED '+String(error)));
  }
  private travelChanged():void{
    if(!this.loaded)return;
    const command=/^[a-f0-9]{32}$/.test(this.travelId)?
      'window.selfGalaxy.travelTo('+JSON.stringify(this.travelId)+')':'window.selfGalaxy.cancelTravel()';
    this.controller.runJavaScript('window.selfGalaxy && '+command)
      .catch((error:Error)=>console.warn('SELF_GALAXY_TRAVEL_FAILED '+String(error)));
  }
  private intercept(event:OnInterceptRequestEvent):WebResourceResponse|null {
    const url=event.request.getRequestUrl();
    const isManifest=url==='https://self.local/galaxies.json';
    const match=/^https:\/\/self\.local\/galaxy\/([a-f0-9]{32})\.ply$/.exec(url);
    if(!isManifest&&!match)return null;
    try{
      const response=new WebResourceResponse();
      if(isManifest){response.setResponseData(this.manifest());response.setResponseMimeType('application/json');}
      else{
        const item=this.items.find((star:GalaxyScene)=>star.jobId===match![1]);
        if(!item||!item.scenePath)throw new Error('scene_missing');
        const file=fs.openSync(item.scenePath,fs.OpenMode.READ_ONLY);
        let bytes:ArrayBuffer;
        try{
          const size=fs.statSync(file.fd).size;
          if(size<4096||size>12*1024*1024)throw new Error('scene_size');
          bytes=new ArrayBuffer(size);
          if(fs.readSync(file.fd,bytes,{length:size})!==size)throw new Error('scene_short_read');
        }finally{fs.closeSync(file);}
        response.setResponseData(bytes);response.setResponseMimeType('application/octet-stream');
        console.info('SELF_GALAXY_ASSET_SERVED '+match![1]+' '+bytes.byteLength);
      }
      response.setResponseCode(200);response.setReasonMessage('OK');
      response.setResponseHeader([{headerKey:'Access-Control-Allow-Origin',headerValue:'*'}]);
      return response;
    }catch(error){console.error('SELF_GALAXY_ASSET_FAILED '+String(error));return null;}
  }
  build(){
    Web({src:$rawfile('gs-universe.html'),controller:this.controller})
      .width('100%').height('100%').backgroundColor('#02040B')
      .onInterceptRequest((event:OnInterceptRequestEvent)=>this.intercept(event))
      .onPageEnd(()=>{this.loaded=true;this.optionsChanged();this.itemsChanged();this.travelChanged();})
      .onConsole((event:OnConsoleEvent)=>{
        const message=event.message.getMessage();
        if(message.startsWith('SELF_GALAXY_RENDER_READY'))this.onReady();
        if(message.startsWith('SELF_GALAXY_ERROR'))this.onFailure(message.slice(18));
        if(message.startsWith('SELF_GALAXY_INTERACTION'))this.onInteraction();
        if(message.startsWith('SELF_GALAXY_APPROACH_COMPLETE ')){
          const id=message.slice('SELF_GALAXY_APPROACH_COMPLETE '.length);
          if(id===this.travelId)this.onApproach(id);
        }
        if(message.startsWith('SELF_GALAXY_SELECT ')){
          const id=message.slice(19);
          if(this.items.some((item:GalaxyScene)=>item.jobId===id))this.onSelection(id);
        }
        console.info('SELF_GALAXY_VIEWER '+message);
        return false;
      });
  }
}

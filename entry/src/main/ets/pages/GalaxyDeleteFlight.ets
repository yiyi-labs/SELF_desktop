import { GalaxyDeleteDust } from './GalaxyDeleteDust';
import { LengthMetricsUnit } from '@kit.ArkUI';

export interface GalaxyDeleteFlightRequest {id:string;token:number;x:number;y:number;width:number;height:number;}

// ArkUI @Prop recursively observes arrays. Native typed arrays must stay outside that state graph.
const pendingDust:Map<number,GalaxyDeleteDust>=new Map<number,GalaxyDeleteDust>();
let dustToken:number=0;
export function registerGalaxyDust(dust:GalaxyDeleteDust):number{
  const token=++dustToken;pendingDust.set(token,dust);return token;
}
export function takeGalaxyDust(token:number):GalaxyDeleteDust|undefined{
  const dust=pendingDust.get(token);pendingDust.delete(token);return dust;
}
export function discardGalaxyDust(token:number):void{
  const dust=pendingDust.get(token);if(dust)dust.release();pendingDust.delete(token);
}

/** A window-level layer lets the breeze carry grains beyond the scroll panel. */
@Component
export struct GalaxyDeleteFlight {
  @Prop @Watch('requestChanged') request:GalaxyDeleteFlightRequest|undefined=undefined;
  @Prop @Watch('activityChanged') active:boolean=true;
  @Prop @Watch('activityChanged') motion:boolean=true;
  onEnded:(id:string,height:number)=>void=()=>{};
  onDiagnostics:(value:string)=>void=()=>{};
  @State private canvasWidth:number=1;
  @State private canvasHeight:number=1;
  @State private canvasX:number=0;
  @State private canvasY:number=0;
  @State private displayScale:number=1;
  private drawing:CanvasRenderingContext2D=new CanvasRenderingContext2D(new RenderingContextSettings(true),LengthMetricsUnit.PX);
  private timer:number=-1;
  private prepared:boolean=false;
  private paintedRequest:GalaxyDeleteFlightRequest|undefined=undefined;
  private frame:ImageData|undefined=undefined;
  private dust:GalaxyDeleteDust|undefined=undefined;
  private started:number=0;
  private lastFrame:number=-1;
  private frameCount:number=0;
  private paintTime:number=0;
  private maxPaint:number=0;
  private prepareTime:number=0;
  private clear():void{
    if(this.timer>=0)clearInterval(this.timer);
    this.timer=-1;
    if(this.prepared&&this.paintedRequest&&this.dust){
      const request=this.paintedRequest,dust=this.dust;
      this.drawing.clearRect(0,0,dust.bufferWidth,dust.bufferHeight);
      if(this.frameCount)console.info('SELF_STAR_DISSOLVE_RASTER frames='+this.frameCount+' mean='+
        Math.round(this.paintTime/this.frameCount)+' max='+this.maxPaint+'ms');
      if(this.frameCount)this.onDiagnostics('frames='+this.frameCount+' mean='+Math.round(this.paintTime/this.frameCount)+' max='+this.maxPaint+'ms prepare='+this.prepareTime+'ms');
    }
    if(this.dust)this.dust.release();this.dust=undefined;
    this.frame=undefined;this.lastFrame=-1;this.frameCount=0;this.paintTime=0;this.maxPaint=0;
    this.paintedRequest=undefined;
  }
  aboutToDisappear():void{this.clear();this.prepared=false;}
  private activityChanged():void{
    if(!this.active||!this.motion){this.clear();if(this.request){discardGalaxyDust(this.request.token);this.onEnded(this.request.id,this.request.height);}}
  }
  private requestChanged():void{
    this.clear();
    if(!this.request||!this.prepared||!this.active||!this.motion)return;
    const before=Date.now(),dust=takeGalaxyDust(this.request.token);
    if(!dust){this.onDiagnostics('missing raster payload');this.onEnded(this.request.id,this.request.height);return;}
    this.dust=dust;this.paintedRequest=this.request;
    try{
      // One pixel per vp is enough for dissolving grains. Scale the texture in the compositor,
      // instead of processing the tablet's much larger physical-pixel surface on the UI thread.
      this.displayScale=this.getUIContext().vp2px(1);
      this.canvasWidth=dust.bufferWidth/this.displayScale;this.canvasHeight=dust.bufferHeight/this.displayScale;
      this.canvasX=this.request.x-dust.left;this.canvasY=this.request.y-dust.top;
      this.frame=new ImageData(dust.bufferWidth,dust.bufferHeight,
        new Uint8ClampedArray(dust.bufferWidth*dust.bufferHeight*4),LengthMetricsUnit.PX);
      dust.prepare(this.frame.width,this.frame.height);
    }catch(error){
      const id=this.request.id,height=dust.height;this.clear();
      this.onDiagnostics('raster failed '+String(error));
      console.warn('SELF_STAR_DISSOLVE_RASTER_FAILED '+String(error));this.onEnded(id,height);return;
    }
    console.info('SELF_STAR_DISSOLVE_PARTICLES '+dust.tiles.filter((tile)=>tile.alpha>0).length+
      ' prepare='+String(Date.now()-before)+'ms raster='+this.frame.width+'x'+this.frame.height);
    this.onDiagnostics('particles='+dust.tiles.filter((tile)=>tile.alpha>0).length+' prepare='+String(Date.now()-before)+
      'ms raster='+this.frame.width+'x'+this.frame.height);
    this.prepareTime=Date.now()-before;this.started=Date.now();this.paint();
    this.timer=setInterval(()=>{
      if(!this.request){this.clear();return;}
      if(Date.now()-this.started>=GalaxyDeleteDust.duration){
        const id=this.request.id,height=this.request.height;this.clear();this.onEnded(id,height);return;
      }
      this.paint();
    },GalaxyDeleteDust.step);
  }
  private paint():void{
    if(!this.request||!this.frame||!this.dust)return;
    const before=Date.now(),request=this.request,dust=this.dust,elapsed=before-this.started;
    const sampled=Math.floor(elapsed/GalaxyDeleteDust.step);if(sampled===this.lastFrame)return;
    this.lastFrame=sampled;dust.render(this.frame.data,elapsed);
    this.drawing.putImageData(this.frame,0,0);
    const cost=Date.now()-before;this.frameCount++;this.paintTime+=cost;this.maxPaint=Math.max(this.maxPaint,cost);
  }
  build(){
    Stack({alignContent:Alignment.TopStart}){
      Canvas(this.drawing).width(this.canvasWidth).height(this.canvasHeight)
        .scale({x:this.displayScale,y:this.displayScale,centerX:0,centerY:0})
        .position({x:this.canvasX,y:this.canvasY}).hitTestBehavior(HitTestMode.None).accessibilityLevel('no')
        .onReady(()=>{if(!this.prepared){this.prepared=true;this.requestChanged();}
          else{this.lastFrame=-1;this.paint();}})
    }.width('100%').height('100%').hitTestBehavior(HitTestMode.None).accessibilityLevel('no')
  }
}

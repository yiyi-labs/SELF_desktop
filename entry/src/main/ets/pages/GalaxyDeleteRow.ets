import { image } from '@kit.ImageKit';
import { GalaxyDeleteDust } from './GalaxyDeleteDust';
import { GalaxyDeleteFlightRequest, registerGalaxyDust, discardGalaxyDust } from './GalaxyDeleteFlight';

@Component
export struct GalaxyDeleteRow {
  @Prop rowId:string='';
  @Prop @Watch('deletionChanged') deleting:boolean=false;
  @Prop @Watch('activityChanged') active:boolean=true;
  @Prop @Watch('activityChanged') motion:boolean=true;
  @BuilderParam content:()=>void;
  onDissolved:(id:string,height:number)=>void=()=>{};
  onFlight:(request:GalaxyDeleteFlightRequest)=>void=()=>{};
  onDiagnostics:(value:string)=>void=()=>{};
  @State private snapshotVisible:boolean=false;
  @State private rowWidth:number=264;
  @State private rowHeight:number=52;
  private snapshot:image.PixelMap|undefined=undefined;
  private timer:number=-1;
  private generation:number=0;
  private payloadToken:number=-1;
  private finished:boolean=false;
  private rowX:number=0;
  private rowY:number=0;
  private clear():void{
    this.generation++;
    if(this.timer>=0)clearTimeout(this.timer);
    this.timer=-1;
    if(this.payloadToken>=0)discardGalaxyDust(this.payloadToken);this.payloadToken=-1;
    if(this.snapshot){this.snapshot.release().catch(()=>{});this.snapshot=undefined;}
    this.snapshotVisible=false;
  }
  aboutToDisappear():void{this.clear();}
  private finish():void{
    if(this.finished)return;
    this.finished=true;this.clear();this.onDissolved(this.rowId,this.rowHeight);
  }
  private activityChanged():void{if(this.deleting&&(!this.motion||!this.active))this.finish();}
  private deletionChanged():void{
    if(!this.deleting){this.clear();this.finished=false;return;}
    if(!this.motion||!this.active){this.finish();return;}
    this.captureAndDissolve();
  }
  private async captureAndDissolve():Promise<void>{
    const generation=++this.generation;
    try{
      const snapshot=await this.getUIContext().getComponentSnapshot().get('galaxy-row-image-'+this.rowId);
      if(generation!==this.generation||!this.deleting){snapshot.release().catch(()=>{});return;}
      this.snapshot=snapshot;
      const info=snapshot.getImageInfoSync(),buffer=new ArrayBuffer(snapshot.getPixelBytesNumber());
      snapshot.readPixelsToBufferSync(buffer);
      const dust=new GalaxyDeleteDust(this.rowWidth,this.rowHeight,new Uint8Array(buffer),info.size.width,info.size.height,
        info.pixelFormat===image.PixelMapFormat.BGRA_8888,info.alphaType===image.AlphaType.PREMUL);
      snapshot.release().catch(()=>{});this.snapshot=undefined;
      this.payloadToken=registerGalaxyDust(dust);
      this.onFlight({id:this.rowId,token:this.payloadToken,x:this.rowX,y:this.rowY,width:this.rowWidth,height:this.rowHeight});
      this.snapshotVisible=true;
      // Keep the occupied height, but do not redraw the row: its real pixels now live in the flight raster.
      // The flight completion owns the normal finish; this only recovers an unavailable canvas.
      this.timer=setTimeout(()=>this.finish(),GalaxyDeleteDust.duration+600);
    }catch(error){this.onDiagnostics('snapshot failed '+String(error));console.warn('SELF_STAR_DISSOLVE_SNAPSHOT_FAILED '+String(error));this.finish();}
  }
  build(){
    Stack({alignContent:Alignment.TopStart}){
      Column(){this.content()}.id('galaxy-row-image-'+this.rowId).width('100%')
        .opacity(this.snapshotVisible?0:1)
        .onAreaChange((_old:Area,current:Area)=>{
          if(!this.deleting){this.rowWidth=Number(current.width);this.rowHeight=Number(current.height);
            this.rowX=Number(current.globalPosition.x);this.rowY=Number(current.globalPosition.y);}
        })
    }.width('100%').enabled(!this.deleting)
  }
}

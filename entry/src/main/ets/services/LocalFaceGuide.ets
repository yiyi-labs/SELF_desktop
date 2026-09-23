import { faceDetector } from '@kit.CoreVisionKit';
import { image } from '@kit.ImageKit';
export interface FaceGuide {x:number;y:number;size:number;}
/** Local, bounded-rate detection. No disk writes, network calls, identity or emotion analysis. */
export class LocalFaceGuide {
 private stopped:boolean=false;
 private initialized:boolean=false;
 private timer:number=-1;
 private task:Promise<void>|undefined;
 private closing:Promise<void>|undefined;
 private errors:number=0;
 onResult:(face:FaceGuide|undefined)=>void=()=>{};
 onAvailable:(available:boolean)=>void=()=>{};
 async start(surface:string):Promise<void>{this.task=this.initialize(surface);await this.task;}
 private async initialize(surface:string):Promise<void>{
  try{
   if(!canIUse('SystemCapability.AI.Face.Detector')){this.onAvailable(false);console.info('SELF_LOCAL_FACE unsupported');return;}
   this.initialized=await faceDetector.init();
   if(this.stopped||!this.initialized)return;
   this.onAvailable(true);console.info('SELF_LOCAL_FACE initialized');this.schedule(surface);
  }catch(_){this.onAvailable(false);console.info('SELF_LOCAL_FACE unavailable');}
 }
 private schedule(surface:string):void{
  if(this.stopped)return;
  this.timer=setTimeout(()=>{this.task=this.detect(surface);},550);
 }
 private async detect(surface:string):Promise<void>{
  let pixel:image.PixelMap|undefined;
  try{
   pixel=await image.createPixelMapFromSurfaceWithTransformation(surface,false);
   const info=await pixel.getImageInfo();const scale=Math.min(1,640/Math.max(info.size.width,info.size.height));
   if(scale<1)await pixel.scale(scale,scale);
   await pixel.convertPixelFormat(image.PixelMapFormat.RGBA_8888);
   if(this.stopped)return;
   const faces=await faceDetector.detect({pixelMap:pixel});
   if(this.stopped)return;
   const face=faces.length===1&&faces[0].probability>=.85?faces[0]:undefined;
   if(face){const w=info.size.width*scale,h=info.size.height*scale;this.onResult({x:(face.rect.left+face.rect.width/2)/w,y:(face.rect.top+face.rect.height/2)/h,size:Math.max(face.rect.width/w,face.rect.height/h)});}
   else this.onResult(undefined);
   this.errors=0;
  }catch(_){this.onResult(undefined);if(++this.errors>=3){this.onAvailable(false);this.stopped=true;console.info('SELF_LOCAL_FACE stream_unavailable');}}
  finally{try{await pixel?.release();}catch(_){}if(!this.stopped)this.schedule(surface);}
 }
 stop():Promise<void>{if(!this.closing)this.closing=this.finishStop();return this.closing;}
 private async finishStop():Promise<void>{this.stopped=true;clearTimeout(this.timer);try{await this.task;}catch(_){}if(this.initialized){try{await faceDetector.release();}catch(_){}this.initialized=false;}}
}

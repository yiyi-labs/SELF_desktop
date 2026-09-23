import { deviceInfo } from '@kit.BasicServicesKit';
import { image } from '@kit.ImageKit';
import { fileIo as fs } from '@kit.CoreFileKit';
import { faceDetector } from '@kit.CoreVisionKit';
import native from 'libself_native.so';
import { DetectedFace,FaceAnchor,FaceAnchorTracker,FacePoint } from './FaceAnchorTracker';
interface FrameRequest {op:string;width:number;height:number;timestamp:number;record:boolean;detect:boolean;}
interface FrameResult {faces:DetectedFace[];rawFaces:number;peakScore:number;processingMs:number;frames:number;}
interface StartRequest {op:string;fd:number;width:number;height:number;}
interface StopRequest {op:string;timestamp:number;}
interface ClipStats {frames:number;width:number;height:number;durationMs:number;fps:number;}
interface ClipEvidence {schemaVersion:number;source:string;createdAt:number;durationMs:number;width:number;height:number;bytes:number;frames:number;fps:number;previewStarted:boolean;reconstructionStatus:string;poseData:boolean;private:boolean;}
/** Device-local camera Surface only, no UI capture/network. One in-flight CPU job. */
export class LocalFaceGuide {
 private stopped:boolean=false;
 private task:Promise<void>|undefined;private closing:Promise<void>|undefined;
 private errors:number=0;private tracker:FaceAnchorTracker=new FaceAnchorTracker();
 private width:number=0;private height:number=0;
 private recording:boolean=false;private settling:boolean=false;
 private file:fs.File|undefined;private path:string='';private startedAt:number=0;
 private logAt:number=0;
 private visionTried:boolean=false;private visionReady:boolean=false;private visionAt:number=0;
 private lastVisionFaces:DetectedFace[]=[];private lastVisionAt:number=0;
 private visionMisses:number=0;
 private visionLogAt:number=0;private visionLogCount:number=-1;
 onResult:(face:FaceAnchor|undefined)=>void=()=>{};
 onAvailable:(available:boolean)=>void=()=>{};
 onError:(message:string)=>void=()=>{};
 onOrientationChanged:()=>void=()=>{};
 private nextFrameAt:number=0;private detectedAt:number=0;
 async consume(frame:image.Image,rotation:number,format:number):Promise<void>{
  if(this.stopped||Date.now()<this.nextFrameAt){await frame.release();return;}
  // The receiver already allows only one in-flight frame. Keep detection bounded
  // independently, so video is not artificially capped at ten frames per second.
  this.nextFrameAt=Date.now()+(this.recording?33:80);this.task=this.read(frame,rotation,format);await this.task;
 }
 private async read(frame:image.Image,rotation:number,format:number):Promise<void>{
  let pixel:image.PixelMap|undefined;const began=Date.now();let stage='receiver';
  try{
   const component=await frame.getComponent(image.ComponentType.JPEG);
   const w=frame.size.width,h=frame.size.height;
   // CameraFormat 3 is RGBA, 1003 is NV21. Never infer format from byte count.
   let formatPixel=image.PixelMapFormat.RGBA_8888;
   if(format!==3&&format!==1003)throw new Error('Unsupported analysis format '+format);
   const stride=component.rowStride;
   let bytes=component.byteBuffer;
   if(format===3&&stride!==w*4){
    const packed=new Uint8Array(w*h*4),source=new Uint8Array(bytes);
    if(stride<w*4||bytes.byteLength<stride*h)throw new Error('Invalid RGBA row stride');
    for(let y=0;y<h;y++)packed.set(source.subarray(y*stride,y*stride+w*4),y*w*4);
    bytes=packed.buffer as ArrayBuffer;
   }
   if(format===1003){
    formatPixel=image.PixelMapFormat.NV21;
    if(stride<w||bytes.byteLength<stride*h*3/2)throw new Error('Invalid NV21 row stride');
    if(stride!==w){const packed=new Uint8Array(w*h*3/2),source=new Uint8Array(bytes);for(let y=0;y<h*3/2;y++)packed.set(source.subarray(y*stride,y*stride+w),y*w);bytes=packed.buffer as ArrayBuffer;}
   }
   // srcPixelFormat describes the camera buffer. pixelFormat only describes
   // the result; omitting srcPixelFormat makes Image Kit assume BGRA input.
   pixel=await image.createPixelMap(bytes,{size:{width:w,height:h},srcPixelFormat:formatPixel,pixelFormat:image.PixelMapFormat.RGBA_8888,editable:true});
   if(rotation)await pixel.rotate(rotation);
   // API26 emulator RGBA producer has a bottom-up camera buffer origin.
   // Match the displayed preview; do not apply this device-path correction to NV21.
   if(format===3&&deviceInfo.productModel==='emulator')await pixel.flip(false,true);
   stage='geometry';const info=await pixel.getImageInfo();const scale=Math.min(1,960/Math.max(info.size.width,info.size.height));
   const width=Math.floor(info.size.width*scale/2)*2,height=Math.floor(info.size.height*scale/2)*2;
   if(width!==info.size.width||height!==info.size.height)await pixel.scale(width/info.size.width,height/info.size.height);
   const actual=await pixel.getImageInfo();
   stage='read';const rgba=new ArrayBuffer(actual.size.width*actual.size.height*4);await pixel.readPixelsToBuffer(rgba);
   if(this.stopped)return;
   const changed=this.width!==actual.size.width||this.height!==actual.size.height;
   if(changed){this.tracker.reset();if(this.recording){this.onOrientationChanged();return;}}
   this.width=actual.size.width;this.height=actual.size.height;
   const detect=began-this.detectedAt>=100;if(detect)this.detectedAt=began;
   const request:FrameRequest={op:'frame',width:this.width,height:this.height,timestamp:began,record:this.recording&&!this.settling,detect};
   stage='native';const result=JSON.parse((await native.camera(JSON.stringify(request),rgba)).json) as FrameResult;
   if(this.stopped)return;
   let found:DetectedFace[]=result.faces;
   if(!this.visionTried){
    this.visionTried=true;
    try{this.visionReady=await faceDetector.init();console.info('SELF_COREVISION_INIT '+this.visionReady);}
    catch(e){console.info('SELF_COREVISION_UNAVAILABLE '+String(e));}
   }
   if(detect&&this.visionReady&&began-this.visionAt>=350){
    this.visionAt=began;
    try{
     // Camera Kit and this PixelMap use the same SDK rotation. A single
     // Core Vision pass avoids four expensive orientation probes per miss.
     const info:faceDetector.VisionInfo={pixelMap:pixel};
     const faces=await faceDetector.detect(info);
     const official=faces.map((face:faceDetector.Face)=>({confidence:face.probability,x:face.rect.left/this.width,y:face.rect.top/this.height,width:face.rect.width/this.width,height:face.rect.height/this.height,landmarks:face.points.map((point:faceDetector.FacePoint)=>({x:point.x/this.width,y:point.y/this.height} as FacePoint)),yaw:face.pose.yaw,roll:face.pose.roll} as DetectedFace));
     if(official.length!==this.visionLogCount||began-this.visionLogAt>5000){this.visionLogAt=began;this.visionLogCount=official.length;console.info('SELF_COREVISION_FACES '+official.length);}
     if(official.length===1&&official[0].confidence>=.8&&official[0].landmarks.length===5){this.lastVisionFaces=official;this.lastVisionAt=began;this.visionMisses=0;}
     else if(++this.visionMisses>=3){this.lastVisionFaces=[];}
    }catch(e){console.info('SELF_COREVISION_DETECT_FAILED '+String(e));this.visionReady=false;}
   }
   if(this.visionReady){
    const confirmed=this.lastVisionFaces.length===1&&began-this.lastVisionAt<1400?this.lastVisionFaces[0]:undefined;
    if(!confirmed)found=[];
    else{
     const nearby=found.find((candidate:DetectedFace)=>candidate.landmarks.length===5&&
      Math.hypot(candidate.landmarks[2].x-confirmed.landmarks[2].x,candidate.landmarks[2].y-confirmed.landmarks[2].y)<Math.max(.09,confirmed.width*.65)&&
      candidate.width/confirmed.width>.55&&candidate.width/confirmed.width<1.8);
     found=nearby?[nearby]:began-this.lastVisionAt<450?[confirmed]:[];
    }
   }
   if(detect)this.onResult(this.tracker.update(found,began,this.width/this.height));
   this.onAvailable(true);this.errors=0;
   if(Date.now()-this.logAt>2500){
    this.logAt=Date.now();
    console.info('SELF_CAMERA_FRAME '+JSON.stringify({width:this.width,height:this.height,format,detected:detect,faces:found.length,rawFaces:result.rawFaces,peakScore:result.peakScore,coreVision:this.visionReady,processingMs:result.processingMs,frames:result.frames,cycleMs:Date.now()-began,source:'camera-image-receiver',privatePixelsLogged:false}));
   }
  }catch(e){
   console.info('SELF_CAMERA_READ_ERROR '+stage+' '+JSON.stringify(e));this.onResult(undefined);this.tracker.reset();
   if(++this.errors>=3){this.onAvailable(false);this.stopped=true;await this.cancelRecording();this.onError('相机画面读取失败（'+stage+'），请重新打开：'+JSON.stringify(e));}
  }finally{try{await pixel?.release();}catch(_){}try{await frame.release();}catch(_){}}
 }
 async startRecording(filesDir:string):Promise<void>{
  if(this.stopped||!this.width||this.recording)throw new Error('请等相机画面准备好');
  this.settling=true;await this.task;
  try{
   const root=filesDir+'/captures';if(!fs.accessSync(root))fs.mkdirSync(root);
   this.startedAt=Date.now();this.path=root+'/capture-'+this.startedAt+'.mp4';
   this.file=fs.openSync(this.path,fs.OpenMode.CREATE|fs.OpenMode.READ_WRITE|fs.OpenMode.TRUNC);
   const request:StartRequest={op:'start',fd:this.file.fd,width:this.width,height:this.height};
   await native.camera(JSON.stringify(request));this.recording=true;
  }catch(e){await this.cancelRecording();throw new Error((e as Error).message);}finally{this.settling=false;}
 }
 async stopRecording():Promise<string>{
  if(!this.recording)throw new Error('当前没有正在录制的视频');
  this.settling=true;await this.task;this.recording=false;
  try{
   const request:StopRequest={op:'stop',timestamp:Date.now()};
   const stats=JSON.parse((await native.camera(JSON.stringify(request))).json) as ClipStats;
   if(this.file){fs.closeSync(this.file);this.file=undefined;}
   const bytes=fs.statSync(this.path).size;if(bytes<1024)throw new Error('未获得有效视频');
   const evidence:ClipEvidence={schemaVersion:2,source:'native-camera-receiver-software-h264',createdAt:this.startedAt,durationMs:stats.durationMs,width:stats.width,height:stats.height,bytes,frames:stats.frames,fps:stats.fps,previewStarted:true,reconstructionStatus:'not-reconstructed',poseData:false,private:true};
   const meta=fs.openSync(this.path+'.json',fs.OpenMode.CREATE|fs.OpenMode.READ_WRITE);try{fs.writeSync(meta.fd,JSON.stringify(evidence));}finally{fs.closeSync(meta);}
   const path=this.path;this.path='';console.info('SELF_CAMERA_SAVED '+JSON.stringify(evidence));return path;
  }catch(e){await this.cancelRecording();throw new Error((e as Error).message);}finally{this.settling=false;}
 }
 private async cancelRecording():Promise<void>{
  this.recording=false;try{await native.camera('{"op":"cancel"}');}catch(_){}
  if(this.file){try{fs.closeSync(this.file);}catch(_){}this.file=undefined;}
  if(this.path&&fs.accessSync(this.path))fs.unlinkSync(this.path);this.path='';
 }
 stop():Promise<void>{if(!this.closing)this.closing=this.finishStop();return this.closing;}
 private async finishStop():Promise<void>{this.stopped=true;try{await this.task;}catch(_){}await this.cancelRecording();if(this.visionReady){try{await faceDetector.release();}catch(_){}}this.tracker.reset();}
}

import { deviceInfo } from '@kit.BasicServicesKit';
import { image } from '@kit.ImageKit';
import { fileIo as fs } from '@kit.CoreFileKit';
import native from 'libself_native.so';
import { DetectedFace,FaceAnchor,FaceAnchorTracker } from './FaceAnchorTracker';
interface FrameRequest {op:string;width:number;height:number;timestamp:number;record:boolean;detect:boolean;}
interface FrameResult {faces:DetectedFace[];processingMs:number;frames:number;}
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
   pixel=await image.createPixelMap(bytes,{size:{width:w,height:h},pixelFormat:formatPixel,editable:true});
   if(rotation)await pixel.rotate(rotation);
   // API26 emulator RGBA producer has a bottom-up camera buffer origin.
   // Match the displayed preview; do not apply this device-path correction to NV21.
   if(format===3&&deviceInfo.productModel==='emulator')await pixel.flip(false,true);
   stage='geometry';const info=await pixel.getImageInfo();const scale=Math.min(1,960/Math.max(info.size.width,info.size.height));
   const width=Math.floor(info.size.width*scale/2)*2,height=Math.floor(info.size.height*scale/2)*2;
   if(width!==info.size.width||height!==info.size.height)await pixel.scale(width/info.size.width,height/info.size.height);
   stage='format';if(info.pixelFormat!==image.PixelMapFormat.RGBA_8888)await pixel.convertPixelFormat(image.PixelMapFormat.RGBA_8888);
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
   if(detect)this.onResult(this.tracker.update(result.faces,began,this.width/this.height));
   this.onAvailable(true);this.errors=0;
   if(Date.now()-this.logAt>2500){this.logAt=Date.now();console.info('SELF_CAMERA_FRAME '+JSON.stringify({width:this.width,height:this.height,detected:detect,faces:result.faces.length,processingMs:result.processingMs,frames:result.frames,cycleMs:Date.now()-began,source:'camera-image-receiver',privatePixelsLogged:false}));}
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
 private async finishStop():Promise<void>{this.stopped=true;try{await this.task;}catch(_){}await this.cancelRecording();this.tracker.reset();}
}

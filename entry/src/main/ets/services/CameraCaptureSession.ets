import { camera } from '@kit.CameraKit';
import { media } from '@kit.MediaKit';
import { common, abilityAccessCtrl } from '@kit.AbilityKit';
import { fileIo as fs } from '@kit.CoreFileKit';
import { display } from '@kit.ArkUI';

interface CameraDeviceEvidence {position:number;type:number;connection:number;}
interface CameraClipEvidence {schemaVersion:number;source:string;createdAt:number;durationMs:number;width:number;height:number;bytes:number;previewStarted:boolean;reconstructionStatus:string;poseData:boolean;private:boolean;}

/** Native Camera Kit surface preview + silent MP4. No network or reconstruction here. */
export class CameraCaptureSession {
 private input:camera.CameraInput|undefined;
 private preview:camera.PreviewOutput|undefined;
 private metadata:camera.MetadataOutput|undefined;
 private watchingDisplay:boolean=false;
 private displayChanged: (id:number)=>void=()=>this.updateRotation();
 onGeometry:(width:number,height:number,rotation:number)=>void=()=>{};
 onFace:(face:camera.MetadataObject|undefined)=>void=()=>{};
 faceDetection:boolean=false;
 private video:camera.VideoOutput|undefined;
 private session:camera.VideoSession|undefined;
 private recorder:media.AVRecorder|undefined;
 private file:fs.File|undefined;
 private path:string='';private completed:boolean=false;private recording:boolean=false;
 private disposed:boolean=false;private opening:Promise<string>|undefined;
 private closing:Promise<void>|undefined;
 private previewStarted:boolean=false;private startedAt:number=0;
 private width:number=0;private height:number=0;
 onPreview:()=>void=()=>{};
 onError:(message:string)=>void=()=>{};
 canRecord:boolean=false;
 async open(context:common.UIAbilityContext,surfaceId:string,front:boolean):Promise<string>{
  this.opening=this.configure(context,surfaceId,front);return this.opening;
 }
 private async configure(context:common.UIAbilityContext,surfaceId:string,front:boolean):Promise<string>{
  try{
   const permissions=await abilityAccessCtrl.createAtManager().requestPermissionsFromUser(context,['ohos.permission.CAMERA']);
   if(permissions.authResults.some((result:number)=>result!==0))throw new Error('尚未允许摄像头，可在系统设置中开启后重试');
   if(this.disposed)throw new Error('已关闭相机');
   const manager=camera.getCameraManager(context);const devices=manager.getSupportedCameras();
   console.info('SELF_CAMERA_DEVICES '+JSON.stringify(devices.map((d:camera.CameraDevice)=>({position:d.cameraPosition,type:d.cameraType,connection:d.connectionType} as CameraDeviceEvidence))));
   if(!devices.length)throw new Error('当前设备没有可用摄像头，请检查 Windows 摄像头权限与占用情况');
   const target=devices.find((d:camera.CameraDevice)=>d.cameraPosition===(front?camera.CameraPosition.CAMERA_POSITION_FRONT:camera.CameraPosition.CAMERA_POSITION_BACK))||devices[0];
   if(!manager.getSupportedSceneModes(target).includes(camera.SceneMode.NORMAL_VIDEO))throw new Error('当前摄像头没有开放标准录像模式');
   const capabilities=manager.getSupportedOutputCapability(target,camera.SceneMode.NORMAL_VIDEO);
   console.info('SELF_CAMERA_METADATA_TYPES '+JSON.stringify(capabilities.supportedMetadataObjectTypes));
   this.recorder=await media.createAVRecorder();const encoders=await this.recorder.getAvailableEncoder();
   console.info('SELF_CAMERA_ENCODERS '+JSON.stringify(encoders));
   console.info('SELF_CAMERA_PROFILES '+JSON.stringify(capabilities.videoProfiles));
   const encoder=encoders.find((e:media.EncoderInfo)=>e.mimeType===media.CodecMimeType.VIDEO_AVC)||encoders.find((e:media.EncoderInfo)=>e.type==='video');
   const videos=capabilities.videoProfiles.filter((p:camera.VideoProfile)=>p.size.width<=Math.min(1920,encoder?.width?.max||1920)&&p.size.height<=Math.min(1080,encoder?.height?.max||1080)&&p.frameRateRange.min<=30&&p.frameRateRange.max>=30).sort((a:camera.VideoProfile,b:camera.VideoProfile)=>b.size.width-a.size.width);
   const profile=videos.find((v:camera.VideoProfile)=>capabilities.previewProfiles.some((p:camera.Profile)=>p.size.width===v.size.width&&p.size.height===v.size.height));
   if(!profile)throw new Error('当前摄像头未提供匹配的预览与录像规格');
   const previewProfile=capabilities.previewProfiles.find((p:camera.Profile)=>p.size.width===profile.size.width&&p.size.height===profile.size.height);
   if(!previewProfile)throw new Error('没有可用预览规格');
   this.width=profile.size.width;this.height=profile.size.height;
   this.input=manager.createCameraInput(target);await this.input.open();
   if(this.disposed)throw new Error('已关闭相机');
   if(encoder){
   const root=context.filesDir+'/captures';if(!fs.accessSync(root))fs.mkdirSync(root);
   this.path=root+'/capture-'+Date.now()+'.mp4';this.file=fs.openSync(this.path,fs.OpenMode.CREATE|fs.OpenMode.READ_WRITE);
   this.recorder.on('error',(error)=>this.onError('录像不可用：'+error.code));
   const config:media.AVRecorderConfig={videoSourceType:media.VideoSourceType.VIDEO_SOURCE_TYPE_SURFACE_YUV,
    profile:{fileFormat:media.ContainerFormatType.CFT_MPEG_4,videoBitrate:Math.max(encoder.bitRate?.min||1,Math.min(8000000,encoder.bitRate?.max||8000000)),videoCodec:encoder.mimeType,videoFrameWidth:this.width,videoFrameHeight:this.height,videoFrameRate:30},
    url:'fd://'+this.file.fd};
   await this.recorder.prepare(config);
   this.video=manager.createVideoOutput(profile,await this.recorder.getInputSurface());
   this.canRecord=true;
   }else{await this.recorder.release();this.recorder=undefined;}
   this.preview=manager.createPreviewOutput(previewProfile,surfaceId);
   this.preview.on('frameStart',()=>{this.previewStarted=true;this.onPreview();console.info('SELF_CAMERA_PREVIEW_STARTED');});
   this.preview.on('error',(error)=>this.onError('预览不可用：'+error.code));
   this.session=manager.createSession(camera.SceneMode.NORMAL_VIDEO) as camera.VideoSession;
   this.session.beginConfig();this.session.addInput(this.input);
   if(!this.session.canAddOutput(this.preview))throw new Error('设备不支持当前预览规格');
   this.session.addOutput(this.preview);
   // Optional HAL detection. Absence of this capability must never look like a successful face lock.
   const types=capabilities.supportedMetadataObjectTypes;
   const faceType=types.includes(camera.MetadataObjectType.BASIC_FACE_DETECTION)?camera.MetadataObjectType.BASIC_FACE_DETECTION:camera.MetadataObjectType.FACE_DETECTION;
   if(types.includes(faceType)){
    try{this.metadata=manager.createMetadataOutput([faceType]);
     if(this.session.canAddOutput(this.metadata)){
      this.session.addOutput(this.metadata);this.faceDetection=true;
      this.metadata.on('metadataObjectsAvailable',(err,objects)=>{if(!this.disposed)this.onFace(!err&&objects?.length===1?objects[0]:undefined);});
      this.metadata.on('error',()=>{this.faceDetection=false;this.onFace(undefined);});
     }else{await this.metadata.release();this.metadata=undefined;}
    }catch(_){this.faceDetection=false;this.metadata=undefined;}
   }
   if(this.video){if(!this.session.canAddOutput(this.video))throw new Error('设备不支持当前预览与录像组合');this.session.addOutput(this.video);}
   await this.session.commitConfig();
   if(this.disposed)throw new Error('已关闭相机');
   await this.session.start();
   this.updateRotation();display.on('change',this.displayChanged);this.watchingDisplay=true;
   if(this.metadata){try{await this.metadata.start();}catch(_){this.faceDetection=false;}}
   console.info('SELF_CAMERA_READY '+JSON.stringify({width:this.width,height:this.height,fps:30,position:target.cameraPosition,recording:false,canRecord:this.canRecord}));
   return (target.cameraPosition===camera.CameraPosition.CAMERA_POSITION_FRONT?'前置':'后置')+' · '+this.width+' × '+this.height+(this.canRecord?'':' · 当前系统无录像编码器，仅可预览');
  }catch(e){await this.release();throw new Error((e as Error).message||String(e));}
 }
 updateRotation():void{
  if(!this.preview||this.disposed)return;
  try{
   const degrees=display.getDefaultDisplaySync().rotation*90;
   const rotation=this.preview.getPreviewRotation(degrees);
   if(![0,90,180,270].includes(rotation))throw new Error('相机没有返回有效方向');
   // Camera Kit rotates the buffer once. ArkUI only fits the resulting aspect ratio.
   this.preview.setPreviewRotation(rotation,false);
   this.onGeometry(this.width,this.height,rotation);
   console.info('SELF_CAMERA_ROTATION '+JSON.stringify({display:degrees,preview:rotation,width:this.width,height:this.height}));
  }catch(e){this.onError('相机方向设置失败，请重新打开：'+(e as Error).message);}
 }
 async start():Promise<void>{
  if(!this.previewStarted||!this.video||!this.recorder||this.disposed||this.completed)throw new Error('请等候真实预览画面出现');
  await this.recorder.updateRotation(this.video.getVideoRotation(display.getDefaultDisplaySync().rotation*90));
  await this.recorder.start();try{await this.video.start();this.recording=true;this.startedAt=Date.now();}catch(e){await this.release();throw new Error((e as Error).message);}
 }
 async stop():Promise<string>{
  if(!this.recording||!this.recorder||!this.video)throw new Error('当前没有正在录制的视频');
  await this.video.stop();await this.recorder.stop();this.recording=false;
  if(!this.file)throw new Error('录像文件未打开');fs.closeSync(this.file);this.file=undefined;
  const bytes=fs.statSync(this.path).size;if(bytes<1024)throw new Error('录像没有产生有效文件');
  const metadata:CameraClipEvidence={schemaVersion:1,source:'native-camera-kit',createdAt:this.startedAt,durationMs:Date.now()-this.startedAt,width:this.width,height:this.height,bytes,previewStarted:this.previewStarted,reconstructionStatus:'not-reconstructed',poseData:false,private:true};
  const file=fs.openSync(this.path+'.json',fs.OpenMode.CREATE|fs.OpenMode.READ_WRITE);try{fs.writeSync(file.fd,JSON.stringify(metadata));}finally{fs.closeSync(file);}
  this.completed=true;console.info('SELF_CAMERA_SAVED '+JSON.stringify(metadata));return this.path;
 }
 dispose():Promise<void>{this.disposed=true;if(!this.closing)this.closing=this.finishClose();return this.closing;}
 private async finishClose():Promise<void>{try{await this.opening;}catch(_){}await this.release();}
 private async release():Promise<void>{
  if(this.watchingDisplay){display.off('change',this.displayChanged);this.watchingDisplay=false;}
  try{await this.metadata?.stop();}catch(_){}
  try{await this.metadata?.release();}catch(_){}this.metadata=undefined;
  try{await this.session?.stop();}catch(_){}
  try{await this.preview?.release();}catch(_){}this.preview=undefined;
  try{await this.video?.release();}catch(_){}this.video=undefined;
  try{await this.session?.release();}catch(_){}this.session=undefined;
  try{await this.input?.close();}catch(_){}this.input=undefined;
  try{await this.recorder?.release();}catch(_){}this.recorder=undefined;
  if(this.file){try{fs.closeSync(this.file);}catch(_){}this.file=undefined;}
  if(!this.completed&&this.path&&fs.accessSync(this.path))fs.unlinkSync(this.path);
 }
}

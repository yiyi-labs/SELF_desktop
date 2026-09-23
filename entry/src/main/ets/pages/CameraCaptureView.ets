import { LocalFaceGuide } from '../services/LocalFaceGuide';
import { common } from '@kit.AbilityKit';
import { CameraCaptureSession } from '../services/CameraCaptureSession';
import { CaptureMotionGuide } from '../services/CaptureMotionGuide';
import { CaptureMoveHint } from './CaptureMoveHint';
import { ReconstructionClient } from '../services/ReconstructionClient';

@Component
export struct CameraCaptureView {
 @Prop motion:boolean=true;
 @Prop language:string='zh';
 @State status:string='';
 @State ready:boolean=false;
 @State busy:boolean=true;
 @State front:boolean=true;
 @State info:boolean=false;
 @State faceSeen:boolean=false;
 @State faceLocked:boolean=false;
 @State detection:boolean=false;
 @State orbit:number=0;
 @State trackX:number=0;
 @State trackY:number=-24;
 @State ringSize:number=420;
 @State faceRoll:number=0;
 @State faceYaw:number=0;
 @State reconstructionState:string='checking';
 private localGuide:LocalFaceGuide=new LocalFaceGuide();
 private motionGuide:CaptureMotionGuide=new CaptureMotionGuide();
 @State captureIssue:string='';
 @State viewportWidth:number=800;
 @State viewportHeight:number=600;
 @State streamRatio:number=16/9;
 @StorageLink('selfForeground') @Watch('visibilityChanged') foreground:boolean=true;
 onClose:()=>void=()=>{};
 private controller:XComponentController=new XComponentController();
 private capture:CameraCaptureSession=new CameraCaptureSession();
 private faceTimer:number=-1;
 private epoch:number=0;
 private surfaceReady:boolean=false;
 private expired:boolean=false;
 private tr(zh:string,en:string):string{return this.language==='en'?en:zh;}
 private previewWidth():number{return Math.max(this.viewportWidth,this.viewportHeight*this.streamRatio);}
 private previewHeight():number{return Math.max(this.viewportHeight,this.viewportWidth/this.streamRatio);}
 private ring():number{return Math.min(this.viewportWidth*.82,this.viewportHeight*.72,560);}
 private seek():void{this.motionGuide.reset();this.faceSeen=false;this.getUIContext().animateTo({duration:this.motion?420:0,curve:Curve.EaseOut},()=>{this.faceLocked=false;this.ringSize=this.ring();this.trackX=0;this.trackY=0;this.faceRoll=0;this.faceYaw=0;});}
 private async checkReconstruction(epoch:number):Promise<void>{
  this.reconstructionState='checking';this.captureIssue='';
  try{
   const capability=await new ReconstructionClient().probe();
   if(this.expired||epoch!==this.epoch)return;
   // A runtime's presence is not a completed AR capture/import/acceptance pipeline.
   this.reconstructionState=capability.available?'not-connected':'unavailable';
   this.captureIssue=capability.message;
   console.info('SELF_CAMERA_RECON_CAPABILITY '+JSON.stringify(capability));
  }catch(_){if(!this.expired&&epoch===this.epoch){this.reconstructionState='unavailable';this.captureIssue=this.tr('暂时无法确认建模能力，请稍后重试。','Modeling capability could not be checked. Please try again.');}}
 }
 private outcome():string{
  if(this.reconstructionState==='checking')return this.tr('正在检查建模能力…','Checking modeling support…');
  return this.reconstructionState==='unavailable'?this.tr('本机暂不能建模 · 可体验面容跟随','Modeling unavailable here · Face tracking preview'):this.tr('建模流程尚未接通 · 当前仅预览','Modeling is not connected yet · Preview only');
 }
 private async open():Promise<void>{
  const epoch=++this.epoch;this.busy=true;this.ready=false;this.detection=false;this.info=false;clearTimeout(this.faceTimer);this.faceTimer=-1;this.seek();this.checkReconstruction(epoch);
  await this.localGuide.stop();await this.capture.dispose();if(this.expired||!this.foreground||epoch!==this.epoch)return;
  const capture=new CameraCaptureSession();this.capture=capture;this.localGuide=new LocalFaceGuide();
  capture.onFrame=(frame,rotation,format)=>this.localGuide.consume(frame,rotation,format);
  capture.onPreview=()=>{if(!this.expired&&epoch===this.epoch)this.ready=true;};
  capture.onGeometry=(w:number,h:number,rotation:number)=>{if(epoch===this.epoch){const ratio=rotation%180===0?w/h:h/w;if(this.streamRatio!==ratio){this.streamRatio=ratio;this.seek();}}};
  capture.onError=(message:string)=>{if(epoch!==this.epoch)return;this.ready=false;this.status=message;capture.dispose();};
  try{const context=this.getUIContext().getHostContext() as common.UIAbilityContext;
   const label=await capture.open(context,this.controller.getXComponentSurfaceId(),this.front,false);
   if(!this.expired&&epoch===this.epoch){
    this.status=label;
    this.localGuide.onAvailable=(ok:boolean)=>{if(epoch===this.epoch)this.detection=ok;};
    this.localGuide.onError=(message:string)=>{if(epoch===this.epoch){this.status=message;this.detection=false;this.info=true;this.seek();}};
    this.localGuide.onResult=(face)=>{
     if(epoch!==this.epoch||this.expired)return;
     const x=face?(face.x-.5)*this.previewWidth():0,y=face?(face.y-.5)*this.previewHeight():0;
     const visible=!!face&&Math.abs(x)<this.viewportWidth/2-16&&Math.abs(y)<this.viewportHeight/2-16;
     if(!visible){this.motionGuide.update(undefined,Date.now());if(this.faceTimer<0)this.faceTimer=setTimeout(()=>{this.faceTimer=-1;this.seek();},500);return;}
     clearTimeout(this.faceTimer);this.faceTimer=-1;
     // Guidance and tracking begin on entry. No shutter or recording timer can unlock them.
     const confirmedMotion=this.motionGuide.update(face,Date.now());
     const following=confirmedMotion&&face!.locked;
     const acquiring=!this.faceLocked&&following;
     this.faceSeen=true;
     if(acquiring)console.info('SELF_CAMERA_GUIDANCE_FOLLOWING '+JSON.stringify({source:'tracked-relative-face-motion',reconstructionPose:false}));
     this.getUIContext().animateTo({duration:this.motion?(acquiring?440:90):0,curve:Curve.EaseOut},()=>{
      this.faceLocked=following;
      this.ringSize=following?Math.max(22,Math.min(38,face!.width*this.previewWidth()*.16)):this.ring();
      this.trackX=following?x:0;this.trackY=following?y:0;
      this.faceRoll=following?face!.roll:0;this.faceYaw=following?face!.yaw:0;
     });
    };

   }
  }catch(e){if(!this.expired&&epoch===this.epoch)this.status=(e as Error).message;}
  finally{if(epoch===this.epoch)this.busy=false;}
 }
 private visibilityChanged():void{
  if(!this.foreground){this.epoch++;this.ready=false;clearTimeout(this.faceTimer);this.faceTimer=-1;this.localGuide.stop();this.capture.dispose();}
  else if(this.surfaceReady&&!this.expired)this.open();
 }
 aboutToDisappear():void{this.expired=true;this.epoch++;clearTimeout(this.faceTimer);this.localGuide.stop();this.capture.dispose();}
 @Builder icon(symbol:string,label:string,action:()=>void){
  Button(symbol).id(symbol==='ⓘ'?'camera-info':symbol==='‹'?'camera-back':'camera-switch').width(48).height(48).fontSize(25).fontColor(Color.White).backgroundColor('#38FFFFFF')
   .border({width:1,color:'#55FFFFFF'}).borderRadius(24).stateStyles({pressed:{.scale({x:.90,y:.90})},normal:{.scale({x:1,y:1})}}).animation({duration:this.motion?160:0,curve:Curve.EaseOut}).accessibilityText(label).onClick(action)
 }
 build(){
  Stack(){
   XComponent({id:'self-camera-preview',type:XComponentType.SURFACE,controller:this.controller})
    .id('self-camera-preview').width(this.previewWidth()).height(this.previewHeight()).onAreaChange((_old:Area,area:Area)=>console.info('SELF_CAMERA_SURFACE '+JSON.stringify({width:Number(area.width),height:Number(area.height),aspect:this.streamRatio})))
    .onLoad(()=>{this.surfaceReady=true;this.ringSize=this.ring();this.open();if(this.motion)this.getUIContext().animateTo({duration:16000,iterations:-1,curve:Curve.Linear},()=>{this.orbit=360;});})
   Stack(){
    Circle().width(this.ringSize).height(this.ringSize).fill(Color.Transparent).stroke(this.faceLocked?'#F8FFFFFF':'#80FFFFFF').strokeWidth(this.faceLocked?2.5:1.3)
    Circle().width(this.ringSize+8).height(this.ringSize+8).fill(Color.Transparent).stroke(this.faceLocked?'#70DFFFEF':'#D9FFFFFF').strokeWidth(1.5).strokeDashArray(this.faceLocked?[8,64]:[24,16]).rotate({angle:this.orbit})
    if(this.faceLocked){Circle().width(3).height(3).fill('#F8FFFFFF')}
    if(!this.ready){LoadingProgress().width(36).height(36).color(Color.White)}
   }.id('camera-anchor').width(this.ringSize+12).height(this.ringSize+12).scale({x:Math.cos(this.faceYaw*Math.PI/180),y:1}).rotate({angle:this.faceRoll}).translate({x:this.trackX,y:this.trackY}).hitTestBehavior(HitTestMode.None)
   if(this.ready&&!this.faceLocked){
    CaptureMoveHint({motion:this.motion,language:this.language,hintSize:Math.min(360,this.viewportWidth-48,this.viewportHeight*.62)})
     .transition({opacity:0,scale:{x:.88,y:.88}})
   }
   Column(){
    Row(){this.icon('‹',this.tr('返回','Back'),()=>this.onClose());Blank();Text(this.tr('拍摄面容','Capture yourself')).fontSize(17).fontColor(Color.White);Blank();this.icon('ⓘ',this.tr('拍摄说明','Capture info'),()=>{this.getUIContext().animateTo({duration:this.motion?220:0},()=>this.info=!this.info);})}.width('100%').padding(24)
    Blank()
    Text(this.faceLocked?this.tr('正在跟随你的面容','Following your face'):this.faceSeen?this.tr('看见你了，保持自然','Face detected. Stay relaxed.'):this.tr('正在寻找你，不用刻意对准','Finding you — no need to line up exactly'))
     .id('camera-guide').fontSize(17).fontColor(Color.White).textShadow({radius:6,color:'#AA000000',offsetX:0,offsetY:1})
    Text(this.outcome()).id('camera-capture-outcome').fontSize(13).fontColor('#EFFFFFFF').textShadow({radius:2,color:'#90000000',offsetY:1}).margin({top:8,bottom:18}).onClick(()=>{this.info=true;})
    this.icon('↻',this.tr('切换镜头','Switch camera'),()=>{if(!this.busy){this.front=!this.front;this.open();}})
    if(this.ready){Text(this.tr('画面只在本机处理','Processed on this device')).id('camera-preview-active').fontSize(12).fontColor('#EFFFFFFF').textShadow({radius:2,color:'#90000000',offsetY:1}).margin({top:12,bottom:28})}
    else{Text(this.tr('正在连接相机…','Connecting camera…')).fontSize(12).fontColor('#D6FFFFFF').margin({bottom:28})}
   }.width('100%').height('100%')
   if(this.info||(!this.ready&&!this.busy)){
    Column({space:14}){
     Text(this.tr('拍摄说明','Capture info')).fontSize(20).fontColor(Color.White)
     Text(this.tr('保持表情自然，让另一人缓慢移动镜头，留下多个视角。','Keep a relaxed expression while someone slowly moves the camera around you.')).fontSize(15).fontColor('#EEFFFFFF')
     Text(this.tr('进入后会自动寻找面容；稳定移动后，小圈会跟随鼻尖。','Tracking starts on entry. After steady motion, the small ring follows your nose.')).fontSize(13).fontColor('#DDFFFFFF')
     Text(this.tr('当前仅预览跟随，不会录制视频或生成个人3D。','This is a tracking preview. No video or personal 3D is created.')).fontSize(13).fontColor('#DDFFFFFF')
     if(this.captureIssue){Text(this.captureIssue).id('camera-reconstruction-issue').fontSize(12).fontColor('#DDFFFFFF')}
     Text(this.detection?this.tr('本机检测面容并跟随鼻尖，不上传画面','Face detection and nose tracking stay on this device'):this.tr('当前设备未提供人脸检测，圆环为对齐引导','Face detection unavailable; the ring is an alignment guide')).fontSize(13).fontColor('#DDFFFFFF')
     Text(this.status).id('camera-status').fontSize(12).fontColor('#DDFFFFFF')
     Button(this.tr('知道了','Got it')).onClick(()=>{this.info=false;if(!this.ready&&!this.busy)this.open();}).backgroundColor('#40FFFFFF').fontColor(Color.White)
    }.padding(24).width(Math.min(this.viewportWidth-48,400)).backgroundColor('#F0303442').borderRadius(28).border({width:1,color:'#50FFFFFF'}).position({x:Math.max(24,this.viewportWidth-424),y:86}).transition({opacity:0,scale:{x:.85,y:.85,centerX:'100%',centerY:'0%'}})
   }
  }.id('camera-fullscreen').width('100%').height('100%').backgroundColor('#151822').clip(true)
   .onAreaChange((_old:Area,area:Area)=>{this.viewportWidth=Number(area.width);this.viewportHeight=Number(area.height);this.capture.updateRotation();})
 }
}

import { LocalFaceGuide } from '../services/LocalFaceGuide';
import { common } from '@kit.AbilityKit';
import { CameraCaptureSession } from '../services/CameraCaptureSession';
import { CaptureMotionGuide } from '../services/CaptureMotionGuide';
import { CaptureMoveHint } from './CaptureMoveHint';
import { ReconstructionTransportClient } from '../services/ReconstructionTransportClient';
import { fileIo as fs } from '@kit.CoreFileKit';
import { FaceAnchor } from '../services/FaceAnchorTracker';
import { previewGeometry,previewPoint } from '../services/CameraPreviewTransform';
import { ViewCoverageGuide } from '../services/ViewCoverageGuide';
import { CaptureViewCoverage } from './CaptureViewCoverage';
import { faceParticle } from '../services/FaceParticleField';

@Component
export struct CameraCaptureView {
 @Prop motion:boolean=true;
 @Prop language:string='zh';
 @Prop backendAddress:string='http://127.0.0.1:8787';
 @Prop backendToken:string='';
 @State status:string='';
 @State ready:boolean=false;
 @State busy:boolean=true;
 @State front:boolean=true;
 @State info:boolean=false;
 @State faceSeen:boolean=false;
 @State faceLocked:boolean=false;
 @State detection:boolean=false;
 @State recording:boolean=false;
 @State clipSaved:boolean=false;
 @State orbit:number=0;
 @State trackX:number=0;
 @State trackY:number=-24;
 @State ringSize:number=420;
 @State faceRoll:number=0;
 @State faceYaw:number=0;
 @State faceAnchorVisible:boolean=false;
 @State faceCenterX:number=0;
 @State faceCenterY:number=0;
 @State faceRadiusX:number=90;
 @State faceRadiusY:number=120;
 @State featureX:number[]=[];
 @State featureY:number[]=[];
 @State coverageFlags:boolean[]=[false,false,false,false,false,false,false,false,false,false,false];
 @State coverageActive:number=-1;
 @State coverageCount:number=0;
 @State coverageHint:number=5;
 @State coverageAngle:number=0;
 @State coverageExpanded:boolean=false;
 @State mirrorOverlay:boolean=true;
 @State reconstructionState:string='checking';
 @State transferStatus:string='';
 private localGuide:LocalFaceGuide=new LocalFaceGuide();
 private motionGuide:CaptureMotionGuide=new CaptureMotionGuide();
 private coverage:ViewCoverageGuide=new ViewCoverageGuide();
 private rawWidth:number=1920;private rawHeight:number=1080;private cameraRotation:number=0;
 private lensOrientation:number=0;private displayRotation:number=0;private actualFront:boolean=true;
 @State captureIssue:string='';
 @State viewportWidth:number=800;
 @State viewportHeight:number=600;
 @State streamRatio:number=16/9;
 @StorageLink('selfForeground') @Watch('visibilityChanged') foreground:boolean=true;
 onClose:()=>void=()=>{};
 onCapture:(name:string)=>void=()=>{};
 private controller:XComponentController=new XComponentController();
 private capture:CameraCaptureSession=new CameraCaptureSession();
 private faceTimer:number=-1;
 private coverageTimer:number=-1;
 private coverageMilestoneSeen:boolean=false;
 private lastClipPath:string='';
 private epoch:number=0;
 private surfaceReady:boolean=false;
 private expired:boolean=false;
 private tr(zh:string,en:string):string{return this.language==='en'?en:zh;}
 private previewWidth():number{return Math.max(this.viewportWidth,this.viewportHeight*this.streamRatio);}
 private previewHeight():number{return Math.max(this.viewportHeight,this.viewportWidth/this.streamRatio);}
 private ring():number{return Math.min(this.viewportWidth*.82,this.viewportHeight*.72,560);}
 private showCoverage(duration:number):void{
  clearTimeout(this.coverageTimer);
  this.getUIContext().animateTo({duration:this.motion?280:0,curve:Curve.EaseOut},()=>{this.coverageExpanded=true;});
  this.coverageTimer=setTimeout(()=>{
   this.coverageTimer=-1;
   if(!this.expired)this.getUIContext().animateTo({duration:this.motion?350:0,curve:Curve.EaseInOut},()=>{this.coverageExpanded=false;});
  },duration);
 }
 private updateCoverage(face:FaceAnchor|undefined):void{
  const result=this.coverage.update(face,this.recording,this.actualFront&&this.mirrorOverlay);
  if(this.recording&&!this.coverageMilestoneSeen&&result.count>=5){this.coverageMilestoneSeen=true;this.showCoverage(1700);}
  if(result.covered.some((value:boolean,index:number)=>value!==this.coverageFlags[index]))this.coverageFlags=result.covered;
  this.coverageActive=result.active;this.coverageCount=result.count;this.coverageHint=result.hint;this.coverageAngle=result.angle;
 }
 private seek():void{this.motionGuide.reset();this.faceSeen=false;this.faceAnchorVisible=false;this.featureX=[];this.featureY=[];this.getUIContext().animateTo({duration:this.motion?420:0,curve:Curve.EaseOut},()=>{this.faceLocked=false;this.ringSize=this.ring();this.trackX=0;this.trackY=0;this.faceRoll=0;this.faceYaw=0;});}
 private async checkReconstruction(epoch:number):Promise<void>{
  this.reconstructionState='checking';this.captureIssue='';
  try{
   const transport=new ReconstructionTransportClient();transport.endpoint=this.backendAddress;transport.token=this.backendToken;
   const capability=await transport.probe();
   if(this.expired||epoch!==this.epoch)return;
   const roundtrip=await transport.echo();
   if(this.expired||epoch!==this.epoch)return;
   this.reconstructionState=roundtrip&&capability.engine==='ready'?'connected':roundtrip?'preparing':'unavailable';
   this.captureIssue=roundtrip&&capability.engine!=='ready'?this.tr('个人建模尚未就绪，当前可以检查取景。','Personal modeling is being prepared; you can check the framing.'):roundtrip?'':this.tr('连接不稳定，请稍后重试。','The connection is unstable. Please try again.');
   console.info('SELF_RECON_USB_HTTP '+JSON.stringify({protocol:capability.protocol,binaryRoundTrip:roundtrip,engine:capability.engine}));
  }catch(_){if(!this.expired&&epoch===this.epoch){this.reconstructionState='unavailable';this.captureIssue=this.tr('暂时无法确认建模能力，请稍后重试。','Modeling capability could not be checked. Please try again.');}}
 }
 private outcome():string{
  if(this.recording)return this.tr('正在记录面容的不同视角…','Capturing different views of your face…');
  if(this.transferStatus)return this.transferStatus;
  if(this.clipSaved)return this.tr('拍摄片段已保存 · 个人建模尚未完成','Capture saved · Personal modeling is not complete');
  if(this.reconstructionState==='checking')return this.tr('正在检查建模能力…','Checking modeling support…');
  if(this.reconstructionState==='preparing')return this.tr('取景已就绪 · 个人建模仍在准备','Framing is ready · Personal modeling is being prepared');
  return this.reconstructionState==='unavailable'?this.tr('暂时无法连接建模服务 · 可继续预览','Modeling service unavailable · Preview continues'):this.tr('建模服务已就绪','Modeling service is ready');
 }
 private async toggleCapture():Promise<void>{
  if(this.busy||!this.ready||!this.capture.canRecord)return;
  this.busy=true;
  try{
   if(this.recording){
    this.lastClipPath=await this.capture.stop();this.recording=false;this.clipSaved=true;this.updateCoverage(undefined);
    console.info('SELF_CAMERA_CAPTURE_COMPLETED '+JSON.stringify({videoSaved:true,personal3D:false}));
    const name=this.lastClipPath.substring(this.lastClipPath.lastIndexOf('/')+1);
    this.onCapture(name);
    this.onClose();
   }else{
    await this.capture.start();this.clipSaved=false;this.recording=true;
    this.coverage.reset();this.coverageMilestoneSeen=false;this.updateCoverage(undefined);this.showCoverage(2300);
    console.info('SELF_CAMERA_CAPTURE_STARTED');
   }
  }catch(e){this.status=(e as Error).message;this.info=true;this.recording=false;}
  finally{this.busy=false;}
 }
 private async leave():Promise<void>{
  if(this.recording){this.captureIssue=this.tr('拍摄还在继续。轻触下方方形按钮，结束后会回到星空。','Capture is still running. Tap the square button below to finish.');this.info=true;return;}
  this.onClose();
 }
 private async discardLastClip():Promise<void>{
  if(!this.lastClipPath)return;
  try{
   if(fs.accessSync(this.lastClipPath))fs.unlinkSync(this.lastClipPath);
   if(fs.accessSync(this.lastClipPath+'.json'))fs.unlinkSync(this.lastClipPath+'.json');
   this.lastClipPath='';this.clipSaved=false;
   console.info('SELF_CAMERA_CAPTURE_DISCARDED');
   await this.open();
  }catch(e){this.status=this.tr('无法删除这段拍摄，请稍后重试。','Could not delete this capture. Please try again.');}
 }
 private async open():Promise<void>{
  const epoch=++this.epoch;this.busy=true;this.ready=false;this.detection=false;this.info=false;this.recording=false;this.clipSaved=false;this.transferStatus='';clearTimeout(this.coverageTimer);this.coverageTimer=-1;this.coverageExpanded=false;clearTimeout(this.faceTimer);this.faceTimer=-1;this.seek();this.checkReconstruction(epoch);
  await this.localGuide.stop();await this.capture.dispose();if(this.expired||!this.foreground||epoch!==this.epoch)return;
  const capture=new CameraCaptureSession();this.capture=capture;this.localGuide=new LocalFaceGuide();
  capture.onFrame=(frame,rotation,format)=>this.localGuide.consume(frame,rotation,format);
  capture.onPreview=()=>{if(!this.expired&&epoch===this.epoch)this.ready=true;};
  capture.onGeometry=(w:number,h:number,rotation:number,front:boolean,lens:number,displayDegrees:number)=>{
   if(epoch!==this.epoch)return;
   const changed=this.rawWidth!==w||this.rawHeight!==h||this.cameraRotation!==rotation||this.actualFront!==front;
   const directionChanged=this.cameraRotation!==rotation;
   const frontChanged=this.actualFront!==front;
   this.rawWidth=w;this.rawHeight=h;this.cameraRotation=rotation;this.actualFront=front;
   this.lensOrientation=lens;this.displayRotation=displayDegrees;
   if(frontChanged)this.mirrorOverlay=front;
   this.streamRatio=rotation%180===0?w/h:h/w;
   if(changed){
    this.seek();
    if(directionChanged&&this.recording){this.captureIssue=this.tr('方向变了，请尽量保持现在的方向；拍摄会继续，直到你轻触结束。','Orientation changed. Keep this direction steady; capture continues until you stop it.');}
    console.info('SELF_CAMERA_COORDINATES '+JSON.stringify({rawWidth:w,rawHeight:h,previewRotation:rotation,lensOrientation:lens,displayRotation:displayDegrees,front,mirrored:this.mirrorOverlay,viewportWidth:this.viewportWidth,viewportHeight:this.viewportHeight}));
   }
  };
  capture.onError=(message:string)=>{if(epoch!==this.epoch)return;this.ready=false;this.recording=false;this.status=message;this.info=true;capture.dispose();};
  try{const context=this.getUIContext().getHostContext() as common.UIAbilityContext;
   const label=await capture.open(context,this.controller.getXComponentSurfaceId(),this.front,true);
   if(!this.expired&&epoch===this.epoch){
    this.status=label;
    this.localGuide.onAvailable=(ok:boolean)=>{if(epoch===this.epoch)this.detection=ok;};
    this.localGuide.onError=(message:string)=>{if(epoch===this.epoch){this.status=message;this.detection=false;this.info=true;this.seek();}};
    this.localGuide.onResult=(face)=>{
     if(epoch!==this.epoch||this.expired)return;
     const geometry=previewGeometry(this.rawWidth,this.rawHeight,this.cameraRotation,this.viewportWidth,this.viewportHeight,this.actualFront&&this.mirrorOverlay);
     const point=previewPoint(face?face.x:.5,face?face.y:.5,geometry);
     const x=point.x,y=point.y;
     const visible=!!face&&Math.abs(x)<this.viewportWidth/2-16&&Math.abs(y)<this.viewportHeight/2-16;
     if(!visible){this.motionGuide.update(undefined,Date.now());this.updateCoverage(undefined);if(this.faceTimer<0)this.faceTimer=setTimeout(()=>{this.faceTimer=-1;this.seek();},750);return;}
     clearTimeout(this.faceTimer);this.faceTimer=-1;
     if(!face!.locked&&this.faceLocked)this.seek();
     // Guidance and tracking begin on entry. No shutter or recording timer can unlock them.
     const confirmedMotion=this.motionGuide.update(face,Date.now());
     const following=confirmedMotion&&face!.locked;
     const acquiring=!this.faceLocked&&following;
     this.updateCoverage(face);
     this.faceSeen=true;
     this.faceAnchorVisible=face!.locked;
     this.faceCenterX=x;this.faceCenterY=y;
     this.faceRadiusX=Math.min(this.viewportWidth*.35,face!.width*geometry.contentWidth*.43);
     this.faceRadiusY=Math.min(this.viewportHeight*.40,face!.height*geometry.contentHeight*.43);
     if(face!.observed&&face!.landmarks){
      const features=face!.landmarks!.map((p)=>previewPoint(p.x,p.y,geometry));
      this.featureX=features.map((p)=>p.x);this.featureY=features.map((p)=>p.y);
     }
     if(acquiring)console.info('SELF_CAMERA_GUIDANCE_FOLLOWING '+JSON.stringify({source:'tracked-relative-face-motion',reconstructionPose:false}));
     const ring=Math.max(24,Math.min(38,face!.width*geometry.contentWidth*.16));
     if(acquiring)this.getUIContext().animateTo({duration:this.motion?430:0,curve:Curve.EaseOut},()=>{
      this.faceLocked=true;this.ringSize=ring;this.trackX=x;this.trackY=y;this.faceRoll=(this.actualFront&&this.mirrorOverlay?-1:1)*face!.roll;this.faceYaw=face!.yaw;
     });
     else if(following){this.faceLocked=true;this.trackX=x;this.trackY=y;this.faceRoll=(this.actualFront&&this.mirrorOverlay?-1:1)*face!.roll;this.faceYaw=face!.yaw;}
    };

   }
  }catch(e){if(!this.expired&&epoch===this.epoch)this.status=(e as Error).message;}
  finally{if(epoch===this.epoch)this.busy=false;}
 }
 private visibilityChanged():void{
  if(!this.foreground){this.epoch++;this.ready=false;this.recording=false;clearTimeout(this.coverageTimer);this.coverageTimer=-1;clearTimeout(this.faceTimer);this.faceTimer=-1;this.localGuide.stop();this.capture.dispose();}
  else if(this.surfaceReady&&!this.expired)this.open();
 }
 aboutToDisappear():void{this.expired=true;this.epoch++;clearTimeout(this.coverageTimer);clearTimeout(this.faceTimer);this.localGuide.stop();this.capture.dispose();}
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
   }.id('camera-anchor').width(this.ringSize+12).height(this.ringSize+12).rotate({angle:this.faceRoll}).translate({x:this.trackX,y:this.trackY})
    .animation({duration:this.motion?95:0,curve:Curve.EaseOut}).hitTestBehavior(HitTestMode.None)
   if(this.faceAnchorVisible){
    Stack(){
     ForEach([0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35],(index:number)=>{
      Circle().width(faceParticle(index,this.faceYaw).size).height(faceParticle(index,this.faceYaw).size)
       .fill(index%3===0?'#C6FFF1':'#E8D9FF').opacity(faceParticle(index,this.faceYaw).opacity)
       .translate({x:faceParticle(index,this.faceYaw).x*this.faceRadiusX,y:faceParticle(index,this.faceYaw).y*this.faceRadiusY})
     },(index:number)=>index.toString())
    }.width(1).height(1).translate({x:this.faceCenterX,y:this.faceCenterY})
     .animation({duration:this.motion?95:0,curve:Curve.EaseOut}).hitTestBehavior(HitTestMode.None)
    ForEach([0,1,2,3,4],(index:number)=>{
     if(this.featureX.length===5&&this.featureY.length===5){
      Circle().width(4).height(4).fill('#D9FFF6').opacity(.55)
       .translate({x:this.featureX[index],y:this.featureY[index]})
     }
    },(index:number)=>index.toString())
   }
   if(this.ready&&!this.faceLocked){
    CaptureMoveHint({motion:this.motion,language:this.language,hintSize:Math.min(360,this.viewportWidth-48,this.viewportHeight*.62)})
     .transition({opacity:0,scale:{x:.88,y:.88}})
   }
   Column(){
    Row(){this.icon('‹',this.tr('返回','Back'),()=>{this.leave();});Blank();Text(this.tr('循光看见自己','Follow your light')).fontSize(17).fontColor(Color.White);Blank();this.icon('ⓘ',this.tr('拍摄说明','Capture info'),()=>{this.getUIContext().animateTo({duration:this.motion?220:0},()=>this.info=!this.info);})}.width('100%').padding({left:24,right:24,top:38,bottom:24})
    Blank()
    if(this.faceLocked||this.recording||this.clipSaved){
     CaptureViewCoverage({covered:this.coverageFlags,active:this.coverageActive,count:this.coverageCount,hint:this.coverageHint,angle:this.coverageAngle,language:this.language,expanded:this.coverageExpanded,availableWidth:this.viewportWidth})
      .margin({bottom:10}).transition({opacity:0,scale:{x:.92,y:.92}})
    }
    Text(this.faceLocked?this.tr('光点正轻轻跟着你','The light is following you'):this.faceSeen?this.tr('看见你了，保持自然','I see you. Stay relaxed.'):this.tr('让光慢慢找到你','Let the light find you'))
     .id('camera-guide').fontSize(17).fontColor(Color.White).textShadow({radius:6,color:'#AA000000',offsetX:0,offsetY:1})
    if(this.recording){Text(this.tr('从正面缓缓走向两侧，留下更多真实的你','Move gently from the front to each side')).id('camera-capture-outcome').fontSize(13).fontColor('#EFFFFFFF').textShadow({radius:2,color:'#90000000',offsetY:1}).margin({top:8,bottom:18})}
    Row({space:30}){
     this.icon('↻',this.tr('切换镜头','Switch camera'),()=>{if(!this.busy&&!this.recording){this.front=!this.front;this.open();}})
     Button(){
      Stack(){
       Circle().width(76).height(76).fill('#27FFFFFF').stroke('#F5FFFFFF').strokeWidth(3)
       if(this.recording){Rect().width(26).height(26).radius(6).fill('#FF788D')}
       else{Circle().width(54).height(54).fill('#F9FFFFFF')}
      }.width(82).height(82)
     }.id('camera-shutter').width(92).height(92).backgroundColor(Color.Transparent).enabled(this.ready&&!this.busy&&!this.clipSaved&&this.capture.canRecord)
      .stateStyles({pressed:{.scale({x:.88,y:.88})},normal:{.scale({x:1,y:1})}}).animation({duration:this.motion?160:0,curve:Curve.EaseOut})
      .accessibilityText(this.clipSaved?this.tr('拍摄已保存','Capture saved'):this.recording?this.tr('结束拍摄','Stop capture'):this.tr('开始拍摄','Start capture')).onClick(()=>this.toggleCapture())
     this.icon('ⓘ',this.tr('拍摄说明','Capture info'),()=>{this.info=true;})
    }
    Text(this.recording?this.tr('再次轻触，结束拍摄','Tap again to finish'):this.tr('轻触拍摄，慢慢移动镜头','Tap to capture, then move slowly')).fontSize(12).fontColor('#EFFFFFFF').margin({top:4})
    if(this.ready){Text(this.tr('拍摄仅用于这次建模','This capture is used only for this model')).id('camera-preview-active').fontSize(12).fontColor('#EFFFFFFF').textShadow({radius:2,color:'#90000000',offsetY:1}).margin({top:12,bottom:28})}
    else{Text(this.tr('正在连接相机…','Connecting camera…')).fontSize(12).fontColor('#D6FFFFFF').margin({bottom:28})}
   }.width('100%').height('100%')
   if(this.info||(!this.ready&&!this.busy)){
    Column({space:14}){
     Text(this.tr('拍摄说明','Capture info')).fontSize(20).fontColor(Color.White)
     Text(this.tr('保持表情自然，让另一人缓慢移动镜头，留下多个视角。','Keep a relaxed expression while someone slowly moves the camera around you.')).fontSize(15).fontColor('#EEFFFFFF')
     Text(this.tr('进入后会自动寻找面容；稳定移动后，小圈会跟随鼻尖。','Tracking starts on entry. After steady motion, the small ring follows your nose.')).fontSize(13).fontColor('#DDFFFFFF')
     Text(this.tr('拍摄后会提交至你连接的建模服务；原片也留在应用内。','After capture, the clip is sent to your connected modeling service and remains in the app.')).fontSize(13).fontColor('#DDFFFFFF')
     Text(this.tr('角度只是参考，不必逐个点亮；保持面容清晰即可。','The view arc is a guide, not a checklist. Keep your face clear.')).fontSize(12).fontColor('#D2FFFFFF')
     if(this.captureIssue){Text(this.captureIssue).id('camera-reconstruction-issue').fontSize(12).fontColor('#DDFFFFFF')}
     Text(this.detection?this.tr('取景时的面容跟随在设备上完成','Live face tracking runs on your device'):this.tr('当前设备未提供人脸检测，圆环为对齐引导','Face detection unavailable; the ring is an alignment guide')).fontSize(13).fontColor('#DDFFFFFF')
     Text(this.tr(this.viewportHeight>this.viewportWidth?'竖屏 · 相机方向 ':'横屏 · 相机方向 ',this.viewportHeight>this.viewportWidth?'Portrait · camera ':'Landscape · camera ')+this.lensOrientation+'° · '+this.displayRotation+'° → '+this.cameraRotation+'°').fontSize(11).fontColor('#C9FFFFFF')
     Button(this.tr('圈偏向另一侧？切换镜像','Marker on the wrong side? Flip alignment')).id('camera-mirror-correction').onClick(()=>{this.mirrorOverlay=!this.mirrorOverlay;this.seek();}).backgroundColor('#40FFFFFF').fontColor(Color.White)
     Text(this.status).id('camera-status').fontSize(12).fontColor('#DDFFFFFF')
     if(this.clipSaved){Button(this.tr('删除这段拍摄','Delete this capture')).id('camera-discard-clip').onClick(()=>this.discardLastClip()).backgroundColor('#40FFFFFF').fontColor(Color.White)}
     Button(this.tr('知道了','Got it')).onClick(()=>{this.info=false;if(!this.ready&&!this.busy)this.open();}).backgroundColor('#40FFFFFF').fontColor(Color.White)
    }.padding(24).width(Math.min(this.viewportWidth-48,400)).backgroundColor('#F0303442').borderRadius(28).border({width:1,color:'#50FFFFFF'}).position({x:Math.max(24,this.viewportWidth-424),y:86}).transition({opacity:0,scale:{x:.85,y:.85,centerX:'100%',centerY:'0%'}})
   }
  }.id('camera-fullscreen').width('100%').height('100%').backgroundColor('#080C1B').clip(true)
   .onAreaChange((_old:Area,area:Area)=>{this.viewportWidth=Number(area.width);this.viewportHeight=Number(area.height);this.capture.updateRotation();})
 }
}

import { LocalFaceGuide } from '../services/LocalFaceGuide';
import { common } from '@kit.AbilityKit';
import { CameraCaptureSession } from '../services/CameraCaptureSession';

@Component
export struct CameraCaptureView {
 @Prop motion:boolean=true;
 @Prop language:string='zh';
 @State status:string='';
 @State ready:boolean=false;
 @State recording:boolean=false;
 @State seconds:number=0;
 @State busy:boolean=true;
 @State canRecord:boolean=false;
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
 @State saved:boolean=false;
 private softwareRecording:boolean=false;
 private localGuide:LocalFaceGuide=new LocalFaceGuide();
 @State guideTravel:number=-38;
 @State viewportWidth:number=800;
 @State viewportHeight:number=600;
 @State streamRatio:number=16/9;
 @StorageLink('selfForeground') @Watch('visibilityChanged') foreground:boolean=true;
 onSaved:()=>void=()=>{};
 onClose:()=>void=()=>{};
 private controller:XComponentController=new XComponentController();
 private capture:CameraCaptureSession=new CameraCaptureSession();
 private timer:number=-1;
 private faceTimer:number=-1;
 private epoch:number=0;
 private surfaceReady:boolean=false;
 private expired:boolean=false;
 private tr(zh:string,en:string):string{return this.language==='en'?en:zh;}
 private previewWidth():number{return Math.max(this.viewportWidth,this.viewportHeight*this.streamRatio);}
 private previewHeight():number{return Math.max(this.viewportHeight,this.viewportWidth/this.streamRatio);}
 private ring():number{return Math.min(this.viewportWidth*.82,this.viewportHeight*.72,560);}
 private seek():void{this.faceSeen=false;this.faceLocked=false;this.getUIContext().animateTo({duration:this.motion?420:0,curve:Curve.EaseOut},()=>{this.ringSize=this.ring();this.trackX=0;this.trackY=-24;this.faceRoll=0;this.faceYaw=0;});}
 private async open():Promise<void>{
  const epoch=++this.epoch;this.busy=true;this.ready=false;this.canRecord=false;this.seek();
  await this.localGuide.stop();await this.capture.dispose();if(this.expired||!this.foreground||epoch!==this.epoch)return;
  const capture=new CameraCaptureSession();this.capture=capture;this.localGuide=new LocalFaceGuide();
  capture.onFrame=(frame,rotation,format)=>this.localGuide.consume(frame,rotation,format);
  capture.onPreview=()=>{if(!this.expired&&epoch===this.epoch)this.ready=true;};
  capture.onGeometry=(w:number,h:number,rotation:number)=>{if(epoch===this.epoch)this.streamRatio=rotation%180===0?w/h:h/w;};
  capture.onError=(message:string)=>{if(epoch!==this.epoch)return;this.ready=false;this.status=message;capture.dispose();};
  try{const context=this.getUIContext().getHostContext() as common.UIAbilityContext;
   const label=await capture.open(context,this.controller.getXComponentSurfaceId(),this.front);
   if(!this.expired&&epoch===this.epoch){
    this.softwareRecording=!capture.canRecord;this.status=label+(this.softwareRecording?' · 本机软件采集':'');
    this.canRecord=capture.canRecord;
    this.localGuide.onOrientationChanged=()=>{if(epoch===this.epoch&&this.recording&&!this.busy)this.record();};
    this.localGuide.onAvailable=(ok:boolean)=>{if(epoch===this.epoch){this.detection=ok;if(this.softwareRecording)this.canRecord=ok;}};
    this.localGuide.onError=(message:string)=>{if(epoch===this.epoch){this.status=message;this.info=true;if(this.softwareRecording){this.recording=false;clearInterval(this.timer);}}};
    this.localGuide.onResult=(face)=>{
     if(epoch!==this.epoch||this.expired)return;
     const x=face?(face.x-.5)*this.previewWidth():0,y=face?(face.y-.5)*this.previewHeight():0;
     const visible=!!face&&Math.abs(x)<this.viewportWidth/2-16&&Math.abs(y)<this.viewportHeight/2-16;
     if(!visible){if(this.faceTimer<0)this.faceTimer=setTimeout(()=>{this.faceTimer=-1;this.seek();},300);return;}
     clearTimeout(this.faceTimer);this.faceTimer=-1;
     const acquiring=!this.faceLocked&&face!.locked;
     this.faceSeen=true;this.faceLocked=face!.locked;
     this.getUIContext().animateTo({duration:this.motion?(acquiring?440:90):0,curve:Curve.EaseOut},()=>{
      this.ringSize=face!.locked?Math.max(22,Math.min(38,face!.width*this.previewWidth()*.16)):this.ring();
      this.trackX=face!.locked?x:0;this.trackY=face!.locked?y:-24;
      this.faceRoll=face!.locked?face!.roll:0;this.faceYaw=face!.locked?face!.yaw:0;
     });
    };

   }
  }catch(e){if(!this.expired&&epoch===this.epoch)this.status=(e as Error).message;}
  finally{if(epoch===this.epoch)this.busy=false;}
 }
 private async record():Promise<void>{
  if(this.busy)return;this.busy=true;
  try{if(this.recording){if(this.softwareRecording)await this.localGuide.stopRecording();else await this.capture.stop();this.saved=true;this.recording=false;clearInterval(this.timer);this.timer=-1;this.onSaved();await this.open();}
   else{if(this.softwareRecording)await this.localGuide.startRecording((this.getUIContext().getHostContext() as common.UIAbilityContext).filesDir);else await this.capture.start();this.saved=false;this.recording=true;this.seconds=0;this.guideTravel=-38;if(this.motion)this.getUIContext().animateTo({duration:1800,iterations:2,playMode:PlayMode.Alternate,curve:Curve.EaseInOut},()=>{this.guideTravel=38;});this.timer=setInterval(()=>{this.seconds++;if(this.seconds>=30)this.record();},1000);}
  }catch(e){this.status=(e as Error).message;this.recording=false;this.ready=false;clearInterval(this.timer);this.timer=-1;await this.localGuide.stop();await this.capture.dispose();}finally{this.busy=false;}
 }
 private visibilityChanged():void{
  if(!this.foreground){this.epoch++;this.ready=false;this.recording=false;clearInterval(this.timer);clearTimeout(this.faceTimer);this.localGuide.stop();this.capture.dispose();}
  else if(this.surfaceReady&&!this.expired)this.open();
 }
 aboutToDisappear():void{this.expired=true;this.epoch++;clearInterval(this.timer);clearTimeout(this.faceTimer);this.localGuide.stop();this.capture.dispose();}
 @Builder icon(symbol:string,label:string,action:()=>void){
  Button(symbol).id(symbol==='ⓘ'?'camera-info':symbol==='‹'?'camera-back':'camera-switch').width(48).height(48).fontSize(25).fontColor(Color.White).backgroundColor('#38FFFFFF')
   .border({width:1,color:'#55FFFFFF'}).borderRadius(24).stateStyles({pressed:{.scale({x:.90,y:.90})},normal:{.scale({x:1,y:1})}}).animation({duration:this.motion?160:0,curve:Curve.EaseOut}).accessibilityText(label).onClick(action)
 }
 build(){
  Stack(){
   XComponent({id:'self-camera-preview',type:XComponentType.SURFACE,controller:this.controller})
    .id('self-camera-preview').width(this.previewWidth()).height(this.previewHeight()).onAreaChange((_old:Area,area:Area)=>console.info('SELF_CAMERA_SURFACE '+JSON.stringify({width:Number(area.width),height:Number(area.height),aspect:this.streamRatio})))
    .onLoad(()=>{this.surfaceReady=true;this.ringSize=this.ring();this.open();if(this.motion)this.getUIContext().animateTo({duration:16000,iterations:-1,curve:Curve.Linear},()=>{this.orbit=360;});})
   Column(){Blank()}.width('100%').height('100%').linearGradient({angle:180,colors:[['#700A1018',0],['#000A1018',.3],['#000A1018',.6],['#B80A1018',1]]}).hitTestBehavior(HitTestMode.None)
   Stack(){
    Circle().width(this.ringSize).height(this.ringSize).fill(Color.Transparent).stroke(this.faceLocked?'#F8FFFFFF':'#80FFFFFF').strokeWidth(this.faceLocked?2.5:1.3)
    Circle().width(this.ringSize+8).height(this.ringSize+8).fill(Color.Transparent).stroke(this.faceLocked?'#70DFFFEF':'#D9FFFFFF').strokeWidth(1.5).strokeDashArray(this.faceLocked?[8,64]:[24,16]).rotate({angle:this.orbit})
    if(this.faceLocked){Circle().width(3).height(3).fill('#F8FFFFFF')}
    if(!this.ready){LoadingProgress().width(36).height(36).color(Color.White)}
   }.id('camera-anchor').width(this.ringSize+12).height(this.ringSize+12).scale({x:Math.cos(this.faceYaw*Math.PI/180),y:1}).rotate({angle:this.faceRoll}).translate({x:this.trackX,y:this.trackY}).hitTestBehavior(HitTestMode.None)
   if(this.recording&&this.seconds<4){
    Column({space:10}){
     Stack(){
      Column({space:4}){Circle().width(24).height(24).fill(Color.Transparent).stroke(Color.White).strokeWidth(2);Rect().width(46).height(50).radius(18).fill(Color.Transparent).stroke(Color.White).strokeWidth(2)}
      Rect().width(28).height(48).radius(5).fill('#35000000').stroke(Color.White).strokeWidth(2).translate({x:this.guideTravel,y:10}).rotate({angle:-12})
     }.width(140).height(90)
     Text(this.tr('慢慢移动镜头，看看另一侧','Move slowly around to the other side')).fontSize(14).fontColor(Color.White)
    }.padding(20).borderRadius(24).backgroundColor('#48000000').translate({y:this.viewportHeight*.16}).hitTestBehavior(HitTestMode.None).transition({opacity:0,scale:{x:.95,y:.95}})
   }
   Column(){
    Row(){this.icon('‹',this.tr('返回','Back'),()=>this.onClose());Blank();Text(this.tr('拍摄面容','Capture yourself')).fontSize(17).fontColor(Color.White);Blank();this.icon('ⓘ',this.tr('拍摄说明','Capture info'),()=>{this.getUIContext().animateTo({duration:this.motion?220:0},()=>this.info=!this.info);})}.width('100%').padding(24)
    Blank()
    Text(this.faceLocked?this.tr('正在跟随你的面容','Following your face'):this.faceSeen?this.tr('看见你了，保持自然','Face detected. Stay relaxed.'):this.tr('正在寻找你，不用刻意对准','Finding you — no need to line up exactly'))
     .id('camera-guide').fontSize(17).fontColor(Color.White).textShadow({radius:6,color:'#AA000000',offsetX:0,offsetY:1})
    Text(this.recording?this.tr('保持表情，缓慢环绕取景','Stay still while the camera moves slowly'):(this.saved?this.tr('视频已留在本机','Video saved on this device'):this.tr('从真实的你开始','Start with the real you'))).fontSize(12).fontColor('#DDFFFFFF').margin({top:8,bottom:18})
    Row({space:46}){
     this.icon('↻',this.tr('切换镜头','Switch camera'),()=>{if(!this.busy&&!this.recording){this.front=!this.front;this.open();}})
     Button(){Stack(){Circle().fill(Color.Transparent).stroke(Color.White).strokeWidth(3).width(78).height(78);Rect().width(this.recording?30:64).height(this.recording?30:64).radius(this.recording?7:32).fill(this.recording?'#EFA9AD':Color.White).animation({duration:this.motion?220:0,curve:Curve.EaseOut})}}
      .id('camera-record').width(86).height(86).backgroundColor(Color.Transparent).opacity(this.ready&&this.canRecord?1:.45).accessibilityText(this.recording?this.tr('结束并保存视频','Stop and save'):this.tr('开始录制','Start recording')).enabled(this.ready&&this.canRecord&&!this.busy).onClick(()=>this.record())
     Text(this.recording?'00:'+String(this.seconds).padStart(2,'0'):this.tr('视频','VIDEO')).width(48).fontColor(Color.White).fontSize(12)
    }.margin({bottom:12})
    if(this.ready){Text(this.canRecord?this.tr('仅本机保存 · 无声','Saved on this device · Silent'):this.tr('正在准备拍摄…','Preparing capture…')).id('camera-preview-active').fontSize(12).fontColor('#D6FFFFFF').margin({bottom:28})}
    else{Text(this.tr('正在连接相机…','Connecting camera…')).fontSize(12).fontColor('#D6FFFFFF').margin({bottom:28})}
   }.width('100%').height('100%')
   if(this.info||(!this.ready&&!this.busy)){
    Column({space:14}){
     Text(this.tr('拍摄说明','Capture info')).fontSize(20).fontColor(Color.White)
     Text(this.tr('保持表情自然，让另一人缓慢移动镜头，留下多个视角。','Keep a relaxed expression while someone slowly moves the camera around you.')).fontSize(15).fontColor('#EEFFFFFF')
     Text(this.tr('视频只留在本机；个人 3D 重建尚未接通。','Video stays on this device. Personal 3D reconstruction is not connected yet.')).fontSize(13).fontColor('#DDFFFFFF')
     Text(this.detection?this.tr('本机检测面容并跟随鼻尖，不上传画面','Face detection and nose tracking stay on this device'):this.tr('当前设备未提供人脸检测，圆环为对齐引导','Face detection unavailable; the ring is an alignment guide')).fontSize(13).fontColor('#DDFFFFFF')
     Text(this.status).id('camera-status').fontSize(12).fontColor('#DDFFFFFF')
     Button(this.tr('知道了','Got it')).onClick(()=>{this.info=false;if(!this.ready&&!this.busy)this.open();}).backgroundColor('#40FFFFFF').fontColor(Color.White)
    }.padding(24).width(Math.min(this.viewportWidth-48,400)).backgroundColor('#E6303442').backgroundBlurStyle(BlurStyle.COMPONENT_THICK).borderRadius(28).border({width:1,color:'#50FFFFFF'}).position({x:Math.max(24,this.viewportWidth-424),y:86}).transition({opacity:0,scale:{x:.85,y:.85,centerX:'100%',centerY:'0%'}})
   }
  }.id('camera-fullscreen').width('100%').height('100%').backgroundColor('#151822').clip(true)
   .onAreaChange((_old:Area,area:Area)=>{this.viewportWidth=Number(area.width);this.viewportHeight=Number(area.height);this.capture.updateRotation();})
 }
}

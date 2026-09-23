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
 private localGuide:LocalFaceGuide=new LocalFaceGuide();
 private seenFrames:number=0;
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
 private ring():number{return Math.min(this.viewportWidth*.68,this.viewportHeight*.56,390);}
 private async open():Promise<void>{
  const epoch=++this.epoch;this.busy=true;this.ready=false;this.faceSeen=false;this.faceLocked=false;
  await this.localGuide.stop();await this.capture.dispose();if(this.expired||!this.foreground||epoch!==this.epoch)return;
  const capture=new CameraCaptureSession();this.capture=capture;
  capture.onPreview=()=>{if(!this.expired&&epoch===this.epoch)this.ready=true;};
  capture.onGeometry=(w:number,h:number,rotation:number)=>{if(epoch===this.epoch)this.streamRatio=rotation%180===0?w/h:h/w;};
  capture.onFace=(face)=>{
   if(this.expired||epoch!==this.epoch)return;
   clearTimeout(this.faceTimer);this.faceSeen=!!face;this.faceLocked=face?.isLockFocusTracked===true;
   this.faceTimer=setTimeout(()=>{this.faceSeen=false;this.faceLocked=false;},700);
  };
  capture.onError=(message:string)=>{if(epoch!==this.epoch)return;this.ready=false;this.status=message;capture.dispose();};
  try{const context=this.getUIContext().getHostContext() as common.UIAbilityContext;
   const label=await capture.open(context,this.controller.getXComponentSurfaceId(),this.front);
   if(!this.expired&&epoch===this.epoch){this.status=label;this.canRecord=capture.canRecord;this.detection=capture.faceDetection;
    this.localGuide=new LocalFaceGuide();this.seenFrames=0;
    if(!capture.faceDetection){
     this.localGuide.onAvailable=(ok:boolean)=>{if(epoch===this.epoch)this.detection=ok;};
     this.localGuide.onResult=(face)=>{
      if(epoch!==this.epoch||this.expired)return;
      clearTimeout(this.faceTimer);
      const x=face?(face.x-.5)*this.previewWidth():0,y=face?(face.y-.5)*this.previewHeight():-24;
      const visible=!!face&&Math.abs(x)<this.viewportWidth/2&&Math.abs(y)<this.viewportHeight/2;
      this.faceSeen=visible;this.seenFrames=visible?this.seenFrames+1:0;this.faceLocked=this.seenFrames>=2;
      this.getUIContext().animateTo({duration:this.motion?350:0,curve:Curve.EaseOut},()=>{this.trackX=visible?Math.max(-this.viewportWidth/2+this.ring()/2,Math.min(this.viewportWidth/2-this.ring()/2,x)):0;this.trackY=visible?Math.max(-this.viewportHeight/2+this.ring()/2,Math.min(this.viewportHeight/2-this.ring()/2,y)):-24;});
      this.faceTimer=setTimeout(()=>{this.faceSeen=false;this.faceLocked=false;this.seenFrames=0;},1600);
     };
     this.localGuide.start(this.controller.getXComponentSurfaceId());
    }
   }
  }catch(e){if(!this.expired&&epoch===this.epoch)this.status=(e as Error).message;}
  finally{if(epoch===this.epoch)this.busy=false;}
 }
 private async record():Promise<void>{
  if(this.busy)return;this.busy=true;
  try{if(this.recording){await this.capture.stop();this.recording=false;clearInterval(this.timer);this.timer=-1;this.onSaved();await this.open();}
   else{await this.capture.start();this.recording=true;this.seconds=0;this.timer=setInterval(()=>{this.seconds++;if(this.seconds>=30)this.record();},1000);}
  }catch(e){this.status=(e as Error).message;this.recording=false;this.ready=false;clearInterval(this.timer);this.timer=-1;await this.capture.dispose();}finally{this.busy=false;}
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
    .onLoad(()=>{this.surfaceReady=true;this.open();if(this.motion)this.getUIContext().animateTo({duration:16000,iterations:-1,curve:Curve.Linear},()=>{this.orbit=360;});})
   Column(){Blank()}.width('100%').height('100%').linearGradient({angle:180,colors:[['#700A1018',0],['#000A1018',.3],['#000A1018',.6],['#B80A1018',1]]}).hitTestBehavior(HitTestMode.None)
   Stack(){
    Circle().width(this.ring()).height(this.ring()).fill(Color.Transparent).stroke('#55FFFFFF').strokeWidth(1)
    Circle().width(this.ring()+14).height(this.ring()+14).fill(Color.Transparent).stroke(this.faceLocked?'#ADFFE1':'#D9FFFFFF').strokeWidth(2).strokeDashArray([18,9]).rotate({angle:this.orbit})
    Column(){Circle().width(9).height(9).fill('#EEFFFFFF');Blank()}.width(this.ring()+30).height(this.ring()+30).rotate({angle:this.orbit})
    if(!this.ready){LoadingProgress().width(36).height(36).color(Color.White)}
   }.translate({x:this.trackX,y:this.trackY}).hitTestBehavior(HitTestMode.None)
   Column(){
    Row(){this.icon('‹',this.tr('返回','Back'),()=>this.onClose());Blank();Text(this.tr('拍摄面容','Capture yourself')).fontSize(17).fontColor(Color.White);Blank();this.icon('ⓘ',this.tr('拍摄说明','Capture info'),()=>{this.getUIContext().animateTo({duration:this.motion?220:0},()=>this.info=!this.info);})}.width('100%').padding(24)
    Blank()
    Text(this.faceLocked?this.tr('正在跟随你的面容','Following your face'):this.faceSeen?this.tr('看见你了，保持自然','Face detected. Stay relaxed.'):this.tr('让面容停在圆环里','Place your face inside the ring'))
     .id('camera-guide').fontSize(17).fontColor(Color.White).textShadow({radius:6,color:'#AA000000',offsetX:0,offsetY:1})
    Text(this.recording?this.tr('保持表情，缓慢环绕取景','Stay still while the camera moves slowly'):this.tr('从真实的你开始','Start with the real you')).fontSize(12).fontColor('#DDFFFFFF').margin({top:8,bottom:18})
    Row({space:46}){
     this.icon('↻',this.tr('切换镜头','Switch camera'),()=>{if(!this.busy&&!this.recording){this.front=!this.front;this.open();}})
     Button(){Stack(){Circle().fill(Color.Transparent).stroke(Color.White).strokeWidth(3).width(78).height(78);Rect().width(this.recording?30:64).height(this.recording?30:64).radius(this.recording?7:32).fill(this.recording?'#EFA9AD':Color.White).animation({duration:this.motion?220:0,curve:Curve.EaseOut})}}
      .id('camera-record').width(86).height(86).backgroundColor(Color.Transparent).opacity(this.ready&&this.canRecord?1:.45).accessibilityText(this.recording?this.tr('结束并保存视频','Stop and save'):this.tr('开始录制','Start recording')).enabled(this.ready&&this.canRecord&&!this.busy).onClick(()=>this.record())
     Text(this.recording?'00:'+String(this.seconds).padStart(2,'0'):this.tr('视频','VIDEO')).width(48).fontColor(Color.White).fontSize(12)
    }.margin({bottom:12})
    if(this.ready){Text(this.canRecord?this.tr('仅本机保存 · 无声','Saved on this device · Silent'):this.tr('当前模拟器仅支持预览','Preview only on this emulator')).id('camera-preview-active').fontSize(12).fontColor('#D6FFFFFF').margin({bottom:28})}
    else{Text(this.tr('正在连接相机…','Connecting camera…')).fontSize(12).fontColor('#D6FFFFFF').margin({bottom:28})}
   }.width('100%').height('100%')
   if(this.info||(!this.ready&&!this.busy)){
    Column({space:14}){
     Text(this.tr('拍摄说明','Capture info')).fontSize(20).fontColor(Color.White)
     Text(this.tr('保持表情自然，让另一人缓慢移动镜头，留下多个视角。','Keep a relaxed expression while someone slowly moves the camera around you.')).fontSize(15).fontColor('#EEFFFFFF')
     Text(this.tr('视频只留在本机；个人 3D 重建尚未接通。','Video stays on this device. Personal 3D reconstruction is not connected yet.')).fontSize(13).fontColor('#DDFFFFFF')
     Text(this.detection?this.tr('已连接设备的人脸检测','Device face detection connected'):this.tr('当前设备未提供人脸检测，圆环为对齐引导','Face detection unavailable; the ring is an alignment guide')).fontSize(13).fontColor('#DDFFFFFF')
     Text(this.status).id('camera-status').fontSize(12).fontColor('#DDFFFFFF')
     Button(this.tr('知道了','Got it')).onClick(()=>{this.info=false;if(!this.ready&&!this.busy)this.open();}).backgroundColor('#40FFFFFF').fontColor(Color.White)
    }.padding(24).width(Math.min(this.viewportWidth-48,400)).backgroundColor('#E6303442').backgroundBlurStyle(BlurStyle.COMPONENT_THICK).borderRadius(28).border({width:1,color:'#50FFFFFF'}).position({x:Math.max(24,this.viewportWidth-424),y:86}).transition({opacity:0,scale:{x:.85,y:.85,centerX:'100%',centerY:'0%'}})
   }
  }.id('camera-fullscreen').width('100%').height('100%').backgroundColor('#151822').clip(true)
   .onAreaChange((_old:Area,area:Area)=>{this.viewportWidth=Number(area.width);this.viewportHeight=Number(area.height);this.capture.updateRotation();})
 }
}

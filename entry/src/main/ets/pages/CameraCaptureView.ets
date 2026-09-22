import { common } from '@kit.AbilityKit';
import { CameraCaptureSession } from '../services/CameraCaptureSession';
@Component
export struct CameraCaptureView {
 @State status:string='准备连接摄像头…';
 @State ready:boolean=false;
 @State recording:boolean=false;
 @State saved:boolean=false;
 @State seconds:number=0;
 @State busy:boolean=false;
 @State canRecord:boolean=false;
 @StorageLink('selfForeground') @Watch('visibilityChanged') foreground:boolean=true;
 onSaved:()=>void=()=>{};
 private controller:XComponentController=new XComponentController();
 private capture:CameraCaptureSession=new CameraCaptureSession();
 private timer:number=-1;
 private expired:boolean=false;
 private async open():Promise<void>{
  this.capture.onPreview=()=>{if(!this.expired)this.ready=true;};
  this.capture.onError=(message:string)=>{this.ready=false;this.status=message;this.capture.dispose();};
  try{const context=this.getUIContext().getHostContext() as common.UIAbilityContext;const label=await this.capture.open(context,this.controller.getXComponentSurfaceId(),true);if(!this.expired){this.status=label;this.canRecord=this.capture.canRecord;}}catch(e){if(!this.expired)this.status=(e as Error).message;}
 }
 private async record():Promise<void>{
  if(this.busy)return;this.busy=true;
  try{if(this.recording){await this.capture.stop();this.recording=false;this.saved=true;this.ready=false;clearInterval(this.timer);this.timer=-1;this.status='视频已私密保存 · 尚未生成个人3D';await this.capture.dispose();this.onSaved();}
   else{await this.capture.start();this.recording=true;this.seconds=0;this.timer=setInterval(()=>{this.seconds++;if(this.seconds>=30)this.record();},1000);}
  }catch(e){this.status=(e as Error).message;this.recording=false;this.ready=false;clearInterval(this.timer);this.timer=-1;await this.capture.dispose();}finally{this.busy=false;}
 }
 private visibilityChanged():void{if(!this.foreground){this.ready=false;this.recording=false;clearInterval(this.timer);this.timer=-1;this.expired=true;this.capture.dispose();this.status='已暂停相机，重新打开拍摄即可继续';}}
 aboutToDisappear():void{this.expired=true;clearInterval(this.timer);this.capture.dispose();}
 build(){Column({space:12}){
  Stack(){
   XComponent({id:'self-camera-preview',type:XComponentType.SURFACE,controller:this.controller}).width('100%').height('100%').onLoad(()=>this.open())
   if(!this.ready){Text(this.saved?'已保存视频':'等待摄像头画面').fontSize(15).fontColor('#FFFFFF').backgroundColor('#88000000').padding(12).borderRadius(16)}
   if(this.recording){Text('● '+this.seconds+' 秒').fontColor('#FFFFFF').backgroundColor('#A0693655').padding(12).borderRadius(20).position({x:12,y:12})}
  }.width('100%').height(280).backgroundColor('#342D41').borderRadius(24).clip(true)
  Text(this.status).id('camera-status').fontSize(14).fontColor('#65556F')
  if(this.ready){Text('相机预览已连接').id('camera-preview-active').fontSize(12).fontColor('#5A7467')}
  Button(this.recording?'结束并保存视频':'开始录制').id('camera-record').enabled(this.ready&&this.canRecord&&!this.saved&&!this.busy).onClick(()=>this.record()).backgroundColor('#7C698F').fontColor('#FFFFFF')
  Text('只在本机录制，无声音、不上传。请保持表情稳定，由另一人缓慢移动镜头，避免只转动头部。').fontSize(13).fontColor('#7D7087')
 }.width('100%')}
}

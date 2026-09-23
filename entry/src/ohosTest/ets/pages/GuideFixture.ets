import { CaptureMoveHint } from '../../../main/ets/pages/CaptureMoveHint';
import { common } from '@kit.AbilityKit';
import { fileIo as fs } from '@kit.CoreFileKit';
import { image } from '@kit.ImageKit';
interface GuideReport {recordedAt:number;done:boolean;error:string;cameraPixels:boolean;}
@Entry
@ComponentV2
struct GuideFixture {
 private stopped:boolean=false;
 aboutToAppear():void{this.capture();}
 aboutToDisappear():void{this.stopped=true;}
 private async save(id:string,name:string):Promise<void>{
  const pixel=await this.getUIContext().getComponentSnapshot().get(id);
  const packer=image.createImagePacker();
  try{
   const data=await packer.packing(pixel,{format:'image/png',quality:100});
   const context=this.getUIContext().getHostContext() as common.UIAbilityContext;
   const f=fs.openSync(context.filesDir+'/'+name,fs.OpenMode.CREATE|fs.OpenMode.READ_WRITE|fs.OpenMode.TRUNC);
   try{fs.writeSync(f.fd,data);}finally{fs.closeSync(f);}
  }finally{await packer.release();await pixel.release();}
 }
 private async capture():Promise<void>{
  const report:GuideReport={recordedAt:Date.now(),done:false,error:'',cameraPixels:false};
  try{
   await new Promise<void>((resolve:()=>void)=>setTimeout(resolve,600));if(this.stopped)return;
   await this.save('camera-motion-hint','camera-guide-transparent-a.png');
   await this.save('guide-fixture','camera-guide-public-scene.png');
   await new Promise<void>((resolve:()=>void)=>setTimeout(resolve,1000));if(this.stopped)return;
   await this.save('camera-motion-hint','camera-guide-transparent-b.png');
   report.done=true;
  }catch(e){report.error=String(e);}
  const context=this.getUIContext().getHostContext() as common.UIAbilityContext;
  const f=fs.openSync(context.filesDir+'/camera-guide-artwork.json',fs.OpenMode.CREATE|fs.OpenMode.READ_WRITE|fs.OpenMode.TRUNC);
  try{fs.writeSync(f.fd,JSON.stringify(report));}finally{fs.closeSync(f);}
 }
 build(){
  Stack(){
   Image($rawfile('native-fixtures/public-scan-face.png')).width('100%').height('100%').objectFit(ImageFit.Contain)
   CaptureMoveHint({motion:true,language:'zh',hintSize:360})
   Text('测试素材 · 非真人采集').fontSize(12).fontColor(Color.White).align(Alignment.TopStart).margin(24)
  }.id('guide-fixture').width('100%').height('100%').backgroundColor('#526171')
 }
}

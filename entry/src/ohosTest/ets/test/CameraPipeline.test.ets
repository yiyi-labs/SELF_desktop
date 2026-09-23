import { describe,it,expect } from '@ohos/hypium';
import { image } from '@kit.ImageKit';
import { fileIo as fs } from '@kit.CoreFileKit';
import { abilityDelegatorRegistry } from '@kit.TestKit';
import native from 'libself_native.so';
import { DetectedFace,FaceAnchorTracker } from '../../../main/ets/services/FaceAnchorTracker';
interface Request {op:string;width?:number;height?:number;timestamp?:number;detect?:boolean;record?:boolean;fd?:number;}
interface Detection {faces:DetectedFace[];processingMs:number;}
interface Stats {frames:number;width:number;height:number;durationMs:number;fps:number;}
export default function cameraPipelineSuite(){
 describe('SELFNativeCameraPipeline',()=>{
  it('realNativeFaceDetectionAndSoftwareMp4',0,async()=>{
   const app=abilityDelegatorRegistry.getAbilityDelegator();const context=(await app.getCurrentTopAbility()).context;
   const bytes=await context.resourceManager.getRawFileContent('native-fixtures/public-scan-face.png');
   const source=image.createImageSource(bytes.buffer as ArrayBuffer);const pixel=await source.createPixelMap({desiredPixelFormat:image.PixelMapFormat.RGBA_8888});
   const rgba=new ArrayBuffer(384*512*4);await pixel.readPixelsToBuffer(rgba);await pixel.release();await source.release();
   const check:Request={op:'frame',width:384,height:512,timestamp:1000,detect:true,record:false};
   const detected=JSON.parse((await native.camera(JSON.stringify(check),rgba)).json) as Detection;
   console.info('SELF_CAMERA_FIXTURE_DETECTION '+JSON.stringify(detected));expect(detected.faces.length).assertEqual(1);
   const nose=detected.faces[0].landmarks[2];expect(nose.x>.35&&nose.x<.65&&nose.y>.25&&nose.y<.6).assertTrue();
   const blank=new Uint8Array(384*512*4);blank.fill(128);
   const none=JSON.parse((await native.camera(JSON.stringify(check),blank.buffer as ArrayBuffer)).json) as Detection;expect(none.faces.length).assertEqual(0);
   const path=context.filesDir+'/camera-codec-public-test.mp4';const file=fs.openSync(path,fs.OpenMode.CREATE|fs.OpenMode.READ_WRITE|fs.OpenMode.TRUNC);
   try{
    const start:Request={op:'start',fd:file.fd,width:384,height:512};await native.camera(JSON.stringify(start));
    for(let i=0;i<12;i++){const frame:Request={op:'frame',width:384,height:512,timestamp:1000+i*150,record:true,detect:false};await native.camera(JSON.stringify(frame),rgba);}
    const stop:Request={op:'stop',timestamp:2800};const stats=JSON.parse((await native.camera(JSON.stringify(stop))).json) as Stats;
    expect(stats.frames).assertEqual(12);expect(stats.durationMs).assertEqual(1800);expect(fs.statSync(path).size>1024).assertTrue();
    console.info('SELF_CAMERA_CODEC_FIXTURE '+JSON.stringify(stats));
   }finally{await native.camera('{"op":"cancel"}');fs.closeSync(file);}
  });
  it('anchorAcquisitionLossAndMultipleFaces',0,()=>{
   const face:DetectedFace={confidence:.95,x:.3,y:.2,width:.4,height:.5,landmarks:[{x:.4,y:.35},{x:.6,y:.35},{x:.5,y:.45},{x:.43,y:.56},{x:.57,y:.56}]};
   const tracker=new FaceAnchorTracker();expect(tracker.update([face],1000,1)?.locked).assertFalse();tracker.update([face],1100,1);expect(tracker.update([face],1200,1)?.locked).assertTrue();
   face.landmarks[2].x=.54;const moved=tracker.update([face],1300,1);expect(moved!.x>.5&&moved!.x<=.54).assertTrue();
   expect(tracker.update([],1800,1)===undefined).assertTrue();
   expect(tracker.update([face,face],1900,1)===undefined).assertTrue();
   expect(tracker.update([face],2000,1)?.locked).assertFalse();
  });
 });
}

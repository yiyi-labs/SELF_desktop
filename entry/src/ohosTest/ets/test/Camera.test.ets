import { describe,it,expect } from '@ohos/hypium';
import { Driver,ON } from '@ohos.UiTest';
import { abilityDelegatorRegistry } from '@kit.TestKit';
import { CaptureService } from '../../../main/ets/services/CaptureService';
import { fileIo as fs } from '@kit.CoreFileKit';

export default function cameraSuite(){
 describe('SELFNativeCamera',()=>{
  it('nativePreviewAndPrivateSilentVideo',0,async()=>{
   const app=abilityDelegatorRegistry.getAbilityDelegator();await app.startAbility({bundleName:'com.self.mirror',abilityName:'EntryAbility'});
   const driver=Driver.create();await driver.delayMs(1800);const context=(await app.getCurrentTopAbility()).context;
   const capture=new CaptureService(context),before=capture.list().map((c)=>c.name);
   try{
    await (await driver.waitForComponent(ON.id('begin-capture'),5000)).click();
    await (await driver.waitForComponent(ON.text('打开相机 · 拍摄视频'),5000)).click();
    await driver.delayMs(1200);
    for(const label of ['仅使用期间允许','使用期间允许','允许','本次使用允许']){const allow=await driver.findComponent(ON.text(label));if(allow){await allow.click();break;}}
    await driver.waitForComponent(ON.id('camera-preview-active'),15000);
    await driver.assertComponentExist(ON.id('camera-preview-active'));
    const record=await driver.findComponent(ON.id('camera-record').enabled(true));
    if(!record){const status=await (await driver.findComponent(ON.id('camera-status'))).getText();expect(status.includes('无录像编码器')).assertTrue();console.info('SELF_CAMERA_TEST '+JSON.stringify({nativePreview:true,recording:false,reason:'no_video_encoder',reconstruction:false}));await driver.pressBack();return;}
    await record.click();await driver.delayMs(3200);
    await (await driver.waitForComponent(ON.text('结束并保存视频'),5000)).click();
    await driver.waitForComponent(ON.text('视频已私密保存 · 尚未生成个人3D'),10000);
    const added=capture.list().filter((c)=>!before.includes(c.name));expect(added.length).assertEqual(1);expect(added[0].bytes>10000).assertTrue();
    const file=fs.openSync(context.filesDir+'/captures/'+added[0].name,fs.OpenMode.READ_ONLY);const header=new ArrayBuffer(12);try{fs.readSync(file.fd,header);}finally{fs.closeSync(file);}
    const bytes=new Uint8Array(header);expect(bytes[4]===102&&bytes[5]===116&&bytes[6]===121&&bytes[7]===112).assertTrue();
    // Evidence contains metadata only. Never copy host webcam frames into the repository or send them to a model.
    const metadata=fs.readTextSync(context.filesDir+'/captures/'+added[0].name+'.json');console.info('SELF_CAMERA_TEST '+metadata);
    await driver.pressBack();await driver.assertComponentExist(ON.text('示例面容 · 数字表达'));
   }catch(e){const status=await driver.findComponent(ON.id('camera-status'));console.error('SELF_CAMERA_TEST_FAILED '+(status?await status.getText():String(e)));throw new Error(String(e));}
   finally{capture.list().filter((c)=>!before.includes(c.name)).forEach((c)=>capture.delete(c.name));}
  });
 });
}

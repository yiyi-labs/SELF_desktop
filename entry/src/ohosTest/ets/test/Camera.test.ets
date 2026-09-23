import { CaptureService,CaptureRecord } from '../../../main/ets/services/CaptureService';
import { fileIo as fs } from '@kit.CoreFileKit';
import { media } from '@kit.MediaKit';
import { image } from '@kit.ImageKit';
import { describe,it,expect } from '@ohos/hypium';
import { Driver,ON } from '@ohos.UiTest';
import { window } from '@kit.ArkUI';
import { abilityDelegatorRegistry } from '@kit.TestKit';
import { UiPreference } from '../../../main/ets/services/UiPreference';

export default function cameraSuite(){
 describe('SELFNativeCamera',()=>{
  it('fullScreenCameraRotatesReopensAndKeepsEntry',0,async()=>{
   const app=abilityDelegatorRegistry.getAbilityDelegator();await app.startAbility({bundleName:'com.self.mirror',abilityName:'EntryAbility'});
   const driver=Driver.create();await driver.delayMs(1800);const context=(await app.getCurrentTopAbility()).context;
   const appWindow=await window.getLastWindow(context);const initial=await driver.getDisplayRotation();
   try{
    for(let pass=0;pass<2;pass++){
     await (await driver.waitForComponent(ON.id('begin-capture'),5000)).click();
     await driver.delayMs(900);
     for(const label of ['仅使用期间允许','使用期间允许','允许','本次使用允许']){const allow=await driver.findComponent(ON.text(label));if(allow){await allow.click();break;}}
     await driver.waitForComponent(ON.id('camera-preview-active'),15000);
     const full=await (await driver.findComponent(ON.id('camera-fullscreen'))).getBounds();
     const size=await driver.getDisplaySize();expect(full.right-full.left>size.x*.95).assertTrue();expect(full.bottom-full.top>size.y*.90).assertTrue();
     const preview=await (await driver.findComponent(ON.id('self-camera-preview'))).getBounds();
     const ratio=(preview.right-preview.left)/(preview.bottom-preview.top);
     // UiTest bounds are clipped to the viewport, so they must cover it. Actual uncut surface geometry is logged separately.
     expect(preview.left<=full.left+2&&preview.right>=full.right-2&&preview.top<=full.top+2&&preview.bottom>=full.bottom-2).assertTrue();
     if(pass===0){
      await appWindow.setPreferredOrientation(window.Orientation.PORTRAIT);await driver.delayMs(1800);
      await driver.assertComponentExist(ON.id('camera-preview-active'));
      const rotated=await (await driver.findComponent(ON.id('camera-fullscreen'))).getBounds();
      expect(rotated.right-rotated.left!==full.right-full.left).assertTrue();
      await appWindow.setPreferredOrientation(window.Orientation.LANDSCAPE);await driver.delayMs(1600);
      await driver.pressHome();await driver.delayMs(600);await app.startAbility({bundleName:'com.self.mirror',abilityName:'EntryAbility'});
      await driver.waitForComponent(ON.id('camera-preview-active'),15000);
     }
     if(!await driver.findComponent(ON.id('camera-status')))await (await driver.findComponent(ON.id('camera-info'))).click();await driver.delayMs(350);
     const status=await (await driver.findComponent(ON.id('camera-status'))).getText();
     const canRecord=await driver.findComponent(ON.id('camera-record').enabled(true));
     console.info('SELF_CAMERA_LAYOUT '+JSON.stringify({pass,fullscreen:full,preview,ratio,status,canRecord:!!canRecord,privatePixelsCaptured:false}));
     expect(!!canRecord).assertTrue();
     await driver.pressBack();await driver.delayMs(650);await driver.assertComponentExist(ON.id('begin-capture'));
    }
    await driver.assertComponentExist(ON.text('示例面容 · 数字表达'));
   }finally{if(await driver.findComponent(ON.id('camera-fullscreen')))await driver.pressBack();await appWindow.setPreferredOrientation(window.Orientation.AUTO_ROTATION_RESTRICTED);await driver.setDisplayRotation(initial);}
  });
  it('cameraActuallyRecordsAndDecodesPrivately',0,async()=>{
   const app=abilityDelegatorRegistry.getAbilityDelegator();await app.startAbility({bundleName:'com.self.mirror',abilityName:'EntryAbility'});
   const driver=Driver.create();await driver.delayMs(1200);const context=(await app.getCurrentTopAbility()).context;
   const captures=new CaptureService(context);const before=captures.list().map((r:CaptureRecord)=>r.name);let created:CaptureRecord[]=[];
   try{
    await (await driver.waitForComponent(ON.id('begin-capture'),5000)).click();
    const button=await driver.waitForComponent(ON.id('camera-record').enabled(true),15000);await button.click();await driver.delayMs(4200);
    await (await driver.findComponent(ON.id('camera-record'))).click();await driver.delayMs(2200);
    created=captures.list().filter((r:CaptureRecord)=>!before.includes(r.name));expect(created.length).assertEqual(1);expect(created[0].bytes>1024).assertTrue();
    const file=fs.openSync(context.filesDir+'/captures/'+created[0].name,fs.OpenMode.READ_ONLY);
    const extractor=await media.createAVImageGenerator();
    try{extractor.fdSrc={fd:file.fd,offset:0,length:created[0].bytes};const frame=await extractor.fetchFrameByTime(500000,media.AVImageQueryOptions.AV_IMAGE_QUERY_CLOSEST,{width:240,height:136});const info=await frame.getImageInfo();expect(info.size.width>0&&info.size.height>0).assertTrue();await frame.release();console.info('SELF_CAMERA_PRIVATE_VIDEO '+JSON.stringify({saved:true,decode:true,bytes:created[0].bytes,width:info.size.width,height:info.size.height,privateVideoExported:false}));}
    finally{await extractor.release();fs.closeSync(file);}
    await driver.pressBack();await driver.delayMs(400);
    await (await driver.findComponent(ON.id('open-settings'))).click();await driver.delayMs(350);
    await (await driver.findComponent(ON.text('采集记录'))).click();await driver.delayMs(400);
    await (await driver.findComponent(ON.id('play-'+created[0].name))).click();await driver.delayMs(1200);
    await driver.assertComponentExist(ON.id('capture-playback'));await driver.pressBack();
   }finally{if(await driver.findComponent(ON.id('camera-fullscreen')))await driver.pressBack();created=captures.list().filter((r:CaptureRecord)=>!before.includes(r.name));for(const clip of created)captures.delete(clip.name);}
  });
  it('orientationChangeSavesCurrentVideoSegment',0,async()=>{
   const app=abilityDelegatorRegistry.getAbilityDelegator();await app.startAbility({bundleName:'com.self.mirror',abilityName:'EntryAbility'});
   const driver=Driver.create();await driver.delayMs(1200);const context=(await app.getCurrentTopAbility()).context;
   const appWindow=await window.getLastWindow(context);const captures=new CaptureService(context);const before=captures.list().map((r:CaptureRecord)=>r.name);
   try{
    await appWindow.setPreferredOrientation(window.Orientation.LANDSCAPE);await driver.delayMs(700);
    await (await driver.waitForComponent(ON.id('begin-capture'),5000)).click();await (await driver.waitForComponent(ON.id('camera-record').enabled(true),15000)).click();await driver.delayMs(2300);
    await appWindow.setPreferredOrientation(window.Orientation.PORTRAIT);await driver.delayMs(3000);
    expect(captures.list().filter((r:CaptureRecord)=>!before.includes(r.name)).length).assertEqual(1);
    await driver.assertComponentExist(ON.text('视频已留在本机'));console.info('SELF_CAMERA_ROTATION_SAVED true');
   }finally{
    if(await driver.findComponent(ON.id('camera-fullscreen')))await driver.pressBack();
    await appWindow.setPreferredOrientation(window.Orientation.AUTO_ROTATION_RESTRICTED);
    for(const clip of captures.list().filter((r:CaptureRecord)=>!before.includes(r.name)))captures.delete(clip.name);
   }
  });
  it('anchoredAtmosphereAccentAndLanguage'  ,0,async()=>{
   const app=abilityDelegatorRegistry.getAbilityDelegator();const driver=Driver.create();
   const context=(await app.getCurrentTopAbility()).context;const before=UiPreference.load(context);
   try{
    const trigger=await driver.waitForComponent(ON.id('open-ambience'),5000);const anchor=await trigger.getBounds();await trigger.click();await driver.delayMs(450);
    const panel=await (await driver.findComponent(ON.id('detail-panel'))).getBounds();
    expect(panel.right>=anchor.left&&panel.top>anchor.top).assertTrue();
    await (await driver.findComponent(ON.id('accent-487F80'))).click();await driver.delayMs(350);
    expect(UiPreference.load(context).accent).assertEqual('#487F80');
    await (await driver.findComponent(ON.id('palette-clear'))).click();await driver.delayMs(600);
    await driver.screenCapture(context.filesDir+'/atmosphere-new.png');
    await (await driver.findComponent(ON.id('panel-close'))).click();await driver.delayMs(350);
    await (await driver.findComponent(ON.id('open-settings'))).click();await driver.delayMs(350);
    await (await driver.findComponent(ON.id('language-en'))).click();await driver.delayMs(350);
    await driver.assertComponentExist(ON.text('Privacy & cloud'));expect(UiPreference.load(context).language).assertEqual('en');
    await driver.screenCapture(context.filesDir+'/settings-en.png');
    await (await driver.findComponent(ON.id('panel-close'))).click();await driver.delayMs(350);
    await driver.assertComponentExist(ON.text('Send'));
    await (await driver.findComponent(ON.id('open-settings'))).click();await driver.delayMs(350);await (await driver.findComponent(ON.id('language-zh'))).click();
    await driver.assertComponentExist(ON.text('隐私与云端'));await driver.pressBack();
    console.info('SELF_UI_SETTINGS '+JSON.stringify({anchor,panel,accentSaved:true,languageSaved:true,englishControls:true,restoredChinese:true}));
   }finally{UiPreference.save(context,before);}
  });
 });
}

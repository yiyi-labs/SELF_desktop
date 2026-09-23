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
     await (await driver.findComponent(ON.id('camera-info'))).click();await driver.delayMs(350);
     const status=await (await driver.findComponent(ON.id('camera-status'))).getText();
     const canRecord=await driver.findComponent(ON.id('camera-record').enabled(true));
     console.info('SELF_CAMERA_LAYOUT '+JSON.stringify({pass,fullscreen:full,preview,ratio,status,canRecord:!!canRecord,privatePixelsCaptured:false}));
     if(!canRecord)expect(status.includes('无录像编码器')).assertTrue();
     await driver.pressBack();await driver.delayMs(650);await driver.assertComponentExist(ON.id('begin-capture'));
    }
    await driver.assertComponentExist(ON.text('示例面容 · 数字表达'));
   }finally{if(await driver.findComponent(ON.id('camera-fullscreen')))await driver.pressBack();await appWindow.setPreferredOrientation(window.Orientation.AUTO_ROTATION_RESTRICTED);await driver.setDisplayRotation(initial);}
  });
  it('anchoredAtmosphereAccentAndLanguage',0,async()=>{
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

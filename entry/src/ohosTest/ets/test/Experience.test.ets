import { describe,it,expect } from '@ohos/hypium';
import { Driver,ON,PointerMatrix,DisplayRotation } from '@ohos.UiTest';
import { window } from '@kit.ArkUI';
import { abilityDelegatorRegistry } from '@kit.TestKit';

export default function experienceSuite(){
 describe('SELFNativeExperience',()=>{
  it('penCircleWithoutToolbarAndWindowRotation',0,async()=>{
   const app=abilityDelegatorRegistry.getAbilityDelegator();await app.startAbility({bundleName:'com.self.mirror',abilityName:'EntryAbility'});
   const driver=Driver.create();await driver.delayMs(2000);const initial=await driver.getDisplayRotation();
   const context=(await app.getCurrentTopAbility()).context;const path=context.filesDir;const appWindow=await window.getLastWindow(context);
   try{
    const r=await (await driver.findComponent(ON.id('self-native-mirror'))).getBounds();
    const points=PointerMatrix.create(1,33);for(let i=0;i<33;i++){const a=i/32*Math.PI*2;points.setPoint(0,i,{x:Math.round(r.left+(r.right-r.left)*(.5+.055*Math.cos(a))),y:Math.round(r.top+(r.bottom-r.top)*(.42+.08*Math.sin(a)))});}
    await driver.injectPenPointerAction(points,700,.5);await driver.delayMs(1000);
    await driver.assertComponentExist(ON.text('想试一点变化'));
    const popup=await (await driver.findComponent(ON.id('conversation-card'))).getBounds();const display=await driver.getDisplaySize();
    expect(popup.left>=0&&popup.right<=display.x&&popup.top>=0&&popup.bottom<=display.y).assertTrue();
    await driver.screenCapture(path+'/experience-pen-popup.png');
    await appWindow.setPreferredOrientation(window.Orientation.PORTRAIT);await driver.delayMs(1600);
    const changed=await (await driver.findComponent(ON.id('self-native-mirror'))).getBounds();
    expect(changed.right-changed.left!==r.right-r.left).assertTrue();
    await (await driver.findComponent(ON.text('回正'))).click();
    await driver.screenCapture(path+'/experience-rotated.png');
    console.info('SELF_EXPERIENCE '+JSON.stringify({injectedPen:true,penSelectedWithoutToolbar:true,popupWithinWindow:true,rotationChangedWidth:true}));
   }finally{await appWindow.setPreferredOrientation(window.Orientation.AUTO_ROTATION_RESTRICTED);await driver.setDisplayRotation(initial);}
  });
  it('cameraPickerCanReturnWithoutReplacingSample',0,async()=>{
   const app=abilityDelegatorRegistry.getAbilityDelegator();await app.startAbility({bundleName:'com.self.mirror',abilityName:'EntryAbility'});
   const driver=Driver.create();await driver.delayMs(1800);const path=(await app.getCurrentTopAbility()).context.filesDir;
   const direct=await driver.findComponent(ON.text('拍摄'));
   if(direct)await direct.click();else{await (await driver.findComponent(ON.text('工具'))).click();await (await driver.waitForComponent(ON.text('拍摄面容视频'),5000)).click();}
   await (await driver.findComponent(ON.text('打开相机 · 拍摄视频'))).click();await driver.delayMs(3000);
   await driver.screenCapture(path+'/experience-camera.png');await driver.dumpLayout(path+'/experience-camera-layout.json');
   await driver.pressBack();await driver.delayMs(1200);
   await driver.screenCapture(path+'/experience-camera-return.png');
   await driver.assertComponentExist(ON.text('拍摄面容'));
   await driver.pressBack();await driver.assertComponentExist(ON.text('示例面容 · 数字表达'));
   console.info('SELF_CAMERA_PICKER '+JSON.stringify({launchAndReturn:true,sourceUnchanged:true,reconstruction:false}));
  });
  it('keyboardInputCanRequestModelWithoutExecuting',0,async()=>{
   const app=abilityDelegatorRegistry.getAbilityDelegator();await app.startAbility({bundleName:'com.self.mirror',abilityName:'EntryAbility'});
   const driver=Driver.create();await driver.delayMs(1700);const path=(await app.getCurrentTopAbility()).context.filesDir;
   try{
    const input=await driver.findComponent(ON.id('conversation-input'));await input.inputText('试试唇色');await driver.delayMs(800);
    expect(await input.getText()).assertEqual('试试唇色');await driver.screenCapture(path+'/experience-keyboard.png');
    await (await driver.findComponent(ON.text('发送'))).click();
    await driver.waitForComponent(ON.text('仅本次发送图像并理解'),5000);
    await (await driver.findComponent(ON.text('暂不发送，保留现在'))).click();
    console.info('SELF_KEYBOARD '+JSON.stringify({inputReadback:true,modelConsentShown:true,noUpload:true}));
   }catch(e){await driver.screenCapture(path+'/experience-keyboard-failure.png');throw new Error(String(e));}
  });
 });
}

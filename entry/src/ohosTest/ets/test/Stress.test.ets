import { describe,it,expect } from '@ohos/hypium';
import { abilityDelegatorRegistry } from '@kit.TestKit';
import { Driver,ON } from '@ohos.UiTest';
export default function stressSuite(){
 describe('SELFNativeStress',()=>{
  it('tenMinutesActualRotationEditCompareDetailsAndBackground',0,async()=>{
   const app=abilityDelegatorRegistry.getAbilityDelegator(),driver=Driver.create();
   await app.startAbility({bundleName:'com.self.mirror',abilityName:'EntryAbility'});await driver.delayMs(2200);
   const started=Date.now();let cycles=0;
   while(Date.now()-started<600000){
    await (await driver.waitForComponent(ON.text('回正'),5000)).click();
    const r=await (await driver.findComponent(ON.id('self-native-mirror'))).getBounds();
    await driver.swipe(Math.round(r.left+(r.right-r.left)*.4),Math.round((r.top+r.bottom)*.5),Math.round(r.left+(r.right-r.left)*.6),Math.round((r.top+r.bottom)*.5),500);
    await (await driver.findComponent(ON.text('工具'))).click();
    await (await driver.waitForComponent(ON.text('建议轻唇色'),5000)).click();
    await (await driver.waitForComponent(ON.text('试一下'),5000)).click();await driver.delayMs(1000);
    await driver.assertComponentExist(ON.text('已应用通用数字表达 · 非产品实测'));
    await (await driver.findComponent(ON.text('对照'))).click();await driver.delayMs(400);
    await (await driver.findComponent(ON.text('对照'))).click();
    await (await driver.findComponent(ON.text('撤销'))).click();await driver.delayMs(900);
    await (await driver.findComponent(ON.text('氛围'))).click();await driver.delayMs(250);await driver.pressBack();
    await (await driver.waitForComponent(ON.text('轻转'),5000)).click();await driver.delayMs(800);
    cycles++;if(cycles%10===0){await driver.pressHome();await driver.delayMs(700);await app.startAbility({bundleName:'com.self.mirror',abilityName:'EntryAbility'});await driver.delayMs(1000);console.info('SELF_STRESS_STEP '+JSON.stringify({elapsedMs:Date.now()-started,cycles}));}
   }
   await driver.pressHome();await driver.delayMs(800);await app.startAbility({bundleName:'com.self.mirror',abilityName:'EntryAbility'});await driver.delayMs(1000);
   expect(Date.now()-started>=600000).assertTrue();console.info('SELF_STRESS_FINISHED '+JSON.stringify({elapsedMs:Date.now()-started,cycles}));
  });
 });
}

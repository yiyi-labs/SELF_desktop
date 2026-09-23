import { describe,it,expect } from '@ohos/hypium';
import { Driver,ON } from '@ohos.UiTest';
import { abilityDelegatorRegistry } from '@kit.TestKit';
import { fileIo as fs } from '@kit.CoreFileKit';
import { SavedWorkspace } from '../../../main/ets/domain/EditPlan';
import { AssetStore } from '../../../main/ets/services/AssetStore';
import { WorkspaceStore,WorkItem } from '../../../main/ets/services/WorkspaceStore';

/** Explicit paid integration suite, excluded by Test-Native.ps1 by default.
 * Run after restarting EntryAbility, which opens the public sample, never a saved personal photo.
 */
export default function liveModelSuite(){
 describe('SELFNativeModelLive',()=>{
  it('publicSampleImageModelConsentNativeCommitAndBill',0,async()=>{
   const app=abilityDelegatorRegistry.getAbilityDelegator();await app.startAbility({bundleName:'com.self.mirror',abilityName:'EntryAbility'});
   const driver=Driver.create();await driver.delayMs(2200);await driver.assertComponentExist(ON.text('示例面容 · 数字表达'));
   const context=(await app.getCurrentTopAbility()).context,assets=new AssetStore(context),works=new WorkspaceStore(context,assets);
   const before=works.list().map((w:WorkItem)=>w.id);let created='';
   let stage='input';
   try{
    const input=await driver.findComponent(ON.id('conversation-input'));await input.inputText('请在已确认唇区新增一层轻柔的柔玫瑰通用数字颜色。');await driver.delayMs(600);expect(await input.getText()).assertEqual('请在已确认唇区新增一层轻柔的柔玫瑰通用数字颜色。');
    stage='first-send';
    await (await driver.findComponent(ON.text('发送'))).click();
    await driver.waitForComponent(ON.text('开启并发送'),5000);
    expect(!!(await driver.findComponent(ON.id('apply-candidate')))).assertFalse();
    await driver.assertComponentExist(ON.text('开启并发送'));stage='model';await (await driver.findComponent(ON.text('开启并发送'))).click();
    await (await driver.waitForComponent(ON.id('apply-candidate'),55000)).click();
    await driver.waitForComponent(ON.text('这一点变化已经做好了，喜欢就留下。'),10000);
    stage='save';await driver.delayMs(1000);
    const direct=await driver.findComponent(ON.text('作品'));
    if(direct)await direct.click();else{await (await driver.findComponent(ON.text('工具'))).click();await (await (await driver.findComponent(ON.type('Scroll'))).scrollSearch(ON.text('作品与记录'))).click();}
    await (await driver.waitForComponent(ON.text('保存当前作品'),5000)).click();await driver.delayMs(700);
    const added=works.list().filter((w:WorkItem)=>!before.includes(w.id));expect(added.length).assertEqual(1);created=added[0].id;
    const saved=JSON.parse(fs.readTextSync(context.filesDir+'/works/'+created+'/workspace.json')) as SavedWorkspace;
    const operations=saved.snapshots[saved.cursor].operations;expect(operations.length).assertEqual(1);
    expect(operations[0].plannerSource?.startsWith('DeepSeek · ')).assertTrue();expect(!!operations[0].snapshotId).assertTrue();
    expect(operations[0].compositingVersion).assertEqual('perceptual-v2');
    console.info('SELF_LIVE_MODEL_COMMIT '+JSON.stringify({sourceKind:saved.sourceKind,model:operations[0].plannerSource,preset:operations[0].presetId,strength:operations[0].absoluteStrength,renderCommitted:true,billCount:operations.length,compositingVersion:operations[0].compositingVersion}));
    await driver.pressBack();await (await driver.waitForComponent(ON.id('conversation-input'),5000)).inputText('先不用改，我想保留现在，简单回应即可。');await driver.delayMs(600);stage='second-send';
    await (await driver.findComponent(ON.text('发送'))).click();await driver.delayMs(400);
    expect(!!(await driver.findComponent(ON.id('cloud-enable-send')))).assertFalse();
    expect(!!(await driver.findComponent(ON.text('云端理解')))).assertFalse();
    const cancel=await driver.findComponent(ON.text('取消这次请求'));if(cancel)await cancel.click();
    console.info('SELF_CLOUD_SESSION '+JSON.stringify({secondSendWithoutConsentModal:true}));
    stage='undo';await (await driver.waitForComponent(ON.text('撤销').enabled(true),5000)).click();await driver.delayMs(800);
   }catch(e){console.error('SELF_MODEL_TEST_STAGE '+stage+' '+String(e));await driver.screenCapture(context.filesDir+'/live-model-failure.png');throw new Error(String(e));}finally{if(created&&!before.includes(created))works.delete(created);}
  });
 });
}

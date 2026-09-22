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
   try{
    const idea=await driver.findComponent(ON.text('唇色想法'));
    if(idea)await idea.click();else{await (await driver.findComponent(ON.text('工具'))).click();await (await driver.waitForComponent(ON.text('让模型规划唇色'),5000)).click();}
    await driver.waitForComponent(ON.text('仅本次发送图像并理解'),5000);
    expect(!!(await driver.findComponent(ON.id('apply-candidate')))).assertFalse();
    await (await driver.findComponent(ON.text('仅本次发送图像并理解'))).click();
    await (await driver.waitForComponent(ON.id('apply-candidate'),55000)).click();
    await driver.waitForComponent(ON.text('已应用通用数字表达 · 非产品实测'),10000);
    await driver.delayMs(1000);
    const direct=await driver.findComponent(ON.text('作品'));
    if(direct)await direct.click();else{await (await driver.findComponent(ON.text('工具'))).click();await (await (await driver.findComponent(ON.type('Scroll'))).scrollSearch(ON.text('作品与记录'))).click();}
    await (await driver.waitForComponent(ON.text('保存当前作品'),5000)).click();await driver.delayMs(700);
    const added=works.list().filter((w:WorkItem)=>!before.includes(w.id));expect(added.length).assertEqual(1);created=added[0].id;
    const saved=JSON.parse(fs.readTextSync(context.filesDir+'/works/'+created+'/workspace.json')) as SavedWorkspace;
    const operations=saved.snapshots[saved.cursor].operations;expect(operations.length).assertEqual(1);
    expect(operations[0].plannerSource?.startsWith('DeepSeek · ')).assertTrue();expect(!!operations[0].snapshotId).assertTrue();
    expect(operations[0].compositingVersion).assertEqual('perceptual-v2');
    console.info('SELF_LIVE_MODEL_COMMIT '+JSON.stringify({sourceKind:saved.sourceKind,model:operations[0].plannerSource,preset:operations[0].presetId,strength:operations[0].absoluteStrength,renderCommitted:true,billCount:operations.length,compositingVersion:operations[0].compositingVersion}));
    await driver.pressBack();await (await driver.waitForComponent(ON.text('撤销').enabled(true),5000)).click();await driver.delayMs(800);
   }catch(e){await driver.screenCapture(context.filesDir+'/live-model-failure.png');throw new Error(String(e));}finally{if(created&&!before.includes(created))works.delete(created);}
  });
 });
}

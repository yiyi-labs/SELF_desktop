import { describe, it, expect } from '@ohos/hypium';
import { SessionStore } from '../../../main/ets/domain/SessionStore';
import { PolicyEngine } from '../../../main/ets/domain/PolicyEngine';
import { PlannerService } from '../../../main/ets/services/PlannerService';
import { ProductRepository } from '../../../main/ets/services/ProductRepository';
import { AmbiencePreference } from '../../../main/ets/services/AmbiencePreference';
import { AssetStore } from '../../../main/ets/services/AssetStore';
import { WorkspaceStore, WorkItem } from '../../../main/ets/services/WorkspaceStore';
import { abilityDelegatorRegistry } from '@kit.TestKit';
import { Driver, ON, PointerMatrix } from '@ohos.UiTest';
import { common } from '@kit.AbilityKit';
import stressSuite from './Stress.test';
import liveModelSuite from './LiveModel.test';
import experienceSuite from './Experience.test';
import productSuite from './Product.test';
import cameraSuite from './Camera.test';
import { fileIo as fs } from '@kit.CoreFileKit';
import { CandidatePlan, SavedWorkspace } from '../../../main/ets/domain/EditPlan';
// Contract fixture only. UI paths cannot call this helper and real model tests use PlannerClient.
class ModelFixtureSession extends SessionStore {
  propose(kind:string,regionId:string,presetId:string='rose',strength:number=.25,replacesLast:boolean=false):CandidatePlan {
    const p=super.propose(kind,regionId,presetId,strength,replacesLast);p.plannerSource='DeepSeek · test-fixture';p.snapshotId='test-snapshot';return p;
  }
}
async function openWorks(driver:Driver):Promise<void>{
  const direct=await driver.findComponent(ON.text('作品'));
  if(direct){await direct.click();return;}
  await (await driver.findComponent(ON.text('工具'))).click();await driver.delayMs(300);
  await (await (await driver.findComponent(ON.type('Scroll'))).scrollSearch(ON.text('作品与记录'))).click();
}
async function exportFrame(driver:Driver):Promise<void>{
  const direct=await driver.findComponent(ON.text('导出'));
  if(direct){await direct.click();return;}
  await (await driver.findComponent(ON.text('工具'))).click();await (await driver.waitForComponent(ON.text('保存当前画面 PNG'),5000)).click();
}
function session():SessionStore{
  const s=new ModelFixtureSession();
  s.regions.push({regionId:'lip',assetId:s.assetId,assetVersion:s.assetVersion,width:1024,height:1024,semantic:'confirmed-lips',fileName:'lip.mask'});
  return s;
}
export default function testsuite(){
  stressSuite();liveModelSuite();experienceSuite();productSuite();cameraSuite();
  describe('SELFNativePolicy',()=>{
    it('localNewEffectCannotBypassModelButRestoreRemainsLocal',0,()=>{
      const s=new SessionStore();s.regions=session().regions;const plan=s.propose('lipTint','lip');let rejected=false;
      try{s.authorize(plan.planId);}catch(e){rejected=true;}expect(rejected).assertTrue();expect(s.pending===undefined).assertTrue();expect(s.operations.length).assertEqual(0);
      s.reset();expect(s.succeeded(s.pendingRequest,s.revision)).assertTrue();expect(s.operations.length).assertEqual(0);
    });
    it('mainlandCatalogHasNoFabricatedCalibration',0,()=>{
      const products=ProductRepository.records();expect(products.length).assertEqual(8);
      expect(products.every((p)=>p.region==='中国大陆渠道资料'&&p.calibrationProfile==='')).assertTrue();
    });
    it('oneOperationExceptionDoesNotUnlockPolicy',0,()=>{
      const s=session();s.protect('lip',false,true);const key=s.protectionKey();
      s.authorize(s.propose('lipTint','lip').planId,true);s.succeeded(s.pendingRequest,s.revision);
      expect(s.protection?.persistent).assertTrue();expect(s.operations[0].protectionException).assertEqual(key);
      s.authorize(s.propose('lipTint','lip').planId);s.succeeded(s.pendingRequest,s.revision);expect(s.operations[1].protectionException===undefined).assertTrue();
      s.replay(-1);s.succeeded(s.pendingRequest,s.revision);expect(s.protectionKey()).assertEqual(key);
    });
    it('rotationDoesNotExpireCandidateButBusinessChangeDoes',0,()=>{
      const s=session();const plan=s.propose('lipTint','lip');s.viewRevision++;s.view.yaw=.5;s.authorize(plan.planId);s.succeeded(s.pendingRequest,s.revision);
      const stale=s.propose('lipTint','lip');s.sceneRevision++;let rejected=false;try{s.authorize(stale.planId);}catch(e){rejected=true;}expect(rejected).assertTrue();
    });
    it('targetedLayerRemovalWaitsForRenderSuccess',0,()=>{
      const s=session();s.authorize(s.propose('lipTint','lip').planId);s.succeeded(s.pendingRequest,s.revision);const id=s.operations[0].operationId;
      const p=s.propose('lipTint','lip','rose',0);p.targetLayerId=id;p.removeLayer=true;s.authorize(p.planId);expect(s.operations.length).assertEqual(1);s.succeeded(s.pendingRequest,s.revision);expect(s.operations.length).assertEqual(0);
    });
    it('deletingSavedRecordKeepsCurrentWorkingAssetsReadable',0,async()=>{
      const context=abilityDelegatorRegistry.getAbilityDelegator().getAppContext() as common.UIAbilityContext;
      const assets=new AssetStore(context),works=new WorkspaceStore(context,assets),s=new SessionStore();
      const id='test-region-'+Date.now();s.width=2;s.height=2;
      s.regions=[{regionId:id,assetId:s.assetId,assetVersion:s.assetVersion,width:2,height:2,semantic:'manual',fileName:id+'.mask'}];
      assets.saveMask(id,new Uint8Array([0,255,127,0]).buffer as ArrayBuffer);
      const first=await works.save(s),opened=works.open(first.id);works.delete(first.id);
      try{
        const bytes=await assets.read(id);expect(bytes.length).assertEqual(4);expect(bytes[1]).assertEqual(255);
        const restored=new SessionStore();restored.restore(opened);
        const second=await works.save(restored);expect(works.open(second.id).regions[0].regionId).assertEqual(id);works.delete(second.id);
      }finally{assets.cleanupTemporary();}
    });
    it('candidateRequiresConsentAndSuccess',0,()=>{
      const s=session(),p=s.propose('lipTint','lip');expect(s.operations.length).assertEqual(0);
      s.authorize(p.planId);expect(s.operations.length).assertEqual(0);
      expect(s.succeeded('stale',s.revision)).assertFalse();
      expect(s.succeeded(s.pendingRequest,s.revision)).assertTrue();expect(s.operations.length).assertEqual(1);
    });
    it('renderFailureCreatesNoBill',0,()=>{
      const s=session(),p=s.propose('lipTint','lip');s.authorize(p.planId);s.failed();expect(s.operations.length).assertEqual(0);expect(s.snapshots.length).assertEqual(1);
    });
    it('undoRedoAreAcknowledgedAndProtectionPersists',0,()=>{
      const s=session();s.authorize(s.propose('lipTint','lip').planId);s.succeeded(s.pendingRequest,s.revision);s.protect('lip',true,false);
      s.replay(-1);s.succeeded(s.pendingRequest,s.revision);expect(s.operations.length).assertEqual(0);expect(s.protection?.anchorOperations.length).assertEqual(1);
      s.replay(1);s.succeeded(s.pendingRequest,s.revision);expect(s.operations.length).assertEqual(1);
    });
    it('unknownAndUncalibratedOperationsRejected',0,()=>{
      const s=session();let rejected=false;try{s.propose('productSimulation','lip');}catch(e){rejected=true;}expect(rejected).assertTrue();
      expect(PolicyEngine.productSimulationAllowed('', ['brand-information'])).assertFalse();
      expect(ProductRepository.records()[0].calibrationProfile).assertEqual('');
    });
    it('savedAnchorIsIndependentAndCanRestore',0,()=>{
      const s=session();s.authorize(s.propose('lipTint','lip').planId);s.succeeded(s.pendingRequest,s.revision);s.protect('lip',true,false);
      const saved=s.serialize('work-1','test'),restored=session();restored.restore(saved);
      expect(restored.protection?.anchorOperations[0].absoluteStrength).assertEqual(.25);
      s.operations[0].absoluteStrength=.5;expect(saved.protection?.anchorOperations[0].absoluteStrength).assertEqual(.25);
      s.view={yaw:.5,pitch:0,distance:18,panX:0,panY:0};restored.restore(s.serialize('work-2','angle'));expect(restored.view.yaw).assertEqual(.5);
    });
    it('distressDoesNotRecommendProductsOrEdit',0,()=>{
      expect(PlannerService.plan('我不喜欢这里').action).assertEqual('supportOffer');
      expect(PlannerService.plan('自然一点').action).assertEqual('suggestLip');
      expect(PlannerService.plan('取消').action).assertEqual('cancel');
      expect(PlannerService.plan('我想伤害自己').action).assertEqual('urgentSupport');
      expect(AmbiencePreference.fromText('我不开心')).assertEqual('quiet');
      expect(AmbiencePreference.fromText('我今天很开心')).assertEqual('warm');
    });
  });
  describe('SELFNativeApi26UI',()=>{
    it('saveReopenExportAndDeleteOnlyNewTestWork',0,async()=>{
      const app=abilityDelegatorRegistry.getAbilityDelegator();await app.startAbility({bundleName:'com.self.mirror',abilityName:'EntryAbility'});const driver=Driver.create();await driver.delayMs(2200);
      const context=(await app.getCurrentTopAbility()).context;const assets=new AssetStore(context),works=new WorkspaceStore(context,assets);const before=works.list().map((w:WorkItem)=>w.id);
      const exportPath=context.filesDir+'/self-export.png';const priorExport=fs.accessSync(exportPath)?assets.readFile(exportPath):undefined;let createdId='';
      try{
        // Saving the unmodified view requires no model call.
        const r=await (await driver.findComponent(ON.id('self-native-mirror'))).getBounds();await driver.swipe(Math.round(r.left+(r.right-r.left)*.44),Math.round((r.top+r.bottom)*.5),Math.round(r.left+(r.right-r.left)*.54),Math.round((r.top+r.bottom)*.5),500);await driver.delayMs(500);
        await openWorks(driver);await driver.delayMs(300);
        await (await driver.findComponent(ON.text('保存当前作品'))).click();await driver.delayMs(700);
        const created=works.list().filter((w:WorkItem)=>!before.includes(w.id));expect(created.length).assertEqual(1);createdId=created[0].id;
        const saved=JSON.parse(fs.readTextSync(context.filesDir+'/works/'+createdId+'/workspace.json')) as SavedWorkspace;expect(saved.snapshots[saved.cursor].operations.length).assertEqual(0);expect(Math.abs(saved.view?.yaw||0)>.01).assertTrue();
        await (await driver.findComponent(ON.id('open-'+createdId))).click();await driver.delayMs(1500);await exportFrame(driver);await driver.delayMs(1500);
        const png=assets.readFile(exportPath);expect(png.length>10000).assertTrue();expect(png[0]).assertEqual(137);expect(png[1]).assertEqual(80);
        await openWorks(driver);await driver.delayMs(300);await (await driver.findComponent(ON.id('delete-'+createdId))).click();await driver.delayMs(500);
        expect(works.list().some((w:WorkItem)=>w.id===createdId)).assertFalse();expect(before.every((id:string)=>works.list().some((w:WorkItem)=>w.id===id))).assertTrue();console.info('SELF_UI_WORKFLOW '+JSON.stringify({save:true,reopen:true,deleteOnlyCreated:true,exportPNGBytes:png.length,savedYaw:saved.view?.yaw}));await driver.pressBack();
      }finally{if(createdId&&!before.includes(createdId))works.delete(createdId);if(priorExport)assets.writeAtomic(exportPath,priorExport.buffer as ArrayBuffer);else if(fs.accessSync(exportPath))fs.unlinkSync(exportPath);}
    });
    it('realTouchLassoThenModelConsentDeclineKeepsOriginal',0,async()=>{
      const delegator=abilityDelegatorRegistry.getAbilityDelegator();await delegator.startAbility({bundleName:'com.self.mirror',abilityName:'EntryAbility'});
      const driver=Driver.create();await driver.delayMs(2500);
      const lasso=await driver.findComponent(ON.id('lasso-tool'));await lasso.click();
      const surface=await driver.findComponent(ON.id('self-native-mirror'));const r=await surface.getBounds();
      const matrix=PointerMatrix.create(1,33);for(let i=0;i<33;i++){const angle=i/32*Math.PI*2;matrix.setPoint(0,i,{x:Math.round(r.left+(r.right-r.left)*(.5+.13*Math.cos(angle))),y:Math.round(r.top+(r.bottom-r.top)*(.43+.08*Math.sin(angle)))});}
      expect(await driver.injectMultiPointerAction(matrix,500)).assertTrue();await driver.delayMs(1200);
      await driver.assertComponentExist(ON.text('想说说这里，还是试一点变化？也可以就这样。'));
      const popup=await (await driver.findComponent(ON.id('conversation-card'))).getBounds();
      const mirror=await (await driver.findComponent(ON.id('self-native-mirror'))).getBounds();
      expect(popup.left>=mirror.left&&popup.right<=mirror.right&&popup.top>=mirror.top&&popup.bottom<=mirror.bottom).assertTrue();
      await driver.screenCapture((await delegator.getCurrentTopAbility()).context.filesDir+'/lasso-popup.png');
      await (await driver.findComponent(ON.text('想试一点变化'))).click();
      await driver.waitForComponent(ON.text('开启并发送'),5000);
      await driver.assertComponentExist(ON.text('开启并发送'));
      expect(!!(await driver.findComponent(ON.id('apply-candidate')))).assertFalse();
      await (await driver.findComponent(ON.text('暂不发送'))).click();await driver.delayMs(700);
      expect(!!(await driver.findComponent(ON.id('apply-candidate')))).assertFalse();
      console.info('SELF_LASSO_MODEL_GATE '+JSON.stringify({realTouch:true,cloudConsent:true,declinedWithoutCandidate:true}));
    });
  });
}


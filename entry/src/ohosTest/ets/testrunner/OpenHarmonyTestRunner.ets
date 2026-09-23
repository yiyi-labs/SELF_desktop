import { TestRunner, abilityDelegatorRegistry } from '@kit.TestKit';
import { Hypium } from '@ohos/hypium';
import testsuite from '../test/List.test';
/** Explicit runner because this test module includes its own UI fixture ability. */
export default class OpenHarmonyTestRunner implements TestRunner {
 onPrepare():void{}
 async onRun():Promise<void>{
  const delegator=abilityDelegatorRegistry.getAbilityDelegator();
  try{
   const monitor:abilityDelegatorRegistry.AbilityMonitor={abilityName:'EntryAbility',moduleName:'entry'};
   await delegator.addAbilityMonitor(monitor);
   await delegator.startAbility({bundleName:'com.self.mirror',abilityName:'EntryAbility'});
   await delegator.waitAbilityMonitor(monitor,10000);
   await new Promise<void>((resolve:()=>void)=>{setTimeout(resolve,1200);});
   Hypium.hypiumTest(delegator,abilityDelegatorRegistry.getArguments(),testsuite);
  }catch(error){delegator.finishTest('Could not start test host: '+String(error),-1,()=>{});}
 }
}

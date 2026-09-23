import { describe,it,expect } from '@ohos/hypium';
import { abilityDelegatorRegistry } from '@kit.TestKit';
import { fileIo as fs } from '@kit.CoreFileKit';
interface ProbeResult {recordedAt:number;phase:string;personalReconstructionValidated:boolean;error:string;}
export default function spatialReconSuite(){
  describe('SELFNativeSpatialProbe',()=>{
    it('recordsActualCommercialGsAvailabilityWithoutCallingItReconstruction',0,async()=>{
      const app=abilityDelegatorRegistry.getAbilityDelegator();
      const started=Date.now();let reportPath='';
      try{
        await app.startAbility({bundleName:'com.self.mirror',moduleName:'entry_test',abilityName:'SpatialProbeAbility'});
        let phase='checking';
        for(let i=0;i<150&&(phase==='checking'||phase==='loaded');i++){
          await new Promise<void>((resolve:()=>void)=>setTimeout(resolve,400));
          const top=await app.getCurrentTopAbility();
          if(top&&top.context.abilityInfo.name==='SpatialProbeAbility'){
            const path=top.context.filesDir+'/gs-sdk-probe.json';
            if(fs.accessSync(path)){
              const result=JSON.parse(fs.readTextSync(path)) as ProbeResult;
              if(result.recordedAt>=started){phase=result.phase;reportPath=path;}
            }
          }
        }
        expect(reportPath.length>0).assertTrue();
        const report=JSON.parse(fs.readTextSync(reportPath)) as ProbeResult;
        expect(report.personalReconstructionValidated).assertFalse();
        console.info('SELF_GS_DEVICE_RESULT '+JSON.stringify(report));
        expect(report.phase!=='failed'&&report.phase!=='checking'&&report.phase!=='loaded').assertTrue();
      }finally{await app.startAbility({bundleName:'com.self.mirror',abilityName:'EntryAbility'});}
    });
  });
}

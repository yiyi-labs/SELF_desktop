import { common } from '@kit.AbilityKit';
import { fileIo as fs } from '@kit.CoreFileKit';
import { util } from '@kit.ArkTS';
import { PortraitStarStore } from '../services/PortraitStarStore';
import { AssetStore } from '../services/AssetStore';
import { SelfTransferManifest, SelfViewerState, PlyInfo, ImportedTransfer, ModelImportError, MODEL_ENTRY } from './SelfTransferContract';
import { makeDir, boundedText, writeText, removeTransferTree } from './TransferFiles';

interface TransferReceipt {schema:string;packageId:string;sha256:string;importedAt:string;}
interface LocalTransferView {schemaVersion:number;sourceFrame:string;camera:number[];target:number[];up:number[];
  fovDegrees:number;faceTrackCount:number;sourceFaceFraction:number;targetFaceFraction:number;
  reconstructionMethod:string;surfacePointCount:number;assetSha256:string;}

export class ModelImportAdapter {
  private root:string;
  private stars:PortraitStarStore;
  constructor(context:common.UIAbilityContext){this.root=context.filesDir+'/models';this.stars=new PortraitStarStore(context,new AssetStore(context));makeDir(this.root);}
  private existing(manifest:SelfTransferManifest):ImportedTransfer|undefined{
    for(const star of this.stars.list()){
      const sidecar=this.root+'/'+star.jobId+'/self-transfer.json';if(!fs.accessSync(sidecar))continue;
      let receipt:TransferReceipt;
      try{receipt=JSON.parse(boundedText(sidecar)) as TransferReceipt;}catch(_){continue;}
      if(receipt.schema==='self.transfer.receipt'&&receipt.packageId===manifest.packageId){
        if(receipt.sha256!==manifest.model.sha256)throw new ModelImportError('相同模型包编号对应不同内容，已拒绝导入');
        return {modelId:star.jobId,name:star.name,packageId:manifest.packageId,sha256:receipt.sha256,duplicate:true};
      }
    }return undefined;
  }
  async importValidated(stage:string,manifest:SelfTransferManifest,ply:PlyInfo,viewer:SelfViewerState|undefined,cancelled:()=>boolean):Promise<ImportedTransfer>{
    if(cancelled())throw new ModelImportError('接收已取消');
    const existing=this.existing(manifest);if(existing)return existing;
    // Receiver generates its own ID, never producer IDs or package IDs as repository keys.
    const modelId=util.generateRandomUUID(true).replace(/-/g,''),pending=this.root+'/.self-transfer-'+modelId,destination=this.root+'/'+modelId;
    if(fs.accessSync(pending)||fs.accessSync(destination))throw new ModelImportError('本地模型编号冲突，请重试');
    makeDir(pending);let published=false;
    try{
      const center=ply.min.map((value:number,i:number)=>(value+ply.max[i])/2);
      const radius=Math.max(.1,Math.hypot(ply.max[0]-ply.min[0],ply.max[1]-ply.min[1],ply.max[2]-ply.min[2]));
      const local:LocalTransferView={schemaVersion:1,sourceFrame:'',camera:viewer?viewer.camera:[center[0],center[1],center[2]+radius*1.8],
        target:viewer?viewer.target:center,up:viewer?viewer.up:[0,1,0],fovDegrees:viewer?viewer.fovDegrees:45,
        faceTrackCount:0,sourceFaceFraction:.5,targetFaceFraction:.5,reconstructionMethod:'self-transfer-v1',
        surfacePointCount:ply.vertexCount,assetSha256:manifest.model.sha256};
      // Same private filesystem: move the verified PLY, avoiding a third complete copy.
      await fs.rename(stage+'/'+MODEL_ENTRY,pending+'/portrait.gaussian.ply');
      if(manifest.assets.some((asset)=>asset.path==='preview/preview.png')&&fs.accessSync(stage+'/preview/preview.png'))
        await fs.rename(stage+'/preview/preview.png',pending+'/portrait.preview.png');
      writeText(pending+'/portrait.view.json',JSON.stringify(local));
      const receipt:TransferReceipt={schema:'self.transfer.receipt',packageId:manifest.packageId,sha256:manifest.model.sha256,importedAt:new Date().toISOString()};
      writeText(pending+'/self-transfer.json',JSON.stringify(receipt));
      if(cancelled())throw new ModelImportError('接收已取消');
      // No awaits between publishing a complete directory and committing the existing index.
      fs.renameSync(pending,destination);published=true;
      const name=PortraitStarStore.cleanName(manifest.displayName||'收到的星辰');
      this.stars.upsert(modelId,name);
      return {modelId,name,packageId:manifest.packageId,sha256:manifest.model.sha256,duplicate:false};
    }catch(error){
      removeTransferTree(published?destination:pending,this.root);
      if(error instanceof ModelImportError)throw error;throw new ModelImportError('模型未能完整保存，请检查存储空间后重试');
    }
  }
}

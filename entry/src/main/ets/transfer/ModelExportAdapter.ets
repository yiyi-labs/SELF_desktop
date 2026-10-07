import { common } from '@kit.AbilityKit';
import { fileIo as fs } from '@kit.CoreFileKit';
import { PortraitStarStore } from '../services/PortraitStarStore';
import { AssetStore } from '../services/AssetStore';
import { ModelImportError, SelfViewerState, validViewer } from './SelfTransferContract';
import { boundedText } from './TransferFiles';

interface LocalView {camera:number[];target:number[];up:number[];fovDegrees:number;}
interface EditGroups {groups:object[];}
export interface ExportSource {name:string;plyPath:string;previewPath:string;viewer:SelfViewerState|undefined;}

export class ModelExportAdapter {
  private stars:PortraitStarStore;
  constructor(context:common.UIAbilityContext){this.stars=new PortraitStarStore(context,new AssetStore(context));}
  source(modelId:string):ExportSource{
    const star=this.stars.list().find((item)=>item.jobId===modelId);
    if(!star)throw new ModelImportError('当前模型尚未完整保存');
    const paths=this.stars.modelPaths(modelId),directory=paths.gaussian.substring(0,paths.gaussian.lastIndexOf('/'));
    // Editing is a separate colour/mask recipe, not a persisted PLY snapshot. Do not silently share its original.
    if(fs.accessSync(directory+'/portrait.edit.json'))throw new ModelImportError('当前试色尚不能导出为模型，请恢复原始模型后发送');
    if(fs.accessSync(directory+'/portrait.edit.v2.json')){
      const edits=JSON.parse(boundedText(directory+'/portrait.edit.v2.json',4*1024*1024)) as EditGroups;
      if(!Array.isArray(edits.groups)||edits.groups.length>0)throw new ModelImportError('当前试色尚不能导出为模型，请恢复原始模型后发送');
    }
    const local=JSON.parse(boundedText(paths.view)) as LocalView;
    const viewer:SelfViewerState={schema:'self.transfer.viewer',version:1,camera:local.camera,target:local.target,up:local.up,fovDegrees:local.fovDegrees};
    return {name:star.name,plyPath:paths.gaussian,previewPath:star.previewPath,viewer:validViewer(viewer)?viewer:undefined};
  }
}

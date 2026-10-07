import { common } from '@kit.AbilityKit';
import { fileIo as fs } from '@kit.CoreFileKit';
import { PortraitStarStore } from '../services/PortraitStarStore';
import { AssetStore } from '../services/AssetStore';
import { ModelImportError, SelfViewerState, validViewer } from './SelfTransferContract';
import { boundedText } from './TransferFiles';
import { savedEditRevision } from './SelfTransferEdits';

interface LocalView {camera:number[];target:number[];up:number[];fovDegrees:number;}
export interface ExportSource {name:string;plyPath:string;directory:string;editsRevision:string;previewPath:string;viewer:SelfViewerState|undefined;}

export class ModelExportAdapter {
  private stars:PortraitStarStore;
  constructor(context:common.UIAbilityContext){this.stars=new PortraitStarStore(context,new AssetStore(context));}
  source(modelId:string):ExportSource{
    const star=this.stars.list().find((item)=>item.jobId===modelId);
    if(!star)throw new ModelImportError('当前模型尚未完整保存');
    const paths=this.stars.modelPaths(modelId),directory=paths.gaussian.substring(0,paths.gaussian.lastIndexOf('/'));
    const local=JSON.parse(boundedText(paths.view)) as LocalView;
    const viewer:SelfViewerState={schema:'self.transfer.viewer',version:1,camera:local.camera,target:local.target,up:local.up,fovDegrees:local.fovDegrees};
    return {name:star.name,plyPath:paths.gaussian,directory,editsRevision:savedEditRevision(directory),previewPath:star.previewPath,viewer:validViewer(viewer)?viewer:undefined};
  }
}

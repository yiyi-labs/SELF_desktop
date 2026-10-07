import { common, bundleManager } from '@kit.AbilityKit';
import { fileIo as fs } from '@kit.CoreFileKit';
import { util } from '@kit.ArkTS';
import { zlib } from '@kit.BasicServicesKit';
import { ModelExportAdapter } from './ModelExportAdapter';
import { ModelImportAdapter } from './ModelImportAdapter';
import { TransferModels } from './TransferState';
import { SELF_SCHEMA, SELF_PROTOCOL, SELF_PLY_CONTRACT, MODEL_ENTRY, VIEW_ENTRY, SelfTransferManifest,
  TransferAsset, SelfViewerState, PreparedTransfer, ImportedTransfer, PackageValidationError, validateManifest, validViewer } from './SelfTransferContract';
import { makeDir, fileSha256, ensureSpace, boundedText, writeText, removeTransferTree } from './TransferFiles';
import { inspectZip } from './SelfTransferZipGuard';
import { inspectPly } from './SelfTransferPly';

export class SelfTransferPackage implements TransferModels {
  readonly root:string;
  private exporter:ModelExportAdapter;
  private importer:ModelImportAdapter;
  private cached:PreparedTransfer|undefined=undefined;
  private preparing:Promise<PreparedTransfer>|undefined=undefined;
  private preparingKey:string='';
  private context:common.UIAbilityContext;
  constructor(context:common.UIAbilityContext){
    this.context=context;
    this.root=context.cacheDir+'/self_transfer';this.exporter=new ModelExportAdapter(context);this.importer=new ModelImportAdapter(context);
    for(const name of ['outgoing','incoming','staging'])makeDir(this.root+'/'+name);
    // Only abandoned transfer directories from earlier launches; never touch model data.
    this.cleanupOld();
  }
  private cleanupOld():void{
    for(const folder of ['outgoing','incoming','staging'])for(const name of fs.listFileSync(this.root+'/'+folder)){
      const path=this.root+'/'+folder+'/'+name;
      // Retain submitted packages for 24h because the sender receives no delivery receipt.
      if(Date.now()/1000-fs.statSync(path).mtime>86400){try{removeTransferTree(path,this.root);}catch(error){console.warn('SELF_TRANSFER_CACHE_CLEANUP '+String(error));}}
    }
  }
  prepare(modelId:string,revision:string):Promise<PreparedTransfer>{
    const key=modelId+':'+revision;
    if(this.preparing){
      if(this.preparingKey===key)return this.preparing;
      return this.preparing.catch(()=>undefined).then(()=>this.prepare(modelId,revision));
    }
    this.preparingKey=key;const operation=this.create(modelId,revision);this.preparing=operation;
    operation.finally(()=>{if(this.preparing===operation){this.preparing=undefined;this.preparingKey='';}}).catch(()=>{});
    return operation;
  }
  private async asset(role:string,path:string,absolute:string,required:boolean):Promise<TransferAsset>{
    return {role,path,required,byteLength:fs.statSync(absolute).size,sha256:await fileSha256(absolute)};
  }
  private async create(modelId:string,revision:string):Promise<PreparedTransfer>{
    const source=this.exporter.source(modelId),stat=fs.statSync(source.plyPath);
    if(this.cached?.modelId===modelId&&this.cached.revision===revision&&this.cached.sourceMtime===stat.mtime&&
      this.cached.sourceSize===stat.size&&fs.accessSync(this.cached.path))return this.cached;
    await ensureSpace(this.root,stat.size*2+1024*1024);
    await inspectPly(source.plyPath);
    const sourceHash=await fileSha256(source.plyPath),packageId=util.generateRandomUUID(true);
    const working=this.root+'/staging/export-'+packageId,bundle=this.root+'/outgoing/'+packageId;
    makeDir(working+'/model');makeDir(bundle);
    try{
      await fs.copyFile(source.plyPath,working+'/'+MODEL_ENTRY);
      const model=await this.asset('model',MODEL_ENTRY,working+'/'+MODEL_ENTRY,true),after=fs.statSync(source.plyPath);
      if(model.sha256!==sourceHash||model.byteLength!==stat.size||after.size!==stat.size||after.mtime!==stat.mtime)
        throw new PackageValidationError('模型正在保存，请完成保存后重试');
      const assets:TransferAsset[]=[model],optionalFeatures:string[]=[];
      if(source.previewPath&&fs.accessSync(source.previewPath)){
        makeDir(working+'/preview');await fs.copyFile(source.previewPath,working+'/preview/preview.png');
        assets.push(await this.asset('preview','preview/preview.png',working+'/preview/preview.png',false));optionalFeatures.push('preview.png');
      }
      if(source.viewer){makeDir(working+'/viewer');writeText(working+'/'+VIEW_ENTRY,JSON.stringify(source.viewer));
        assets.push(await this.asset('viewer',VIEW_ENTRY,working+'/'+VIEW_ENTRY,false));optionalFeatures.push('viewer.camera.v1');}
      const manifest:SelfTransferManifest={schema:SELF_SCHEMA,protocolVersion:SELF_PROTOCOL,packageId,createdAt:new Date().toISOString(),
        producer:{appFamily:'SELF',variant:this.context.applicationInfo.name==='com.self.mirror.harmony'?'olay_harmony':'olay',
          appVersion:bundleManager.getBundleInfoForSelfSync(bundleManager.BundleFlag.GET_BUNDLE_INFO_DEFAULT).versionName,bundleName:this.context.applicationInfo.name},
        model:{kind:'gaussian-splatting',format:'ply',formatContract:SELF_PLY_CONTRACT,entry:MODEL_ENTRY,byteLength:model.byteLength,sha256:model.sha256},
        displayName:source.name,assets,requiredFeatures:['model.ply'],optionalFeatures};
      validateManifest(manifest);writeText(working+'/manifest.json',JSON.stringify(manifest));
      const name=source.name.replace(/[\u0000-\u001f<>:"/\\|?*]/g,'_').slice(0,24)||'Model';
      const finalPath=bundle+'/SELF_'+name+'_'+packageId+'.self3d.zip',temporary=bundle+'/package.partial.zip';
      await zlib.compressFile(working,temporary,{level:zlib.CompressLevel.COMPRESS_LEVEL_NO_COMPRESSION,keepTopLevelFolder:false});
      const inspection=await inspectZip(temporary);
      if(inspection.entries.find((entry)=>entry.path===MODEL_ENTRY)?.size!==model.byteLength)throw new PackageValidationError('模型包生成不完整');
      fs.renameSync(temporary,finalPath);
      this.cached={path:finalPath,packageId,modelId,revision,sourcePath:source.plyPath,sourceSize:stat.size,sourceMtime:stat.mtime};
      console.info('SELF_PACKAGE_PREPARED '+packageId+' '+sourceHash);return this.cached;
    }catch(error){removeTransferTree(bundle,this.root);throw error as Error;}
    finally{removeTransferTree(working,this.root);}
  }
  async importPackage(path:string,cancelled:()=>boolean):Promise<ImportedTransfer>{
    // Every incoming path is first copied/resolved by the bridge into a session owned by this app.
    if(!path.startsWith(this.root+'/incoming/')||path.includes('/../')||path.includes('\\'))throw new PackageValidationError('模型文件不在接收目录');
    const session=path.substring(0,path.lastIndexOf('/')),stage=this.root+'/staging/import-'+util.generateRandomUUID(true);
    try{
      if(cancelled())throw new PackageValidationError('接收已取消');
      const zip=await inspectZip(path);await ensureSpace(this.root,zip.originalSize);
      makeDir(stage);await zlib.decompressFile(path,stage,{});
      if(cancelled())throw new PackageValidationError('接收已取消');
      const manifest=JSON.parse(boundedText(stage+'/manifest.json')) as SelfTransferManifest;validateManifest(manifest);
      for(const entry of zip.entries){
        const absolute=stage+'/'+entry.path,stat=fs.lstatSync(absolute);
        if(stat.isSymbolicLink()||(entry.path.endsWith('/')?!stat.isDirectory():!stat.isFile()))throw new PackageValidationError('模型包资产路径异常');
        if(!entry.path.endsWith('/')&&stat.size!==entry.size)throw new PackageValidationError('模型包文件长度损坏');
        if(entry.path!=='manifest.json'&&!entry.path.endsWith('/')&&!manifest.assets.some((asset)=>asset.path===entry.path))
          throw new PackageValidationError('模型包包含未登记资产');
      }
      for(const asset of manifest.assets){
        const absolute=stage+'/'+asset.path;
        if(!fs.accessSync(absolute)){if(asset.required)throw new PackageValidationError('模型包缺少必要文件');continue;}
        if(fs.statSync(absolute).size!==asset.byteLength||await fileSha256(absolute)!==asset.sha256)throw new PackageValidationError('模型文件损坏，SHA-256 校验未通过');
      }
      console.info('SELF_PACKAGE_VALIDATED '+manifest.packageId+' '+manifest.model.sha256);
      const ply=await inspectPly(stage+'/'+MODEL_ENTRY,cancelled);
      let viewer:SelfViewerState|undefined=undefined;
      if(manifest.assets.some((asset)=>asset.path===VIEW_ENTRY)&&fs.accessSync(stage+'/'+VIEW_ENTRY)){
        const parsed=JSON.parse(boundedText(stage+'/'+VIEW_ENTRY)) as SelfViewerState;if(validViewer(parsed))viewer=parsed;
      }
      await ensureSpace(this.root,1024*1024);
      return await this.importer.importValidated(stage,manifest,ply,viewer,cancelled);
    }catch(error){
      if(error instanceof PackageValidationError||error instanceof Error&&error.name==='ModelImportError')throw error;
      console.error('SELF_PACKAGE_FAILURE '+String(error));throw new PackageValidationError('模型包损坏或无法读取');
    }finally{
      if(fs.accessSync(stage))removeTransferTree(stage,this.root);
      // Sessions are isolated one-level directories; cleanup never walks out of incoming/.
      if(session.substring(0,session.lastIndexOf('/'))===this.root+'/incoming')removeTransferTree(session,this.root);
    }
  }
}

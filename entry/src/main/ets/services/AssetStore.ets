import { common } from '@kit.AbilityKit';
import { fileIo as fs } from '@kit.CoreFileKit';
import { photoAccessHelper } from '@kit.MediaLibraryKit';
export interface ImportedPhoto { id: string; path: string; mime: string; bytes: Uint8Array; }
export class AssetStore {
  private paths: Map<string,string> = new Map();
  private raw: Map<string,string> = new Map();
  private temporaryPaths: Set<string> = new Set();
  private context: common.UIAbilityContext;
  constructor(context: common.UIAbilityContext) {this.context=context;}
  registerRaw(id: string, rawPath: string): void { this.raw.set(id,rawPath); }
  registerPrivate(id: string, path: string): void {
    if(!path.startsWith(this.context.filesDir+'/')&&!path.startsWith(this.context.cacheDir+'/'))throw new Error('Asset outside private storage');
    this.paths.set(id,path);
    if(path.startsWith(this.context.cacheDir+'/'))this.temporaryPaths.add(path);
  }
  stageWorkspaceAsset(id:string,path:string,extension:string):void{
    if(!/^[a-zA-Z0-9_-]+$/.test(id)||!['mask','image'].includes(extension)||!path.startsWith(this.context.filesDir+'/works/'))throw new Error('Invalid workspace asset');
    const bytes=this.readFile(path),workingPath=this.context.cacheDir+'/'+id+'.'+extension;
    this.writeAtomic(workingPath,bytes.buffer as ArrayBuffer);this.registerPrivate(id,workingPath);
  }
  async read(id: string): Promise<Uint8Array> {
    const raw=this.raw.get(id);if(raw)return this.context.resourceManager.getRawFileContent(raw);
    const path=this.paths.get(id);if(!path)throw new Error('没有登记这个资产');return this.readFile(path);
  }
  readFile(path: string): Uint8Array {
    const f=fs.openSync(path,fs.OpenMode.READ_ONLY);
    try{const length=fs.statSync(f.fd).size;if(length<=0||length>33554432)throw new Error('文件为空或超过 32 MB');
      const bytes=new ArrayBuffer(length);let offset=0;
      while(offset<length){const part=new ArrayBuffer(length-offset);const read=fs.readSync(f.fd,part,{offset});if(read<=0)throw new Error('文件读取不完整');new Uint8Array(bytes).set(new Uint8Array(part,0,read),offset);offset+=read;}
      return new Uint8Array(bytes);
    }finally{fs.closeSync(f);}
  }
  writeAtomic(path: string, bytes: ArrayBuffer | string): void {
    if(!path.startsWith(this.context.filesDir+'/')&&!path.startsWith(this.context.cacheDir+'/'))throw new Error('Write outside private storage');
    const temp=path+'.tmp';const f=fs.openSync(temp,fs.OpenMode.CREATE|fs.OpenMode.READ_WRITE|fs.OpenMode.TRUNC);
    try{const written=fs.writeSync(f.fd,bytes);if(typeof bytes!=='string'&&written!==bytes.byteLength)throw new Error('Short write');fs.fsyncSync(f.fd);}
    catch(error){fs.closeSync(f);if(fs.accessSync(temp))fs.unlinkSync(temp);throw new Error(String(error));}
    fs.closeSync(f);fs.renameSync(temp,path);
  }
  saveMask(id: string, bytes: ArrayBuffer): string {
    if(!/^[a-zA-Z0-9_-]+$/.test(id))throw new Error('Invalid region id');
    const path=this.context.cacheDir+'/'+id+'.mask';this.writeAtomic(path,bytes);this.registerPrivate(id,path);return id+'.mask';
  }
  async pickPhoto(): Promise<ImportedPhoto | undefined> {
    const options=new photoAccessHelper.PhotoSelectOptions();options.MIMEType=photoAccessHelper.PhotoViewMIMETypes.IMAGE_TYPE;options.maxSelectNumber=1;
    const picker=new photoAccessHelper.PhotoViewPicker();const result=await picker.select(options);
    if(!result.photoUris.length)return undefined;
    const source=fs.openSync(result.photoUris[0],fs.OpenMode.READ_ONLY);const id='photo-'+Date.now(),path=this.context.cacheDir+'/'+id+'.image';
    try{fs.copyFileSync(source.fd,path);}finally{fs.closeSync(source);}
    try{const bytes=this.readFile(path);let mime='';
    if(bytes[0]===137&&bytes[1]===80&&bytes[2]===78&&bytes[3]===71)mime='image/png';
    if(bytes[0]===255&&bytes[1]===216)mime='image/jpeg';
    if(!mime)throw new Error('本版先支持 JPEG / PNG，请选择这两种格式');
    this.registerPrivate(id,path);return {id,path,mime,bytes};
    }catch(error){if(fs.accessSync(path))fs.unlinkSync(path);throw new Error(String(error));}
  }
  discardTemporary(id:string):void{const path=this.paths.get(id);if(path?.startsWith(this.context.cacheDir+'/')&&fs.accessSync(path))fs.unlinkSync(path);this.paths.delete(id);}
  cleanupTemporary(): void {
    this.temporaryPaths.forEach((path:string)=>{if(fs.accessSync(path))fs.unlinkSync(path);});this.temporaryPaths.clear();
    this.paths.clear();
  }
}

import { common } from '@kit.AbilityKit';
import { fileIo as fs } from '@kit.CoreFileKit';
import { AssetStore } from './AssetStore';
import { SavedWorkspace, RegionRecord, Protection } from '../domain/EditPlan';
import { SessionStore } from '../domain/SessionStore';
export interface WorkItem { id: string; label: string; savedAt: number; }
export class WorkspaceStore {
  private root: string;
  private context: common.UIAbilityContext;
  private assets: AssetStore;
  constructor(context: common.UIAbilityContext,assets: AssetStore) {
    this.context=context;this.assets=assets;
    this.root=context.filesDir+'/works';if(!fs.accessSync(this.root))fs.mkdirSync(this.root);
  }
  private directory(id: string): string { if(!/^work-[0-9]+$/.test(id))throw new Error('Invalid workspace id');return this.root+'/'+id; }
  list(): WorkItem[] {
    const out: WorkItem[]=[];
    for(const id of fs.listFileSync(this.root)){if(!/^work-[0-9]+$/.test(id))continue;
      try{const s=JSON.parse(fs.readTextSync(this.directory(id)+'/workspace.json')) as SavedWorkspace;out.push({id,label:s.label,savedAt:s.savedAt});}catch(error){}
    }
    return out.sort((a:WorkItem,b:WorkItem)=>b.savedAt-a.savedAt);
  }
  async save(session: SessionStore): Promise<WorkItem> {
    const id='work-'+Date.now(),dir=this.directory(id),s=session.serialize(id,session.sourceKind==='PHOTO'?'我的照片作品':'示例面容作品');
    fs.mkdirSync(dir);
    try{
      for(const region of s.regions){const bytes=await this.assets.read(region.regionId);this.assets.writeAtomic(dir+'/'+region.fileName,bytes.buffer as ArrayBuffer);}
      if(s.sourceKind==='PHOTO'){const bytes=await this.assets.read(s.assetId);this.assets.writeAtomic(dir+'/source.image',bytes.buffer as ArrayBuffer);s.sourceFile='source.image';}
      this.assets.writeAtomic(dir+'/workspace.json',JSON.stringify(s));
      return {id,label:s.label,savedAt:s.savedAt};
    }catch(error){this.delete(id);throw new Error(String(error));}
  }
  open(id: string): SavedWorkspace {
    const dir=this.directory(id),s=JSON.parse(fs.readTextSync(dir+'/workspace.json')) as SavedWorkspace;
    if(s.schemaVersion!==1||s.workspaceId!==id)throw new Error('作品元数据不匹配');
    if(s.sourceKind==='MESH'&&s.assetVersion!=='lee-r186-self2')throw new Error('示例资产版本不同，需要重新配准');
    for(const r of s.regions){if(!/^[a-zA-Z0-9_-]+\.mask$/.test(r.fileName)||r.assetVersion!==s.assetVersion||r.width!==s.width||r.height!==s.height)throw new Error('蒙版版本或尺寸不一致');
      if(!fs.accessSync(dir+'/'+r.fileName)||fs.statSync(dir+'/'+r.fileName).size!==r.width*r.height)throw new Error('作品蒙版缺失或损坏');
    }
    if(s.sourceKind==='PHOTO'){if(s.sourceFile!=='source.image'||!fs.accessSync(dir+'/source.image'))throw new Error('原照片缺失');this.assets.stageWorkspaceAsset(s.assetId,dir+'/source.image','image');}
    // The current unsaved session must not depend on a saved record that the user can delete.
    for(const r of s.regions)this.assets.stageWorkspaceAsset(r.regionId,dir+'/'+r.fileName,'mask');
    return s;
  }
  delete(id: string): void {
    const dir=this.directory(id);if(!fs.accessSync(dir))return;
    // Only this application's known flat workspace directory, never paths supplied by Web.
    for(const name of fs.listFileSync(dir)){if(name.includes('/')||name.includes('..'))throw new Error('Unexpected workspace entry');fs.unlinkSync(dir+'/'+name);}
    fs.rmdirSync(dir);
  }
  async savePreference(session: SessionStore): Promise<void> {
    if(!session.protection)throw new Error('先建立保护范围');
    if(session.sourceKind!=='MESH')throw new Error('个人照片保护随作品保存；本版长期跨会话偏好仅支持这份示例资产');
    if(session.protection.anchorOperations.length>0)throw new Error('当前效果保护随作品保存；长期偏好使用原始基准');
    const bytesId=session.protection.regionId;
    const bytes=await this.assets.read(bytesId);
      this.assets.writeAtomic(this.context.filesDir+'/preference.mask',bytes.buffer as ArrayBuffer);
      const savedProtection: Protection={ruleId:session.protection.ruleId,regionId:'preference',anchorRevision:0,anchorOperations:[],persistent:true};
      const p: SavedPreference={assetVersion:session.assetVersion,protection:savedProtection};
      this.assets.writeAtomic(this.context.filesDir+'/preference.json',JSON.stringify(p));
    session.protection.persistent=true;
  }
  loadPreference(session: SessionStore): void {
    const file=this.context.filesDir+'/preference.json';if(!fs.accessSync(file)||session.sourceKind!=='MESH')return;
    const p=JSON.parse(fs.readTextSync(file)) as SavedPreference;
    if(p.assetVersion!==session.assetVersion||!fs.accessSync(this.context.filesDir+'/preference.mask'))return;
    if(session.protection&&!session.protection.persistent)throw new Error('这份作品有独立保护，暂不能与当前长期保护合并；请先明确管理保护规则');
    const region:RegionRecord={regionId:'preference',assetId:session.assetId,assetVersion:session.assetVersion,width:1024,height:1024,semantic:'manual',fileName:'preference.mask'};
    this.assets.registerPrivate('preference',this.context.filesDir+'/preference.mask');session.regions.push(region);session.protection=p.protection;
  }
  deletePreference(): void { for(const name of ['preference.json','preference.mask']){const path=this.context.filesDir+'/'+name;if(fs.accessSync(path))fs.unlinkSync(path);} }
  deletePersonalAsset(assetId:string):void{
    if(!assetId.startsWith('photo-'))throw new Error('只能删除个人照片资产');
    for(const item of this.list()){
      const s=JSON.parse(fs.readTextSync(this.directory(item.id)+'/workspace.json')) as SavedWorkspace;
      if(s.assetId===assetId)this.delete(item.id);
    }
    const exported=this.context.filesDir+'/self-export.png';if(fs.accessSync(exported))fs.unlinkSync(exported);
    this.assets.cleanupTemporary();
  }
  saveNote(text: string): void { if(text.length>2000)throw new Error('记录请控制在 2000 字以内');this.assets.writeAtomic(this.context.filesDir+'/private-note.txt',text); }
  readNote(): string { const p=this.context.filesDir+'/private-note.txt';return fs.accessSync(p)?fs.readTextSync(p):''; }
  deleteNote(): void { const p=this.context.filesDir+'/private-note.txt';if(fs.accessSync(p))fs.unlinkSync(p); }
}
interface SavedPreference {assetVersion: string;protection: Protection;}

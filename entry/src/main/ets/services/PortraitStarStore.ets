import { common } from '@kit.AbilityKit';
import { fileIo as fs } from '@kit.CoreFileKit';
import { AssetStore } from './AssetStore';

export interface PortraitStar { jobId:string; name:string; createdAt:number; previewPath:string; preview3dPath:string; }
export interface PortraitModelPaths { gaussian:string; view:string; }
interface StoredStar { jobId:string; name:string; createdAt:number; }
interface StarIndex { schemaVersion:number; stars:StoredStar[]; }

/** Only indexes verified app-private reconstructions; the original assets stay in models/. */
export class PortraitStarStore {
  private root:string;
  private indexPath:string;
  private assets:AssetStore;
  constructor(context:common.UIAbilityContext,assets:AssetStore){
    this.root=context.filesDir+'/models';this.indexPath=context.filesDir+'/portrait-stars.json';
    this.assets=assets;
  }
  private validId(id:string):boolean{return /^[a-f0-9]{32}$/.test(id);}
  static cleanName(value:string):string{
    const cleaned=value.trim().replace(/[\u0000-\u001f\u007f<>\\/]/g,'').slice(0,24).trim();
    return cleaned||'未命名的星辰';
  }
  private directory(id:string):string{
    if(!this.validId(id))throw new Error('星辰编号无效');
    return this.root+'/'+id;
  }
  modelPaths(id:string):PortraitModelPaths{
    const directory=this.directory(id);
    return {gaussian:directory+'/portrait.gaussian.ply',view:directory+'/portrait.view.json'};
  }
  previewPath(id:string):string{return this.directory(id)+'/portrait.preview.png';}
  preview3dPath(id:string):string{return this.directory(id)+'/portrait.preview.gaussian.ply';}
  private complete(id:string):boolean{
    if(!this.validId(id))return false;
    const paths=this.modelPaths(id);
    return fs.accessSync(paths.gaussian)&&fs.accessSync(paths.view)&&
      fs.statSync(paths.gaussian).size>=4096&&fs.statSync(paths.view).size>=128;
  }
  private read():StoredStar[]{
    if(!fs.accessSync(this.indexPath))return [];
    try{
      const index=JSON.parse(fs.readTextSync(this.indexPath)) as StarIndex;
      if(index.schemaVersion!==1||!Array.isArray(index.stars))return [];
      return index.stars.filter((star:StoredStar)=>this.validId(star.jobId)&&
        typeof star.name==='string'&&Number.isFinite(star.createdAt));
    }catch(_){return [];}
  }
  private write(stars:StoredStar[]):void{
    this.assets.writeAtomic(this.indexPath,JSON.stringify({schemaVersion:1,stars} as StarIndex));
  }
  list():PortraitStar[]{
    const saved=this.read();let changed=false;
    if(fs.accessSync(this.root)){
      for(const id of fs.listFileSync(this.root)){
        if(!this.complete(id)||saved.some((star:StoredStar)=>star.jobId===id))continue;
        saved.push({jobId:id,name:'我的星辰 '+(saved.length+1),createdAt:Date.now()-saved.length});changed=true;
      }
    }
    if(changed)this.write(saved);
    return saved.filter((star:StoredStar)=>this.complete(star.jobId))
      .sort((a:StoredStar,b:StoredStar)=>b.createdAt-a.createdAt)
      .map((star:StoredStar)=>({jobId:star.jobId,name:star.name,createdAt:star.createdAt,
        previewPath:fs.accessSync(this.previewPath(star.jobId))?this.previewPath(star.jobId):'',
        preview3dPath:fs.accessSync(this.preview3dPath(star.jobId))?this.preview3dPath(star.jobId):''} as PortraitStar));
  }
  upsert(id:string,name:string):void{
    if(!this.complete(id))throw new Error('星辰尚未完整保存');
    const stars=this.read(),existing=stars.find((star:StoredStar)=>star.jobId===id);
    if(existing)existing.name=PortraitStarStore.cleanName(name);
    else stars.push({jobId:id,name:PortraitStarStore.cleanName(name),createdAt:Date.now()});
    this.write(stars);
  }
}

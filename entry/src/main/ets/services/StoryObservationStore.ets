import { common } from '@kit.AbilityKit';
import { fileIo as fs } from '@kit.CoreFileKit';
import { AssetStore } from './AssetStore';
import { GsViewSnapshot } from '../bridge/RendererBridge';

export interface StoryObservation {
  recordId:string;messageId:string;userQuote:string;starId:string;assetId:string;
  createdAt:number;view?:GsViewSnapshot;editGroupId?:string;recallAllowed:boolean;
}
interface ObservationFile {schemaVersion:number;assetId:string;records:StoryObservation[];}

/** Separate from edit history and persistent preferences. No image is stored. */
export class StoryObservationStore {
  private assets:AssetStore;
  private context:common.UIAbilityContext;
  constructor(context:common.UIAbilityContext){this.context=context;this.assets=new AssetStore(context);}
  private path(assetId:string):string{
    if(!/^[a-f0-9]{32}$/.test(assetId))throw new Error('Invalid asset id');
    return this.context.filesDir+'/models/'+assetId+'/story.observations.v1.json';
  }
  list(assetId:string):StoryObservation[]{
    try{
      const path=this.path(assetId);
      if(!fs.accessSync(path))return [];
      const value=JSON.parse(fs.readTextSync(path)) as ObservationFile;
      if(value.schemaVersion!==1||value.assetId!==assetId||!Array.isArray(value.records)||value.records.length>50)
        throw new Error('Invalid observation file');
      return value.records.filter((item:StoryObservation)=>item.assetId===assetId&&item.starId===assetId&&
        item.userQuote.length>0&&item.userQuote.length<=500);
    }catch(error){console.warn('SELF_STORY_OBSERVATIONS_READ_FAILED '+String(error));return [];}
  }
  save(assetId:string,record:StoryObservation):StoryObservation[]{
    if(record.assetId!==assetId||record.starId!==assetId||!record.userQuote.trim()||record.userQuote.length>500)
      throw new Error('Invalid observation');
    const records=this.list(assetId);
    if(records.length>=50)throw new Error('这颗星辰的文字记录已满');
    records.push(record);
    this.assets.writeAtomic(this.path(assetId),JSON.stringify({schemaVersion:1,assetId,records} as ObservationFile));
    return records;
  }
  remove(assetId:string,recordId:string):StoryObservation[]{
    const records=this.list(assetId).filter((item:StoryObservation)=>item.recordId!==recordId);
    this.assets.writeAtomic(this.path(assetId),JSON.stringify({schemaVersion:1,assetId,records} as ObservationFile));
    return records;
  }
}

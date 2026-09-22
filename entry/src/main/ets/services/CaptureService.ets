import { camera, cameraPicker } from '@kit.CameraKit';
import { common } from '@kit.AbilityKit';
import { fileIo as fs, fileUri } from '@kit.CoreFileKit';

export interface CaptureRecord {name:string;bytes:number;}

/** System camera picker: explicit user capture, private file, no implicit upload. */
export class CaptureService {
  private context:common.UIAbilityContext;
  constructor(context:common.UIAbilityContext){this.context=context;}
  list():CaptureRecord[]{
    const root=this.context.filesDir+'/captures';if(!fs.accessSync(root))return [];
    return fs.listFileSync(root).filter((name:string)=>/^capture-[0-9]+\.mp4$/.test(name)).map((name:string)=>({name,bytes:fs.statSync(root+'/'+name).size} as CaptureRecord)).sort((a:CaptureRecord,b:CaptureRecord)=>b.name.localeCompare(a.name));
  }
  delete(name:string):void{
    if(!/^capture-[0-9]+\.mp4$/.test(name))throw new Error('无效视频记录');
    const path=this.context.filesDir+'/captures/'+name;
    if(fs.accessSync(path))fs.unlinkSync(path);if(fs.accessSync(path+'.json'))fs.unlinkSync(path+'.json');
  }
  async record():Promise<string>{
    const root=this.context.filesDir+'/captures';
    if(!fs.accessSync(root))fs.mkdirSync(root);
    const path=root+'/capture-'+Date.now()+'.mp4';
    const file=fs.openSync(path,fs.OpenMode.CREATE|fs.OpenMode.READ_WRITE);fs.closeSync(file);
    try{
      const result=await cameraPicker.pick(this.context,[cameraPicker.PickerMediaType.VIDEO],{
        cameraPosition:camera.CameraPosition.CAMERA_POSITION_BACK,
        saveUri:fileUri.getUriFromPath(path),videoDuration:45
      });
      if(!result)throw new Error('当前系统相机没有返回拍摄结果，未保存视频。请在支持相机的真机重试。');
      if(result.resultCode!==0||result.mediaType!==cameraPicker.PickerMediaType.VIDEO||fs.statSync(path).size===0){fs.unlinkSync(path);return '';}
      const metadata=fs.openSync(path+'.json',fs.OpenMode.CREATE|fs.OpenMode.READ_WRITE);
      try{fs.writeSync(metadata.fd,JSON.stringify({schemaVersion:1,source:'system-camera-video',createdAt:Date.now(),reconstructionStatus:'not-reconstructed',poseData:false,private:true}));}finally{fs.closeSync(metadata);}
      return path;
    }catch(e){if(fs.accessSync(path)&&fs.statSync(path).size===0)fs.unlinkSync(path);throw new Error((e as Error).message);}
  }
}

import { common } from '@kit.AbilityKit';
import { fileIo as fs } from '@kit.CoreFileKit';
import { UiText } from './UiText';

export type CloudConsentDecision = 'unknown' | 'allowed' | 'denied';

interface SavedCloudConsent {
  schemaVersion:number;
  dataScopeVersion:number;
  decision:CloudConsentDecision;
}

/** One choice for cloud dialogue and portrait-aware planning, separate from UI preferences. */
export class CloudConsentStore {
  private static readonly fileName:string='/cloud-dialogue-consent.json';
  static load(context:common.UIAbilityContext):CloudConsentDecision {
    try {
      const saved=JSON.parse(fs.readTextSync(context.filesDir+CloudConsentStore.fileName)) as SavedCloudConsent;
      if(saved.schemaVersion===1&&saved.dataScopeVersion===1&&
        (saved.decision==='allowed'||saved.decision==='denied'))return saved.decision;
    } catch(_) {}
    return 'unknown';
  }
  static allowed(context:common.UIAbilityContext):boolean {
    return CloudConsentStore.load(context)==='allowed';
  }
  static save(context:common.UIAbilityContext,decision:CloudConsentDecision):boolean {
    if(decision==='unknown')return false;
    const path=context.filesDir+CloudConsentStore.fileName,temp=path+'.tmp';
    const saved:SavedCloudConsent={schemaVersion:1,dataScopeVersion:1,decision};
    try {
      const file=fs.openSync(temp,fs.OpenMode.CREATE|fs.OpenMode.READ_WRITE|fs.OpenMode.TRUNC);
      try {fs.writeSync(file.fd,JSON.stringify(saved));} finally {fs.closeSync(file);}
      fs.renameSync(temp,path);
      return CloudConsentStore.load(context)===decision;
    } catch(error) {
      console.error('SELF_CLOUD_CONSENT_SAVE_FAILED '+String(error));
      return false;
    }
  }
  static introduction(language:string):string {
    if(language==='en')
      return 'Before our first conversation: your words and recent replies go from this device directly to DeepSeek’s official service. Asking about a portrait or editing a selection also sends its current still view. Camera video and 3D model files stay here, and no computer relays anything. Your choice is remembered; turn it off in Settings at any time. Each edit still needs your approval.';
    return UiText.get('开始对话前，先由你决定一次：文字和最近的对话会由本设备直接发送给 DeepSeek 官方服务；针对面容画面提问或圈选修改时，还会附上当前静态画面。相机视频和立体模型文件不会随对话发送，也不经过任何电脑中转。选择会保留，可随时在设置中关闭；每次修改仍由你确认。',language);
  }
}

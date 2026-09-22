import { UIAbility } from '@kit.AbilityKit';
import { deviceInfo } from '@kit.BasicServicesKit';
import { window } from '@kit.ArkUI';
export default class EntryAbility extends UIAbility {
  onForeground():void{AppStorage.setOrCreate('selfForeground',true);}
  onBackground():void{AppStorage.setOrCreate('selfForeground',false);}
  onWindowStageCreate(stage: window.WindowStage): void {
    if(deviceInfo.deviceType==='phone'||deviceInfo.deviceType==='tablet')stage.getMainWindowSync().setPreferredOrientation(window.Orientation.AUTO_ROTATION_RESTRICTED).catch((e:Error)=>console.warn('SELF_ORIENTATION '+e.message));
    stage.loadContent('pages/SelfMirrorPage');
  }
}

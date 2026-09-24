import { UIAbility } from '@kit.AbilityKit';
import { deviceInfo } from '@kit.BasicServicesKit';
import { window } from '@kit.ArkUI';
export default class EntryAbility extends UIAbility {
  onForeground():void{AppStorage.setOrCreate('selfForeground',true);}
  onBackground():void{AppStorage.setOrCreate('selfForeground',false);}
  onWindowStageCreate(stage: window.WindowStage): void {
    const main=stage.getMainWindowSync();
    if(deviceInfo.deviceType==='phone'||deviceInfo.deviceType==='tablet'){
      main.setPreferredOrientation(window.Orientation.AUTO_ROTATION_RESTRICTED).catch((e:Error)=>console.warn('SELF_ORIENTATION '+e.message));
      main.setWindowLayoutFullScreen(true).catch((e:Error)=>console.warn('SELF_IMMERSIVE '+e.message));
      main.setWindowSystemBarProperties({statusBarColor:'#00000000',navigationBarColor:'#00000000',statusBarContentColor:'#FFFFFF',navigationBarContentColor:'#FFFFFF'}).catch((e:Error)=>console.warn('SELF_SYSTEM_BARS '+e.message));
    }
    stage.loadContent('pages/SelfMirrorPage');
  }
}

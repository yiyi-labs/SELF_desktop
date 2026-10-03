import { UIAbility } from '@kit.AbilityKit';
import { deviceInfo } from '@kit.BasicServicesKit';
import { window } from '@kit.ArkUI';
import { Want, AbilityConstant } from '@kit.AbilityKit';
import { ReconstructionLiveActivity } from '../services/ReconstructionLiveActivity';
export default class EntryAbility extends UIAbility {
  onCreate(want:Want):void{this.openWaiting(want);}
  onNewWant(want:Want,_launchParam:AbilityConstant.LaunchParam):void{this.openWaiting(want);}
  private openWaiting(want:Want):void{
    if(want.parameters?.reconstructionWaiting===true)
      AppStorage.setOrCreate('selfReconstructionOpen',(AppStorage.get<number>('selfReconstructionOpen')||0)+1);
  }
  onForeground():void{AppStorage.setOrCreate('selfForeground',true);ReconstructionLiveActivity.shared().setForeground(true);}
  onBackground():void{AppStorage.setOrCreate('selfForeground',false);ReconstructionLiveActivity.shared().setForeground(false);}
  onDestroy():void{ReconstructionLiveActivity.shared().dispose();}
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

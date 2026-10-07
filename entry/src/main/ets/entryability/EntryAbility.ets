import { UIAbility } from '@kit.AbilityKit';
import { SelfTransferRuntime } from '../transfer/SelfTransferRuntime';
import { deviceInfo } from '@kit.BasicServicesKit';
import { window } from '@kit.ArkUI';
import { Want, AbilityConstant } from '@kit.AbilityKit';
import { ReconstructionLiveActivity } from '../services/ReconstructionLiveActivity';
export default class EntryAbility extends UIAbility {
  private selfTransfer:SelfTransferRuntime|undefined=undefined;
  private selfTransferForeground:boolean=false;
  private selfTransferWant:Want|undefined=undefined;
  private handleTransferWant(want:Want):void{
    if(want.action!=='ohos.want.action.sendData'&&want.action!=='ohos.want.action.viewData')return;
    if(this.selfTransfer)this.selfTransfer.handleWant(want);else this.selfTransferWant=want;
  }
  onWindowStageDestroy():void{this.selfTransfer?.dispose();this.selfTransfer=undefined;}
  onCreate(want:Want):void{this.openWaiting(want);}
  onNewWant(want:Want,_launchParam:AbilityConstant.LaunchParam):void{this.openWaiting(want);}
  private openWaiting(want:Want):void{
    this.handleTransferWant(want);
    if(want.parameters?.reconstructionWaiting===true)
      AppStorage.setOrCreate('selfReconstructionOpen',(AppStorage.get<number>('selfReconstructionOpen')||0)+1);
  }
  onForeground():void{this.selfTransferForeground=true;this.selfTransfer?.setForeground(true);AppStorage.setOrCreate('selfForeground',true);ReconstructionLiveActivity.shared().setForeground(true);}
  onBackground():void{this.selfTransferForeground=false;this.selfTransfer?.setForeground(false);AppStorage.setOrCreate('selfForeground',false);ReconstructionLiveActivity.shared().setForeground(false);}
  onDestroy():void{this.selfTransfer?.dispose();this.selfTransfer=undefined;ReconstructionLiveActivity.shared().dispose();}
  onWindowStageCreate(stage: window.WindowStage): void {
    const main=stage.getMainWindowSync();
    this.selfTransfer=SelfTransferRuntime.bind(this.context,main.getWindowProperties().id);
    this.selfTransfer.setForeground(this.selfTransferForeground);
    if(this.selfTransferWant){this.selfTransfer.handleWant(this.selfTransferWant);this.selfTransferWant=undefined;}
    if(deviceInfo.deviceType==='phone'||deviceInfo.deviceType==='tablet'){
      main.setPreferredOrientation(window.Orientation.AUTO_ROTATION_RESTRICTED).catch((e:Error)=>console.warn('SELF_ORIENTATION '+e.message));
      main.setWindowLayoutFullScreen(true).catch((e:Error)=>console.warn('SELF_IMMERSIVE '+e.message));
      main.setWindowSystemBarProperties({statusBarColor:'#00000000',navigationBarColor:'#00000000',statusBarContentColor:'#FFFFFF',navigationBarContentColor:'#FFFFFF'}).catch((e:Error)=>console.warn('SELF_SYSTEM_BARS '+e.message));
    }
    stage.loadContent('pages/SelfMirrorPage');
  }
}

import { UIAbility } from '@kit.AbilityKit';
import { window } from '@kit.ArkUI';
export default class EntryAbility extends UIAbility {
  onForeground():void{AppStorage.setOrCreate('selfForeground',true);}
  onBackground():void{AppStorage.setOrCreate('selfForeground',false);}
  onWindowStageCreate(stage: window.WindowStage): void {
    stage.loadContent('pages/SelfMirrorPage');
  }
}

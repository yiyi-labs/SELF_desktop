import { UIAbility } from '@kit.AbilityKit';
import { window } from '@kit.ArkUI';
/** Isolated native migration gate. Does not replace the existing editor or edit its saved work. */
export default class NativeProbeAbility extends UIAbility {
  onWindowStageCreate(stage: window.WindowStage): void {
    stage.loadContent('pages/NativeEsProbe', (error) => {
      if(error.code)console.error('SELF_NATIVE_LOAD_ERROR '+JSON.stringify(error));
    });
  }
}

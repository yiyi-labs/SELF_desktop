import { UIAbility } from '@kit.AbilityKit';
import { window } from '@kit.ArkUI';
/** Test package only: production artwork on a solid background, no camera. */
export default class GuideTestAbility extends UIAbility {
 onWindowStageCreate(stage:window.WindowStage):void{stage.loadContent('pages/GuideFixture');}
}

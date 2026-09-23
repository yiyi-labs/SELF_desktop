import { CaptureMoveHint } from '../../../main/ets/pages/CaptureMoveHint';
@Entry
@ComponentV2
struct GuideFixture {
 build(){Stack(){CaptureMoveHint({motion:true,language:'zh',hintSize:360})}.width('100%').height('100%').backgroundColor('#526171')}
}

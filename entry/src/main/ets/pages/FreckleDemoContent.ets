import { FreckleDemo, FreckleDemoLook } from '../domain/FreckleDemo';
import { OlayPhotoRepository } from '../services/OlayPhotoRepository';

/** Content only: the enclosing normal reply retains its background, anchor and scrolling. */
@Component
export struct FreckleDemoContent {
  @Prop activeLook:string='';
  @Prop notice:string='';
  @Prop showCare:boolean=true;
  onTry:(id:string)=>void=()=>{};
  onProduct:(id:string)=>void=()=>{};
  onDismissCare:()=>void=()=>{};
  build(){
    Column({space:10}){
      Row(){Text('换一种看自己的方式').fontSize(13).fontWeight(FontWeight.Medium).fontColor('#E7F0FC')
        .layoutWeight(1);Text('保留雀斑').fontSize(10).fontColor('#BED7EA')}
      Row({space:7}){
        ForEach(FreckleDemo.looks(),(look:FreckleDemoLook)=>{
          Column({space:5}){
            Image($rawfile('ui/'+look.image)).width('100%').height(105).objectFit(ImageFit.Cover)
              .borderRadius(12).accessibilityText(look.title+'，保留相同雀斑的真实局部皮肤照片')
            Text(look.title).fontSize(12).fontWeight(FontWeight.Medium).fontColor('#F0F5FF')
            Text(look.note).fontSize(9).fontColor('#C0D1E5').maxLines(2).textAlign(TextAlign.Center)
            Button(this.activeLook===look.id?'已选择':'试在脸上')
              .id('freckle-try-'+look.id).fontSize(10).height(29).width('100%').padding(0)
              .fontColor('#F5F8FF').backgroundColor(this.activeLook===look.id?'#6879A0':'#344C68')
              .borderRadius(15).onClick(()=>this.onTry(look.id))
          }.layoutWeight(1).padding(6).borderRadius(16).backgroundColor('#263C5866')
            .border({width:1,color:this.activeLook===look.id?'#B8CDE8':'#657F9D66'})
        },(look:FreckleDemoLook)=>look.id)
      }.width('100%').alignItems(VerticalAlign.Top)
      Text('真实皮肤照片 · 光色示意，非护理功效。试色功能稍后开放。')
        .fontSize(10).lineHeight(15).fontColor('#B9CDE4').width('100%')
      Row({space:3}){
        Text('照片：Drymartini38 · CC BY-SA 4.0（裁切 / 调色）')
          .fontSize(9).fontColor('#AFC2D7').layoutWeight(1)
        Hyperlink('https://commons.wikimedia.org/wiki/File:FrecklesAfterSummertime.jpg','↗')
          .color('#AFC2D7').width(22).height(22).accessibilityText('查看照片来源与许可')
      }.width('100%')
      if(this.notice){Text(this.notice).id('freckle-preview-notice').fontSize(12).lineHeight(18)
        .fontColor('#DCEAFF').width('100%')}
      if(this.showCare){
        Column({space:9}){
          Row(){Text('OLAY · 日常照顾').fontSize(12).fontWeight(FontWeight.Medium).fontColor('#EDF3FF')
            .layoutWeight(1)
            Button('收起').fontSize(10).height(26).fontColor('#BED0E6').backgroundColor('#00000000')
              .onClick(()=>this.onDismissCare())}
          Text('保留雀斑，也可以好好照顾皮肤。先做好防晒和保湿；想了解淡斑护理，再慢慢选。')
            .fontSize(12).lineHeight(18).fontColor('#D9E7F7').width('100%')
          Row({space:9}){
            Image(OlayPhotoRepository.thumbnail('CN013')).width(42).height(48).objectFit(ImageFit.Contain)
            Column({space:3}){
              Text('小白伞防晒').fontSize(12).fontColor('#F0F5FF')
              Text('日间护理候选 · 用法以包装为准').fontSize(10).fontColor('#BED0E6')
            }.alignItems(HorizontalAlign.Start).layoutWeight(1)
            Button('了解').id('freckle-product-sunscreen').height(29).fontSize(11)
              .fontColor('#E5EEFA').backgroundColor('#344E6B').borderRadius(15)
              .onClick(()=>this.onProduct('CN013'))
          }.width('100%')
          Row({space:9}){
            Image(OlayPhotoRepository.thumbnail('CN019')).width(42).height(48).objectFit(ImageFit.Contain)
            Column({space:3}){
              Text('淡斑小白瓶').fontSize(12).fontColor('#F0F5FF')
              Text('可选了解 · 先核对代际与肤质').fontSize(10).fontColor('#BED0E6')
            }.alignItems(HorizontalAlign.Start).layoutWeight(1)
            Button('了解').id('freckle-product-serum').height(29).fontSize(11)
              .fontColor('#E5EEFA').backgroundColor('#344E6B').borderRadius(15)
              .onClick(()=>this.onProduct('CN019'))
          }.width('100%')
          Text('初次使用先小范围试用；不适就停用。护理效果因人而异，不承诺消除雀斑。')
            .fontSize(10).lineHeight(15).fontColor('#B9CDE4').width('100%')
        }.padding(11).width('100%').backgroundColor('#263C58D9')
          .border({width:1,color:'#7896BA'}).borderRadius(16)
      }
    }.alignItems(HorizontalAlign.Start).width('100%')
  }
}

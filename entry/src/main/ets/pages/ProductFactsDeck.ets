import { UiText } from '../services/UiText';
import { ProductRecord,ProductRepository } from '../services/ProductRepository';

@Component
export struct ProductFactsDeck {
 @StorageLink('selfLanguage') language:string='zh';
 private tr(value:string):string{return UiText.get(value,this.language);}
 @Prop product:ProductRecord=ProductRepository.records()[0];
 @Prop motion:boolean=true;
 @State active:number=-1;
 private title(index:number):string{return ['要点','配方','来源'][index];}
 private summary():string{
  if(this.product.name.includes('淡纹'))return '名称标注\n淡纹护理';
  if(this.product.name.includes('淡斑'))return '名称标注\n淡斑精华';
  if(this.product.name.includes('水光'))return '名称标注\n水光精华';
  if(this.product.name.includes('美白'))return '名称标注\n美白护理';
  return '面霜系列\n按肤感选择';
 }
 private choose(index:number):void{this.getUIContext().animateTo({duration:this.motion?260:0,curve:Curve.EaseOut},()=>{this.active=this.active===index?-1:index;});}
 @Builder glyph(index:number){
  Stack(){
   Circle().fill(index===0?'#F1DFD7':index===1?'#E7DDEF':'#DEE7EF').width(38).height(38)
   if(index===0){Ellipse().width(13).height(22).fill('#B895AB').rotate({angle:32})}
   if(index===1){Row({space:3}){Circle().width(9).height(9).fill('#A78DB9');Circle().width(13).height(13).fill('#BEA9C9');Circle().width(7).height(7).fill('#8D739F')}}
   if(index===2){Rect().width(17).height(21).radius(3).fill('#9CACBC');Text(this.tr('✓')).fontSize(14).fontColor(Color.White)}
  }.width(38).height(38)
 }
 build(){
  Stack({alignContent:Alignment.TopStart}){
   ForEach([0,1,2],(index:number)=>{
    Column({space:7}){
     Row({space:5}){this.glyph(index);Text(this.tr(this.title(index))).fontSize(12).fontColor('#6F5F7B')}.width('100%')
     if(this.active===index){
      if(index===0){Text(this.tr(this.summary())).fontSize(12).lineHeight(20).fontColor('#5F4F6B');Text(this.tr('不代表实测功效')).fontSize(9).fontColor('#A496AA')}
      if(index===1){Text(this.tr('等待核对\n实物成分表')).fontSize(12).lineHeight(20).fontColor('#5F4F6B');Text(this.tr('不推断配比')).fontSize(9).fontColor('#A496AA')}
      if(index===2){Text(this.tr('大陆渠道\n'+this.product.retrievedAt)).fontSize(11).lineHeight(19).fontColor('#5F4F6B');Text(this.tr('长按复制来源')).fontSize(9).fontColor('#A496AA');Text(this.tr(this.product.source)).fontSize(8).maxLines(2).fontColor('#93839D').copyOption(CopyOptions.LocalDevice)}
      Text(this.tr('轻点收起')).fontSize(9).fontColor('#A496AA')
     }
    }.id('product-fact-'+index).padding(9).width('100%').height(this.active===index?194:66).alignItems(HorizontalAlign.Start)
     .backgroundColor(index===0?'#FFFDFC':index===1?'#F3EEF8':'#EBF0F7').border({width:1,color:'#F8FFFFFF'}).borderRadius(18)
     .shadow({radius:this.active===index?12:5,color:'#16665074',offsetY:3})
     .rotate({angle:this.active===index?0:(index-1)*3}).position({x:0,y:this.active<0?index*37:this.active===index?0:8+index*5})
     .zIndex(this.active===index?5:index).onClick(()=>this.choose(index))
   },(index:number)=>String(index))
  }.id('product-facts-deck').width(112).height(210)
 }
}

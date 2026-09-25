import { OlayDiscoveryItem, OlayDiscoveryRepository } from '../services/OlayDiscoveryRepository';

/** Source-linked product identities beside the portrait; never drives GS colours. */
@Component
export struct OlayLibrary {
  @Prop language:string='zh';
  @Prop viewportWidth:number=400;
  @Prop viewportHeight:number=600;
  onClose:()=>void=()=>{};
  @State section:string='brand';
  @State selectedId:string='';
  @State week:number=0;

  private label(zh:string,en:string):string{return this.language==='en'?en:zh;}
  private panelWidth():number{return this.viewportWidth>=840?Math.min(340,this.viewportWidth-32):this.viewportWidth-24;}
  private panelHeight():number{return this.viewportWidth>=840?Math.min(this.viewportHeight*.52,400):Math.min(this.viewportHeight*.42,390);}
  private records():OlayDiscoveryItem[]{return OlayDiscoveryRepository.records().filter((p:OlayDiscoveryItem)=>p.section===this.section);}
  private selected():OlayDiscoveryItem|undefined{return OlayDiscoveryRepository.records().find((p:OlayDiscoveryItem)=>p.id===this.selectedId);}
  private hasPhoto(id:string):boolean{return id==='CN001'||id==='CN002'||id==='CN003'||id==='CN004';}
  private productPhoto(id:string):Resource{
    if(id==='CN001')return $r('app.media.olay_cn001');
    if(id==='CN002')return $r('app.media.olay_cn002');
    if(id==='CN003')return $r('app.media.olay_cn003');
    return $r('app.media.olay_cn004');
  }
  private category(value:string):string{
    if(value==='cream')return this.label('面霜','Cream');
    if(value==='serum')return this.label('精华','Serum');
    if(value==='toner')return this.label('精华水','Toner');
    if(value==='emulsion')return this.label('乳液','Lotion');
    if(value==='eye')return this.label('眼周护理','Eye care');
    if(value==='sunscreen')return this.label('防晒','Sun care');
    if(value==='cleanser')return this.label('洁面','Cleanser');
    if(value==='mask')return this.label('面膜','Mask');
    if(value==='set')return this.label('组合','Set');
    return this.label('护理','Care');
  }
  private routine(value:string):string{
    if(value==='cleanser')return this.label('清洁时轻柔带过，随后充分冲净。','Cleanse gently and rinse well.');
    if(value==='sunscreen')return this.label('日间均匀涂抹；在户外时留意补涂。','Apply evenly in the daytime and reapply outdoors.');
    if(value==='eye')return this.label('沿眼周轻轻点开，避开眼内。','Pat gently around the eyes, avoiding the eye itself.');
    if(value==='serum'||value==='toner')return this.label('清洁后轻轻铺开，再按自己的习惯叠加面霜。','Apply gently after cleansing, then follow with cream if you wish.');
    if(value==='cream'||value==='emulsion')return this.label('在面部轻轻推开，留意自己喜欢的肤感。','Smooth gently over the face and notice the finish you like.');
    return this.label('组合中的单品可逐一查看，使用时以包装说明为准。','Check each item in the set and follow its label.');
  }
  private hasTimeline(value:string):boolean{return ['serum','toner','cream','emulsion','eye'].includes(value);}
  private timeNote():string{
    if(this.week===0)return this.label('今天：先在相近光线下留一张参考照片。','Today: take a reference photo in consistent light.');
    if(this.week<3)return this.label('预期观察：看看触感与日常使用是否适合自己。','What to observe: comfort and how it fits your routine.');
    if(this.week<6)return this.label('预期观察：用相同角度和光线，对照自己的记录。','What to observe: compare your own photos in similar light.');
    return this.label('预期观察：回看一段时间的记录，变化以你真实看到的为准。','What to observe: review your record; your own experience is what matters.');
  }
  build(){
    Column({space:12}){
      Row(){
        Column({space:4}){
          Text(this.label('循光 · OLAY','In the light · OLAY')).fontSize(19).fontWeight(FontWeight.Medium).fontColor('#EFF5FF')
          Text(this.label('从需求开始，慢慢认识适合自己的护理','Explore care at your own pace')).fontSize(11).fontColor('#A7BDD8')
        }.alignItems(HorizontalAlign.Start).layoutWeight(1)
        Button('×').fontSize(22).fontColor('#DAE9F9').backgroundColor('#25415A').width(36).height(36).borderRadius(18).onClick(()=>this.onClose())
      }.width('100%')
      Row({space:8}){
        Button(this.label('近期系列','Recent lines')).fontSize(12).fontColor('#E7F1FF').backgroundColor(this.section==='brand'?'#5E7797':'#243B54')
          .borderRadius(17).onClick(()=>{this.section='brand';this.selectedId='';this.week=0;})
        Button(this.label('更多资料','More records')).fontSize(12).fontColor('#E7F1FF').backgroundColor(this.section==='catalog'?'#5E7797':'#243B54')
          .borderRadius(17).onClick(()=>{this.section='catalog';this.selectedId='';this.week=0;})
      }.width('100%')
      if(!this.selected()){
      Scroll(){
        Column({space:8}){
          ForEach(this.records(),(product:OlayDiscoveryItem)=>{
            Row({space:11}){
              if(this.hasPhoto(product.id)){
                Image(this.productPhoto(product.id)).width(42).height(42).objectFit(ImageFit.Contain)
              }else{
                Circle().width(9).height(9).fill('#A7BED7')
              }
              Column({space:4}){
                Text(product.name).fontSize(13).fontColor('#F1F5FF').maxLines(2)
                Text(this.category(product.category)+'  ·  '+product.family).fontSize(10).fontColor('#AFC4DB').maxLines(1)
              }.alignItems(HorizontalAlign.Start).layoutWeight(1)
              Text('›').fontSize(23).fontColor('#BBD0E6')
            }.width('100%').padding({left:8,right:12,top:7,bottom:7})
              .backgroundColor(this.selectedId===product.id?'#4B6683C7':'#203A54A9')
              .border({width:1,color:this.selectedId===product.id?'#9BB9D5':'#54718A'})
              .borderRadius(18).onClick(()=>{this.selectedId=product.id;this.week=0;})
          },(product:OlayDiscoveryItem)=>product.id)
        }.width('100%')
      }.layoutWeight(1).scrollBar(BarState.Off)
      }else{
        Column({space:8}){
          Button(this.label('‹  返回资料','‹  Back')).fontSize(11).fontColor('#D5E6F8').backgroundColor('#29435C')
            .borderRadius(15).onClick(()=>{this.selectedId='';this.week=0;})
          Row({space:10}){
            if(this.hasPhoto(this.selectedId)){
              Image(this.productPhoto(this.selectedId)).width(88).height(88).objectFit(ImageFit.Contain)
            }
            Column({space:5}){
              Text((this.selected() as OlayDiscoveryItem).name).fontSize(15).fontColor('#F3F6FF').fontWeight(FontWeight.Medium).maxLines(2)
              Text(this.category((this.selected() as OlayDiscoveryItem).category)).fontSize(10).fontColor('#A9C0D9')
            }.alignItems(HorizontalAlign.Start).layoutWeight(1)
          }
          Text(this.routine((this.selected() as OlayDiscoveryItem).category)).fontSize(12).lineHeight(18).fontColor('#E1ECF9')
          if(this.hasTimeline((this.selected() as OlayDiscoveryItem).category)){
            Text(this.label('预期观察 · '+(this.week===0?'今天':'第'+this.week+'周'),'What to observe · '+(this.week===0?'today':'week '+this.week)))
              .fontSize(11).fontColor('#C9DCF0')
            Slider({value:this.week,min:0,max:8,step:1}).blockColor('#D9EAF9').selectedColor('#799CBC')
              .onChange((value:number)=>this.week=value)
            Text(this.timeNote()).fontSize(11).fontColor('#B9D1E8').maxLines(2)
          }
          Text(this.label('来源 · 长按复制','Source · long press to copy')).fontSize(10).fontColor('#9FB7D2')
          Text((this.selected() as OlayDiscoveryItem).source).fontSize(9).fontColor('#B4C8DC').maxLines(2).copyOption(CopyOptions.LocalDevice)
        }.padding(12).width('100%').backgroundColor('#29435CC9').border({width:1,color:'#7091B0'})
          .borderRadius(20).transition({opacity:0,scale:{x:.95,y:.95},translate:{y:8}})
      }
    }.padding(16).width(this.panelWidth()).height(this.panelHeight())
      .backgroundColor('#E912253D').border({width:1,color:'#5D7998'})
      .borderRadius(28).shadow({radius:26,color:'#66030813',offsetY:8})
  }
}

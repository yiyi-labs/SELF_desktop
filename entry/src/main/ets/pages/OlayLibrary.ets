import { OlayDiscoveryItem, OlayDiscoveryRepository } from '../services/OlayDiscoveryRepository';
import { OlayPhotoRepository } from '../services/OlayPhotoRepository';
import { StarCloseButton } from './StarCloseButton';
import { UiText } from '../services/UiText';

class OlayListDataSource implements IDataSource {
  private items:OlayDiscoveryItem[]=[];
  private listeners:DataChangeListener[]=[];
  totalCount():number{return this.items.length;}
  getData(index:number):OlayDiscoveryItem{return this.items[index];}
  registerDataChangeListener(listener:DataChangeListener):void{this.listeners.push(listener);}
  unregisterDataChangeListener(listener:DataChangeListener):void{
    this.listeners=this.listeners.filter((item:DataChangeListener)=>item!==listener);
  }
  setData(items:OlayDiscoveryItem[]):void{
    this.items=items;
    this.listeners.forEach((listener:DataChangeListener)=>listener.onDataReloaded());
  }
}

/** Source-linked product identities beside the portrait; never drives GS colours. */
@Component
export struct OlayLibrary {
  @Prop language:string='zh';
  @Prop viewportWidth:number=400;
  @Prop viewportHeight:number=600;
  @Prop initialProductId:string='';
  onClose:()=>void=()=>{};
  @State section:string='brand';
  @State selectedId:string='';
  @State week:number=0;
  private listData:OlayListDataSource=new OlayListDataSource();

  private tr(value:string):string{return UiText.get(value,this.language);}
  private panelWidth():number{return Math.min(this.viewportWidth-24,this.viewportHeight>this.viewportWidth?420:360);}
  private panelHeight():number{return this.viewportHeight>this.viewportWidth?
    Math.min(this.viewportHeight*.74,900):Math.min(this.viewportHeight*.62,520);}
  private records():OlayDiscoveryItem[]{return OlayDiscoveryRepository.allRecords().filter((p:OlayDiscoveryItem)=>p.section===this.section);}
  private selected():OlayDiscoveryItem|undefined{return OlayDiscoveryRepository.allRecords().find((p:OlayDiscoveryItem)=>p.id===this.selectedId);}
  private productPhoto(id:string):Resource{return OlayPhotoRepository.photo(id);}
  private changeSection(section:string):void{
    this.section=section;this.selectedId='';this.week=0;this.listData.setData(this.records());
  }
  aboutToAppear():void{
    const item=OlayDiscoveryRepository.allRecords().find((p:OlayDiscoveryItem)=>p.id===this.initialProductId);
    if(item){this.section=item.section;this.selectedId=item.id;}
    this.listData.setData(this.records());
  }
  private category(value:string):string{
    if(value==='cream')return this.tr('面霜');
    if(value==='serum')return this.tr('精华');
    if(value==='toner')return this.tr('精华水');
    if(value==='emulsion')return this.tr('乳液');
    if(value==='eye')return this.tr('眼周护理');
    if(value==='sunscreen')return this.tr('防晒');
    if(value==='cleanser')return this.tr('洁面');
    if(value==='mask')return this.tr('面膜');
    if(value==='set')return this.tr('组合');
    return this.tr('护理');
  }
  private routine(value:string):string{
    if(value==='cleanser')return this.tr('清洁时轻柔带过，随后充分冲净。');
    if(value==='sunscreen')return this.tr('日间均匀涂抹；在户外时留意补涂。');
    if(value==='eye')return this.tr('沿眼周轻轻点开，避开眼内。');
    if(value==='serum'||value==='toner')return this.tr('清洁后轻轻铺开，再按自己的习惯叠加面霜。');
    if(value==='cream'||value==='emulsion')return this.tr('在面部轻轻推开，留意自己喜欢的肤感。');
    return this.tr('组合中的单品可逐一查看，使用时以包装说明为准。');
  }
  private hasTimeline(value:string):boolean{return ['serum','toner','cream','emulsion','eye'].includes(value);}
  private timeNote():string{
    if(this.week===0)return this.tr('今天：先在相近光线下留一张参考照片。');
    if(this.week<3)return this.tr('预期观察：看看触感与日常使用是否适合自己。');
    if(this.week<6)return this.tr('预期观察：用相同角度和光线，对照自己的记录。');
    return this.tr('预期观察：回看一段时间的记录，变化以你真实看到的为准。');
  }
  build(){
    Stack(){
      List({space:8}){
        ListItem(){
          Column({space:4}){
            Text(this.tr('循光 · OLAY')).fontSize(19).fontWeight(FontWeight.Medium).fontColor('#EFF5FF')
            Text(this.tr('从需求开始，慢慢认识适合自己的护理')).fontSize(11).fontColor('#A7BDD8')
          }.alignItems(HorizontalAlign.Start).width('100%').padding({right:44})
        }
        ListItem(){
          Row({space:8}){
            Button(this.tr('近期系列')).fontSize(12).fontColor('#E7F1FF')
              .backgroundColor(this.section==='brand'?'#5E7797':'#243B54')
              .borderRadius(17).onClick(()=>this.changeSection('brand'))
            Button(this.tr('更多资料')).fontSize(12).fontColor('#E7F1FF')
              .backgroundColor(this.section==='catalog'?'#5E7797':'#243B54')
              .borderRadius(17).onClick(()=>this.changeSection('catalog'))
            Button(this.tr('历史与研究')).fontSize(12).fontColor('#E7F1FF')
              .backgroundColor(this.section==='research'?'#5E7797':'#243B54')
              .borderRadius(17).onClick(()=>this.changeSection('research'))
          }.width('100%')
        }
        if(!this.selected()){
          LazyForEach(this.listData,(product:OlayDiscoveryItem)=>{
            ListItem(){
              Row({space:11}){
                Image(OlayPhotoRepository.thumbnail(product.id)).width(46).height(46).objectFit(ImageFit.Contain)
                Column({space:4}){
                  Text(product.name).fontSize(13).fontColor('#F1F5FF').maxLines(2)
                  Text(this.category(product.category)+'  ·  '+product.family).fontSize(10).fontColor('#AFC4DB').maxLines(1)
                }.alignItems(HorizontalAlign.Start).layoutWeight(1)
                Text('›').fontSize(23).fontColor('#BBD0E6')
              }.width('100%').padding({left:8,right:12,top:7,bottom:7})
                .backgroundColor('#203A54A9').border({width:1,color:'#54718A'}).borderRadius(18)
            }.onClick(()=>{this.selectedId=product.id;this.week=0;})
          },(product:OlayDiscoveryItem)=>product.id)
        }else{
          ListItem(){
            Column({space:8}){
              Button(this.tr('‹  返回资料')).fontSize(11).fontColor('#D5E6F8').backgroundColor('#29435C')
                .borderRadius(15).onClick(()=>{this.selectedId='';this.week=0;})
              Row({space:10}){
                Image(this.productPhoto(this.selectedId)).width(92).height(92).objectFit(ImageFit.Contain)
                Column({space:5}){
                  Text((this.selected() as OlayDiscoveryItem).name).fontSize(15).fontColor('#F3F6FF').fontWeight(FontWeight.Medium).maxLines(2)
                  Text(this.category((this.selected() as OlayDiscoveryItem).category)).fontSize(10).fontColor('#A9C0D9')
                  if(OlayPhotoRepository.isSeriesReference(this.selectedId)){
                    Text(this.tr('系列外观参考')).fontSize(10).fontColor('#C7D7E9')
                  }
                  if(OlayPhotoRepository.isCompositeReference(this.selectedId)){
                    Text(this.tr('组合外观示意')).fontSize(10).fontColor('#C7D7E9')
                  }
                }.alignItems(HorizontalAlign.Start).layoutWeight(1)
              }
              if(this.section==='research'){
                Text(this.tr('历史或研究线索，供核对身份；当前版本与在售信息尚未确认。'))
                  .fontSize(12).lineHeight(18).fontColor('#E1ECF9')
              }else{Text(this.routine((this.selected() as OlayDiscoveryItem).category)).fontSize(12).lineHeight(18).fontColor('#E1ECF9')}
              if(this.section!=='research'&&this.hasTimeline((this.selected() as OlayDiscoveryItem).category)){
                Text(this.week===0?this.tr('预期观察 · 今天'):this.tr('预期观察 · 第{week}周').replace('{week}',String(this.week)))
                  .fontSize(11).fontColor('#C9DCF0')
                Slider({value:this.week,min:0,max:8,step:1}).blockColor('#D9EAF9').selectedColor('#799CBC')
                  .onChange((value:number)=>this.week=value)
                Text(this.timeNote()).fontSize(11).fontColor('#B9D1E8').maxLines(2)
              }
              Text(this.tr('来源 · 长按复制')).fontSize(10).fontColor('#9FB7D2')
              Text((this.selected() as OlayDiscoveryItem).source).fontSize(9).fontColor('#B4C8DC').maxLines(2).copyOption(CopyOptions.LocalDevice)
            }.padding(12).width('100%').backgroundColor('#29435CC9').border({width:1,color:'#7091B0'})
              .borderRadius(20).transition({opacity:0,scale:{x:.95,y:.95},translate:{y:8}})
          }
        }
      }.padding(16).width('100%').height('100%').cachedCount(4).scrollBar(BarState.Off)
        .edgeEffect(EdgeEffect.Spring)
      StarCloseButton({diameter:36,label:this.tr('关闭'),onClose:()=>this.onClose()})
        .position({x:this.panelWidth()-52,y:16})
    }.width(this.panelWidth()).height(this.panelHeight())
      .backgroundColor('#E912253D').border({width:1,color:'#5D7998'})
      .borderRadius(28).shadow({radius:26,color:'#66030813',offsetY:8})
  }
}

import { UiText } from '../services/UiText';

@Component
export struct ReconstructionProgressCapsule {
  @Prop name:string='';
  @Prop progress:number=0;
  @Prop outcome:string='';
  @Prop message:string='';
  @Prop language:string='zh';
  @Prop motion:boolean=true;
  @Prop capsuleWidth:number=340;
  @Prop compact:boolean=true;
  onOpen:()=>void=()=>{};
  private tr(zh:string,en:string):string{return this.language==='en'?en:UiText.get(zh,this.language);}
  private title():string{
    if(this.outcome==='ready')return this.tr('星辰已构建完成','Your star is ready');
    if(this.outcome==='failed')return this.tr('这次寻找暂时停下','The light paused');
    return this.name||this.tr('星辰正在构建','Finding your portrait');
  }
  build(){
    Button({type:ButtonType.Normal,stateEffect:false}){
      Row({space:12}){
        Stack(){
          Circle().width(28).height(28).fill('#173A5270').blur(5)
          Image($rawfile('ui/reconstruction_star.svg')).width(23).height(23)
        }.width(32).height(32).hitTestBehavior(HitTestMode.None)
        Column({space:5}){
          Row({space:8}){
            Text(this.title()).fontSize(13).fontColor('#E8F1FF').fontWeight(FontWeight.Medium)
              .maxLines(1).textOverflow({overflow:TextOverflow.Ellipsis}).layoutWeight(1)
            Text(this.outcome==='ready'?this.tr('轻触查看','Open'):this.outcome==='failed'?
              this.tr('查看详情','Details'):Math.round(this.progress)+'%')
              .fontSize(11).fontColor('#B8CFE6')
          }.width('100%')
          if(!this.outcome){
            Progress({value:this.progress,total:100,type:ProgressType.Linear})
              .width('100%').height(2).color('#BEDCF4').backgroundColor('#31445E')
          }else{
            Text(this.outcome==='ready'?this.tr('新的微光，正等你走近。','A new light is waiting for you.'):UiText.get(this.message,this.language))
              .fontSize(10).fontColor('#A7BDD6').maxLines(1).textOverflow({overflow:TextOverflow.Ellipsis})
          }
        }.layoutWeight(1).alignItems(HorizontalAlign.Start)
        Text('›').fontSize(19).fontColor('#9BB6D2').margin({left:2})
      }.padding({left:15,right:17}).width('100%')
    }.id('reconstruction-progress-capsule').width(this.capsuleWidth).height(this.compact?48:62).padding(0)
      .backgroundColor('#E319293E').backgroundBlurStyle(BlurStyle.COMPONENT_ULTRA_THIN,{colorMode:ThemeColorMode.DARK})
      .border({width:1,color:'#647690AF'}).borderRadius(26)
      .shadow({radius:16,color:'#5010192C',offsetY:4})
      .stateStyles({pressed:{.scale({x:.985,y:.97})},normal:{.scale({x:1,y:1})}})
      .animation({duration:this.motion?180:0,curve:Curve.EaseOut})
      .accessibilityText(this.title()+' '+(this.outcome?UiText.get(this.message,this.language):Math.round(this.progress)+'%')+
        this.tr(' · 轻触查看进度',' · Open progress'))
      .onClick(()=>this.onOpen())
  }
}

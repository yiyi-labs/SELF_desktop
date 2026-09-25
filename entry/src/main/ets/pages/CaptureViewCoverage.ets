/** Wide downward-opening view arc; the pointer travels beneath it. */
@ComponentV2
export struct CaptureViewCoverage {
 @Param covered:boolean[]=[false,false,false,false,false,false,false,false,false,false,false,false,false];
 @Param active:number=-1;
 @Param count:number=0;
 @Param hint:number=6;
 @Param angle:number=0;
 @Param language:string='zh';
 @Param expanded:boolean=false;
 @Param availableWidth:number=800;
 private tr(zh:string,en:string):string{return this.language==='en'?en:zh;}
 private cue():string{
  if(this.hint<0)return this.tr('视角已点亮','Views illuminated');
  if(this.hint<=2)return this.tr('慢慢看看左侧，脸留在画面里','Move toward the left; keep your face in view');
  if(this.hint<=5)return this.tr('再留一点左前方','Hold a little on the left');
  if(this.hint===6)return this.tr('先留下正面','Start from the front');
  if(this.hint<=9)return this.tr('慢慢看看右前方','Slowly move toward the right');
  if(this.hint<=12)return this.tr('再看看右侧，脸留在画面里','Move farther right; keep your face in view');
  return this.tr('视角已点亮','Views illuminated');
 }
 private arcY(index:number):number{return -14+index*index*.72;}
 build(){
  Column({space:this.expanded?8:0}){
   if(this.expanded){
    Text(this.cue()).fontSize(17).fontWeight(FontWeight.Medium).fontColor('#FAFFFFFF')
     .width('100%').textAlign(TextAlign.Center)
   }
   Row({space:14}){
    Stack(){
    Path().commands('M 4 43 Q 74 -8 144 43').width(148).height(58).fill(Color.Transparent)
     .stroke('#8BCFEEE6').strokeWidth(1.2)
    ForEach([0,1,2,3,4,5,6,7,8,9,10,11,12],(index:number)=>{
     Circle().width(this.active===index?7:5).height(this.active===index?7:5)
      .fill(this.covered[index]?'#DFFFF1':this.active===index?'#FFFFFF':'#5A9DAEC0')
      .stroke(this.covered[index]?'#F5FFFFFF':'#B9E7F4F2').strokeWidth(.8)
      .translate({x:(index-6)*11.4,y:this.arcY(index-6)})
    },(index:number)=>index.toString())
    if(this.active>=0){
     Path().commands('M 0 10 L 5 1 L 10 10 Z').width(11).height(11).fill('#E6FFF4')
      .translate({x:this.angle*1.14,y:this.arcY(this.angle/10)+17})
      .shadow({radius:8,color:'#A0BFEFEA'})
      .animation({duration:240,curve:Curve.EaseOut})
    }
    }.width(148).height(72).hitTestBehavior(HitTestMode.None)
    Column({space:4}){
     Text(this.tr('已留下 ','Captured ')+this.count+this.tr(' 个视角',' views')).fontSize(this.expanded?18:15)
      .fontWeight(FontWeight.Medium).fontColor('#F8FFFFFF')
     if(this.active>=0){Text((this.angle>0?'+':'')+this.angle+'°').fontSize(12).fontColor('#D9ECF8F3')}
     if(!this.expanded){Text(this.cue()).fontSize(12).fontColor('#DDE9FCF8')}
    }.alignItems(HorizontalAlign.Start)
   }.width('100%').justifyContent(FlexAlign.Center)
  }.padding({left:15,right:18,top:this.expanded?17:10,bottom:this.expanded?13:10})
   .width(Math.min(this.availableWidth-40,this.expanded?430:336)).height(this.expanded?128:92).backgroundColor('#78202C3E')
   .backgroundBlurStyle(BlurStyle.COMPONENT_REGULAR)
   .linearGradient({angle:145,colors:[['#A3526B80',0],['#6D1D2D43',.6],['#9A40596F',1]]})
   .border({width:1,color:this.expanded?'#E6E8FFF9':'#B5DDF8F2'}).borderRadius(30)
   .shadow({radius:this.expanded?32:24,color:'#4C071421',offsetY:this.expanded?14:9})
   .animation({duration:300,curve:Curve.EaseOut})
   .hitTestBehavior(HitTestMode.None)
 }
}

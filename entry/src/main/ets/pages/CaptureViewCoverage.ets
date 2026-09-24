/** Wide downward-opening view arc; the pointer travels beneath it. */
@ComponentV2
export struct CaptureViewCoverage {
 @Param covered:boolean[]=[false,false,false,false,false,false,false,false,false,false,false];
 @Param active:number=-1;
 @Param count:number=0;
 @Param hint:number=5;
 @Param angle:number=0;
 @Param language:string='zh';
 private tr(zh:string,en:string):string{return this.language==='en'?en:zh;}
 private cue():string{
  if(this.hint<0)return this.tr('视角已点亮','Views illuminated');
  if(this.hint<=2)return this.tr('慢慢看看左侧','Slowly move toward the left');
  if(this.hint<=4)return this.tr('再留一点左前方','Hold a little on the left');
  if(this.hint===5)return this.tr('先留下正面','Start from the front');
  if(this.hint<=7)return this.tr('慢慢看看右前方','Slowly move toward the right');
  if(this.hint<=10)return this.tr('再看看右侧','Move a little farther right');
  return this.tr('视角已点亮','Views illuminated');
 }
 private arcY(index:number):number{return -11+index*index*.88;}
 build(){
  Row({space:14}){
   Stack(){
    Path().commands('M 4 40 Q 64 -4 124 40').width(128).height(58).fill(Color.Transparent)
     .stroke('#8BCFEEE6').strokeWidth(1.2)
    ForEach([0,1,2,3,4,5,6,7,8,9,10],(index:number)=>{
     Circle().width(this.active===index?7:5).height(this.active===index?7:5)
      .fill(this.covered[index]?'#DFFFF1':this.active===index?'#FFFFFF':'#5A9DAEC0')
      .stroke(this.covered[index]?'#F5FFFFFF':'#B9E7F4F2').strokeWidth(.8)
      .translate({x:(index-5)*11.6,y:this.arcY(index-5)})
    },(index:number)=>index.toString())
    if(this.active>=0){
     Path().commands('M 0 10 L 5 1 L 10 10 Z').width(11).height(11).fill('#E6FFF4')
      .translate({x:this.angle*1.16,y:this.arcY(this.angle/10)+17})
      .shadow({radius:8,color:'#A0BFEFEA'})
      .animation({duration:240,curve:Curve.EaseOut})
    }
   }.width(128).height(72).hitTestBehavior(HitTestMode.None)
   Column({space:4}){
    Row({space:8}){
     Text(this.tr('视角','Views')+' '+this.count+'/11').fontSize(15).fontWeight(FontWeight.Medium).fontColor('#F8FFFFFF')
     if(this.active>=0){Text((this.angle>0?'+':'')+this.angle+'°').fontSize(11).fontColor('#D9ECF8F3')}
    }
    Text(this.cue()).fontSize(12).fontColor('#DDE9FCF8')
   }.alignItems(HorizontalAlign.Start)
  }.padding({left:15,right:18,top:10,bottom:10}).height(92).backgroundColor('#78202C3E')
   .backgroundBlurStyle(BlurStyle.COMPONENT_REGULAR)
   .linearGradient({angle:145,colors:[['#8B425A70',0],['#641D2D43',.6],['#85324B60',1]]})
   .border({width:1,color:'#B5DDF8F2'}).borderRadius(30)
   .shadow({radius:24,color:'#4C071421',offsetY:9})
   .hitTestBehavior(HitTestMode.None)
 }
}

/** Lightweight, glass-like view guidance; the illuminated points are sampled face-view sectors. */
@ComponentV2
export struct CaptureViewCoverage {
 @Param covered:boolean[]=[false,false,false,false,false];
 @Param active:number=-1;
 @Param count:number=0;
 @Param hint:number=2;
 @Param angle:number=0;
 @Param language:string='zh';
 private tr(zh:string,en:string):string{return this.language==='en'?en:zh;}
 private cue():string{
  if(this.hint===0)return this.tr('再看看左侧','Move a little farther left');
  if(this.hint===1)return this.tr('慢慢移向左前','Move toward the left');
  if(this.hint===2)return this.tr('先留下正面','Start from the front');
  if(this.hint===3)return this.tr('慢慢移向右前','Move toward the right');
  if(this.hint===4)return this.tr('再看看右侧','Move a little farther right');
  return this.tr('视角已点亮','Views illuminated');
 }
 build(){
  Row({space:10}){
   Stack(){
    Circle().width(78).height(78).fill('#254D6077').stroke('#96DCF7EF').strokeWidth(1.2)
    Circle().width(52).height(52).fill('#506DDDCB').blur(24).translate({x:-12,y:-12})
    Ellipse().width(88).height(28).fill(Color.Transparent).stroke('#91D3F0F0').strokeWidth(1.3).rotate({angle:-15})
    Ellipse().width(36).height(83).fill(Color.Transparent).stroke('#5FC9E9E9').strokeWidth(1)
    Path().commands('M 8 54 Q 50 3 92 54').width(100).height(65).fill(Color.Transparent).stroke('#9AD9ECF3').strokeWidth(1.5)
    ForEach([0,1,2,3,4],(index:number)=>{
     Circle().width(this.active===index?12:9).height(this.active===index?12:9)
      .fill(this.covered[index]?'#D7FFF1':this.active===index?'#FFFFFF':'#285A6477')
      .stroke(this.covered[index]?'#F8FFFFFF':'#D5F0FFFF').strokeWidth(1.2)
      .translate({x:(index-2)*19,y:Math.abs(index-2)*8-15})
    },(index:number)=>index.toString())
   }.width(102).height(94).hitTestBehavior(HitTestMode.None)
   Column({space:5}){
    Text(this.tr('视角参考','View guide')+'  '+this.count+'/5').fontSize(15).fontWeight(FontWeight.Medium).fontColor('#F8FFFFFF')
    Text(this.cue()).fontSize(13).fontColor('#DDE9FCF8')
    if(this.active>=0){Text(this.tr('相对角度约 ','Relative angle ~')+(this.angle>0?'+':'')+this.angle+'°').fontSize(11).fontColor('#BCE8F3F7')}
   }.alignItems(HorizontalAlign.Start)
  }.padding({left:10,right:16,top:5,bottom:5}).height(106).backgroundColor('#78202C3E')
   .backgroundBlurStyle(BlurStyle.COMPONENT_REGULAR)
   .linearGradient({angle:145,colors:[['#8B52738A',0],['#6B1B2D43',.6],['#8D283D51',1]]})
   .border({width:1,color:'#B5DDF8F2'}).borderRadius(30)
   .shadow({radius:24,color:'#4C071421',offsetY:9})
   .hitTestBehavior(HitTestMode.None)
 }
}

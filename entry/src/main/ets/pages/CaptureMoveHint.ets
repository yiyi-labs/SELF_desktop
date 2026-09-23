/** Original line artwork based on the interaction seen in the supplied Remy demo. */
@ComponentV2
export struct CaptureMoveHint {
 @Param motion:boolean=true;
 @Param language:string='zh';
 @Param hintSize:number=320;
 @Local travel:number=-1;
 private startTimer:number=-1;
 aboutToAppear():void{
  this.travel=this.motion?-1:0;
  // Wait for the initial layout so the first visible position is an animation start value.
  if(this.motion)this.startTimer=setTimeout(()=>{this.getUIContext().animateTo({duration:2300,iterations:-1,playMode:PlayMode.Alternate,curve:Curve.EaseInOut},()=>{this.travel=1;});},100);
 }
 aboutToDisappear():void{clearTimeout(this.startTimer);}
 build(){
  Column({space:18}){
   Stack(){
    // Stable person, moving phone: the camera changes viewpoint around the person.
    Path().commands('M 110 20 C 91 20 85 35 88 51 C 90 65 99 73 110 73 C 121 73 130 65 132 51 C 135 35 129 20 110 20 M 91 79 C 76 83 65 91 60 105 L 54 131 Q 53 137 60 140 L 78 144 L 86 189 Q 89 201 101 202 L 119 202 Q 131 201 134 189 L 142 144 L 160 140 Q 167 137 166 131 L 160 105 C 155 91 144 83 129 79')
     .width(220).height(222).fill(Color.Transparent).stroke('#F5FFFFFF').strokeWidth(3.4).strokeLineCap(LineCapStyle.Round)
    Path().commands('M 22 178 Q 110 220 198 178 M 185 177 L 198 178 L 193 191')
     .width(220).height(222).fill(Color.Transparent).stroke('#80FFFFFF').strokeWidth(2).strokeDashArray([5,6])
    Stack(){
     Rect().width(68).height(114).radius(13).fill(Color.Transparent).stroke(Color.White).strokeWidth(3.4)
     Rect().width(48).height(86).radius(5).fill(Color.Transparent).stroke('#A8FFFFFF').strokeWidth(1).translate({y:-3})
     Line().startPoint([0,0]).endPoint([19,0]).stroke(Color.White).strokeWidth(2.4).width(19).height(2).translate({y:48})
    }.width(74).height(122).rotate({angle:this.travel*18}).translate({x:this.travel*64,y:20+Math.abs(this.travel)*7})
   }.width(260).height(242).scale({x:this.hintSize/320,y:this.hintSize/320})
   Text(this.language==='en'?'Slowly move the camera to one side':'让镜头慢慢移向一侧').fontSize(this.hintSize>300?21:18).fontWeight(FontWeight.Medium).fontColor(Color.White).textAlign(TextAlign.Center).textShadow({radius:2,color:'#90000000',offsetY:1})
   Text(this.language==='en'?'Keep a relaxed, steady expression':'面容保持自然、稳定就好').fontSize(13).fontColor('#EFFFFFFF').textShadow({radius:2,color:'#90000000',offsetY:1})
  }.id('camera-motion-hint').width(this.hintSize).padding({top:12,bottom:22,left:16,right:16}).hitTestBehavior(HitTestMode.None)
 }
}

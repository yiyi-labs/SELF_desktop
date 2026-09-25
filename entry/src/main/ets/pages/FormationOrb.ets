/** A small, self-contained transition while a portrait is being formed. */
@Component
export struct FormationOrb {
  @Prop motion:boolean=true;
  @State lift:number=0;
  @State glow:number=0;
  private startTimer:number=-1;

  aboutToAppear():void{
    if(!this.motion)return;
    this.startTimer=setTimeout(()=>{
      this.startTimer=-1;
      this.getUIContext().animateTo({duration:950,iterations:-1,playMode:PlayMode.Alternate,curve:Curve.EaseInOut},()=>{
        this.lift=-25;this.glow=1;
      });
    },80);
  }

  aboutToDisappear():void{if(this.startTimer>=0)clearTimeout(this.startTimer);}

  build(){
    Stack(){
      Ellipse().width(76).height(10).fill('#607EA6').blur(12).opacity(.27+this.glow*.18).translate({y:65})
      Stack(){
        Circle().width(108).height(108).fill('#26466F83').stroke('#8BB8E4').strokeWidth(1)
          .shadow({radius:36,color:'#739BCDD1'})
        Circle().width(72).height(72).fill(Color.Transparent).stroke('#B3D5F1').strokeWidth(1).opacity(.55)
        Circle().width(31).height(31).fill('#EDF0FF').shadow({radius:32,color:'#BDCBF4'})
      }.width(116).height(116).translate({y:this.lift})
    }.width(136).height(152).hitTestBehavior(HitTestMode.None)
  }
}

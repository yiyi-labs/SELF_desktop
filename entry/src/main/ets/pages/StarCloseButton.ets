/** A text-free close mark keeps both strokes centred on every device font. */
@Component
export struct StarCloseButton {
  @Prop diameter:number=36;
  @Prop label:string='关闭';
  onClose:()=>void=()=>{};
  @State private pressed:boolean=false;

  build(){
    Button({type:ButtonType.Circle,stateEffect:false}){
      Stack(){
        Circle().width(this.diameter-7).height(this.diameter-7)
          .fill(this.pressed?'#5E88AD':'#25415A')
        Rect().width(this.diameter*.42).height(2).fill('#EAF4FF').rotate({angle:45})
        Rect().width(this.diameter*.42).height(2).fill('#EAF4FF').rotate({angle:-45})
      }.width(this.diameter).height(this.diameter)
    }.width(this.diameter).height(this.diameter).borderRadius(this.diameter/2)
      .backgroundColor('#00000000')
      .border({width:1,color:this.pressed?'#D8EFFF':'#7699B8'})
      .shadow({radius:this.pressed?17:5,color:this.pressed?'#A8D9F0':'#325270',offsetY:0})
      .scale({x:this.pressed?.92:1,y:this.pressed?.92:1})
      .animation({duration:170,curve:Curve.EaseOut})
      .accessibilityText(this.label)
      .onTouch((event:TouchEvent)=>{
        this.pressed=event.type===TouchType.Down;
      })
      .onClick(()=>this.onClose())
  }
}

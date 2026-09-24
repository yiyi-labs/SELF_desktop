/** A decorative, deterministic field. It never represents captured face geometry. */
@Component
export struct NightSkySurface {
  @Prop formation:number=0;
  @Prop musicPulse:number=0;
  @Prop motion:boolean=true;
  @Prop active:boolean=true;
  private drawing:CanvasRenderingContext2D=new CanvasRenderingContext2D(new RenderingContextSettings(true));
  private clock:number=0;
  private timer:number=-1;

  private unit(seed:number):number{return Math.abs(Math.sin(seed*127.1+78.233)*43758.5453)%1;}
  private dot(x:number,y:number,r:number,color:string):void{
    this.drawing.beginPath();this.drawing.fillStyle=color;this.drawing.arc(x,y,r,0,Math.PI*2);this.drawing.fill();
  }
  private draw():void{
    const ctx=this.drawing,w=ctx.width,h=ctx.height;
    if(w<=0||h<=0)return;
    ctx.clearRect(0,0,w,h);
    const t=this.motion?this.clock*.018:0;
    const cx=w*.5,cy=h*.49,portrait=Math.max(0,Math.min(1,this.formation));
    // Sparse distant stars remain behind both the empty and forming states.
    for(let i=0;i<110;i++){
      const x=this.unit(i+1)*w,y=this.unit(i+701)*h;
      const twinkle=.42+.32*Math.sin(t*.5+i*.9)+this.musicPulse*.20;
      this.dot(x,y,Math.max(.45,w*.0011)*(i%11===0?1.8:1),`rgba(213,225,255,${Math.max(.12,twinkle)*.58})`);
    }
    // A suggested human outline, never a substitute for the actual reconstructed portrait.
    const count=168;
    for(let i=0;i<count;i++){
      const a=i*2.399963,tier=this.unit(i+309),isHead=i<110;
      const spread=Math.sqrt(tier);
      const hx=Math.cos(a)*w*.115*spread;
      const hy=Math.sin(a)*h*.205*spread-h*.075;
      const shoulderA=(i-110)/Math.max(1,count-110)*Math.PI;
      const bx=Math.cos(shoulderA)*w*.225;
      const by=h*.19+Math.sin(shoulderA)*h*.10;
      const shapeX=cx+(isHead?hx:bx),shapeY=cy+(isHead?hy:by);
      const driftX=(this.unit(i+1300)-.5)*w*.55;
      const driftY=(this.unit(i+1700)-.5)*h*.68;
      const x=shapeX*portrait+(cx+driftX)*(1-portrait)+Math.sin(t+i*.48)*(this.motion?2.8:0);
      const y=shapeY*portrait+(cy+driftY)*(1-portrait)+Math.cos(t*.7+i*.62)*(this.motion?2.2:0);
      const alpha=(.17+.32*portrait)*(i%9===0?1.4:1)+this.musicPulse*.09;
      const tone=i%6===0?'179,226,240':i%4===0?'233,202,238':'212,219,255';
      this.dot(x,y,(i%13===0?2.4:1.15)*(1+this.musicPulse*.22),`rgba(${tone},${Math.min(.7,alpha)})`);
    }
    const radius=Math.min(w,h)*(.052+this.musicPulse*.006);
    this.dot(cx,cy,radius*1.9,'rgba(136,167,236,.018)');
    ctx.beginPath();ctx.strokeStyle=`rgba(219,231,255,${.28+this.musicPulse*.16})`;ctx.lineWidth=1.2;
    ctx.arc(cx,cy,radius,0,Math.PI*2);ctx.stroke();
    this.dot(cx,cy,radius*.22,'rgba(236,239,255,.13)');
  }
  aboutToDisappear():void{if(this.timer>=0)clearInterval(this.timer);this.timer=-1;}
  build(){
    Canvas(this.drawing).width('100%').height('100%').hitTestBehavior(HitTestMode.None)
      .onReady(()=>{this.draw();if(this.timer<0)this.timer=setInterval(()=>{if(this.active){if(this.motion)this.clock++;this.draw();}},50);})
  }
}

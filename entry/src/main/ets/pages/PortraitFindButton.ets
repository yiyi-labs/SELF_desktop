import { PortraitFindTrail } from './PortraitFindTrail';

@Component
export struct PortraitFindButton {
  @Prop label:string='寻找我的模样';
  @Prop english:boolean=false;
  @Prop @Watch('optionsChanged') motion:boolean=true;
  @Prop @Watch('activeChanged') active:boolean=true;
  onFind:(event:ClickEvent)=>void=()=>{};
  @State private pressed:boolean=false;
  @State private launching:boolean=false;
  private drawing:CanvasRenderingContext2D=new CanvasRenderingContext2D(new RenderingContextSettings(true));
  private trail:PortraitFindTrail=new PortraitFindTrail();
  private prepared:boolean=false;
  private frameTimer:number=-1;
  private launchTimer:number=-1;
  private lastFrame:number=0;
  private buttonWidth():number{return this.english?208:172;}
  private immersed():boolean{return this.pressed||this.launching;}
  private stopFrames():void{
    if(this.frameTimer>=0)clearInterval(this.frameTimer);
    this.frameTimer=-1;this.trail.clear();
    if(this.prepared)this.drawing.clearRect(0,0,this.buttonWidth(),54);
  }
  private dispose():void{
    if(this.launchTimer>=0)clearTimeout(this.launchTimer);
    this.launchTimer=-1;this.pressed=false;this.launching=false;this.stopFrames();
  }
  private activeChanged():void{if(!this.active)this.dispose();}
  private optionsChanged():void{if(!this.motion)this.stopFrames();}
  aboutToDisappear():void{this.dispose();this.prepared=false;}
  private paint():void{
    if(!this.prepared)return;
    const ctx=this.drawing;ctx.clearRect(0,0,this.buttonWidth(),54);
    for(const light of this.trail.particles){
      const t=light.age/light.life;
      const alpha=Math.min(1,light.age/.07)*Math.pow(1-t,.85)*.95*
        Math.max(0,Math.min(1,(this.buttonWidth()-14-light.x)/24));
      const color=light.warm?'255,227,192':'208,233,255';
      const glow=ctx.createRadialGradient(light.x,light.y,0,light.x,light.y,light.radius*4);
      glow.addColorStop(0,'rgba('+color+','+alpha*.3+')');glow.addColorStop(1,'rgba('+color+',0)');
      ctx.fillStyle=glow;ctx.beginPath();ctx.arc(light.x,light.y,light.radius*4,0,Math.PI*2);ctx.fill();
      const tail=ctx.createLinearGradient(light.x-light.length,light.y,light.x,light.y);
      tail.addColorStop(0,'rgba('+color+',0)');tail.addColorStop(.75,'rgba('+color+','+alpha*.48+')');
      tail.addColorStop(1,'rgba('+color+','+alpha+')');
      ctx.strokeStyle=tail;ctx.lineWidth=light.radius;
      ctx.beginPath();ctx.moveTo(light.x-light.length,light.y);ctx.lineTo(light.x,light.y);ctx.stroke();
      ctx.fillStyle='rgba(244,250,255,'+alpha+')';ctx.beginPath();ctx.arc(light.x,light.y,light.radius,0,Math.PI*2);ctx.fill();
    }
  }
  private startFrames():void{
    if(!this.motion||!this.active||!this.prepared)return;
    if(this.frameTimer>=0)return;
    this.lastFrame=Date.now();
    this.frameTimer=setInterval(()=>{
      if(!this.active||!this.motion){this.stopFrames();return;}
      const now=Date.now(),dt=(now-this.lastFrame)/1000;this.lastFrame=now;
      this.trail.step(dt,this.pressed,this.buttonWidth(),54);this.paint();
      if(!this.pressed&&this.trail.particles.length===0)this.stopFrames();
    },16);
  }
  private touch(event:TouchEvent):void{
    if(!this.active||this.launching)return;
    if(event.type===TouchType.Down){
      this.pressed=true;
      if(this.motion){this.trail.burst(8,this.buttonWidth(),54);this.startFrames();}
    }else if(event.type===TouchType.Up||event.type===TouchType.Cancel){
      this.pressed=false;
    }
  }
  private launch(event:ClickEvent):void{
    if(!this.active||this.launching)return;
    this.pressed=false;
    if(!this.motion){this.onFind(event);return;}
    this.launching=true;this.trail.burst(10,this.buttonWidth(),54);this.startFrames();
    this.launchTimer=setTimeout(()=>{
      this.launchTimer=-1;
      if(!this.active)return;
      this.launching=false;this.stopFrames();this.onFind(event);
    },280);
  }
  build(){
    Stack(){
      Button({type:ButtonType.Normal,stateEffect:false}){
        Row({space:12}){
          Image($rawfile('ui/portrait_find.svg')).width(24).height(24).objectFit(ImageFit.Contain)
            .opacity(this.immersed()?0:1)
          Text(this.label).fontSize(16).fontColor('#FFFFFF')
            .opacity(this.immersed()?0:1)
        }.animation({duration:this.motion&&!this.immersed()?200:0,curve:Curve.EaseOut})
      }.id('begin-capture').width('100%').height(54).padding({left:20,right:20})
        .backgroundColor(this.immersed()?'#F0081225':'#F0243659')
        .border({width:1,color:this.immersed()?'#8397B5D1':'#A1ADC5E9'}).borderRadius(28)
        .shadow({radius:this.immersed()?12:24,color:this.immersed()?'#263F668A':'#536987BE'})
        .scale({x:this.pressed?.985:1,y:this.pressed?.985:1})
        .animation({duration:this.motion&&!this.immersed()?200:0,curve:Curve.EaseOut})
        .enabled(this.active&&!this.launching).accessibilityText(this.label)
        .onTouch((event:TouchEvent)=>this.touch(event)).onClick((event:ClickEvent)=>this.launch(event))
      Canvas(this.drawing).width(this.buttonWidth()).height(54).position({x:0,y:0})
        .hitTestBehavior(HitTestMode.None).accessibilityLevel('no').onReady(()=>this.prepared=true)
    }.width(this.buttonWidth()).height(54).borderRadius(28).clip(true)
  }
}

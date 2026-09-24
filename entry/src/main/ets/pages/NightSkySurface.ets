import { common } from '@kit.AbilityKit';

/** Fictional surface-particle memories gathered from one moving nebula. Personal portraits never enter the origin. */
@Component
export struct NightSkySurface {
  @Prop formation:number=0;
  @Prop musicPulse:number=0;
  @Prop motion:boolean=true;
  @Prop active:boolean=true;
  @Prop phaseMode:string='origin';
  private readonly skyCount:number=180;
  private skyX:Float32Array=new Float32Array(180);
  private skyY:Float32Array=new Float32Array(180);
  private skyZ:Float32Array=new Float32Array(180);
  private scatterX:Float32Array=new Float32Array(4200);
  private scatterY:Float32Array=new Float32Array(4200);
  private drawing:CanvasRenderingContext2D=new CanvasRenderingContext2D(new RenderingContextSettings(true));
  private glow:ImageBitmap|null=null;
  private prepared:boolean=false;
  private walker:DataView|null=null;
  private windowScene:DataView|null=null;
  private frameCount:number=20;
  private pointCount:number=4200;
  private loadStarted:boolean=false;
  private clock:number=0;
  private elapsed:number=0;
  private lastTick:number=0;
  private timer:number=-1;
  private stride:number=1;
  private slowFrames:number=0;

  private unit(seed:number):number {
    const value=Math.sin(seed*127.1+78.233)*43758.5453;
    return value-Math.floor(value);
  }
  private async loadScenes():Promise<void> {
    if(this.loadStarted)return;
    this.loadStarted=true;
    try {
      const context=this.getUIContext().getHostContext() as common.UIAbilityContext;
      const assets=await Promise.all([
        context.resourceManager.getRawFileContent('origin-walker.bin'),
        context.resourceManager.getRawFileContent('origin-window.bin')]);
      const scenes:DataView[]=[];
      for(const bytes of assets){
        const view=new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength);
        const frames=view.getUint16(6,true),points=view.getUint16(8,true),stride=view.getUint16(10,true);
        if(view.getUint32(0,true)!==0x4d554853||view.getUint16(4,true)!==1||
          frames!==20||points!==4200||stride!==6||bytes.byteLength!==16+frames*points*stride)
          throw new Error('origin motion asset format mismatch');
        scenes.push(view);
      }
      this.walker=scenes[0];this.windowScene=scenes[1];
      this.frameCount=20;this.pointCount=4200;
      console.info(`SELF_ORIGIN_SCENES_READY count=2 frames=20 points=4200 bytes=${assets[0].byteLength+assets[1].byteLength}`);
      this.draw();
    } catch(error) {console.error('SELF_ORIGIN_SCENES_FAILED '+String(error));}
  }
  private prepare():void {
    if(this.prepared)return;
    for(let i=0;i<this.skyCount;i++){
      this.skyX[i]=(this.unit(i*11+401)-.5)*2;
      this.skyY[i]=(this.unit(i*11+403)-.5)*2;
      this.skyZ[i]=.35+this.unit(i*11+407)*1.8;
    }
    for(let i=0;i<this.scatterX.length;i++){
      const a=this.unit(i*7+311)*Math.PI*2;
      const r=Math.sqrt(-2*Math.log(Math.max(.0001,this.unit(i*7+313))))*
        (i%13===0?.43:.23);
      this.scatterX[i]=.53+r*Math.cos(a)+r*Math.sin(a)*.29;
      this.scatterY[i]=.51+r*Math.sin(a)*.76;
    }
    try {
      const offscreen=new OffscreenCanvas(48,48);
      const brush=offscreen.getContext('2d');
      const halo=brush.createRadialGradient(24,24,0,24,24,24);
      halo.addColorStop(0,'rgba(224,238,255,0.85)');
      halo.addColorStop(.15,'rgba(191,221,254,0.48)');
      halo.addColorStop(.48,'rgba(137,179,235,0.16)');
      halo.addColorStop(1,'rgba(103,151,220,0)');
      brush.fillStyle=halo;
      brush.fillRect(0,0,48,48);
      this.glow=offscreen.transferToImageBitmap();
    } catch(error) {console.warn('SELF_PARTICLE_GLOW_FALLBACK '+String(error));}
    this.prepared=true;
  }
  private ambient(ctx:CanvasRenderingContext2D,w:number,h:number,t:number):void {
    const breathe=this.motion?Math.sin(t*.18)*.015:0;
    const x=w*(.54+breathe),y=h*.47;
    const radius=Math.min(w*.48,h*.72);
    const blue=ctx.createRadialGradient(x-radius*.26,y,0,x,y,radius);
    blue.addColorStop(0,'rgba(93,119,186,0.13)');
    blue.addColorStop(.46,'rgba(68,91,151,0.055)');
    blue.addColorStop(1,'rgba(40,57,112,0)');
    ctx.globalAlpha=1;
    ctx.fillStyle=blue;
    ctx.fillRect(0,0,w,h);
    const violet=ctx.createRadialGradient(w*.65,h*.35,0,w*.65,h*.35,radius*.78);
    violet.addColorStop(0,'rgba(146,108,181,0.055)');
    violet.addColorStop(1,'rgba(146,108,181,0)');
    ctx.fillStyle=violet;
    ctx.fillRect(0,0,w,h);
  }
  private drawSky(ctx:CanvasRenderingContext2D,w:number,h:number,t:number):void {
    const driftX=this.motion?Math.sin(t*.085)*w*.025:0;
    const driftY=this.motion?Math.cos(t*.07)*h*.012:0;
    const tau=Math.PI*2;
    for(let band=0;band<3;band++){
      ctx.beginPath();
      ctx.fillStyle=band===2?'#D9E7FC':band===1?'#AFC7E9':'#8FA6CF';
      ctx.globalAlpha=band===2?.48:band===1?.31:.18;
      for(let i=band;i<this.skyCount;i+=3){
        const z=this.skyZ[i];
        const x=w*.5+this.skyX[i]*w*.52/z+driftX/z;
        const y=h*.5+this.skyY[i]*h*.56/z+driftY/z;
        const r=i%31===0?2.3:band===2?1.6:1.0;
        ctx.moveTo(x+r,y);ctx.arc(x,y,r,0,tau);
      }
      ctx.fill();
    }
  }
  private drawMemory(ctx:CanvasRenderingContext2D,w:number,h:number,t:number):void {
    const phase=t%72;
    const indoor=phase>=30&&phase<66&&this.phaseMode==='origin';
    const data=indoor?this.windowScene:this.walker;
    let blend=1;
    if(phase>=17&&phase<23)blend=(1+Math.cos((phase-17)*Math.PI/6))*.5;
    else if(phase>=23&&phase<30)blend=0;
    else if(phase>=30&&phase<36)blend=(1-Math.cos((phase-30)*Math.PI/6))*.5;
    else if(phase>=53&&phase<59)blend=(1+Math.cos((phase-53)*Math.PI/6))*.5;
    else if(phase>=59&&phase<66)blend=0;
    else if(phase>=66)blend=(1-Math.cos((phase-66)*Math.PI/6))*.5;
    if(this.phaseMode==='sky')blend=0;
    if(this.phaseMode==='forming')blend=Math.max(0,Math.min(1,this.formation));
    if(!this.motion&&this.phaseMode==='origin')blend=1;
    if(data===null)blend=0;

    // The posed scene stops moving before dispersal, then its points release into the nebula.
    let pose=0;
    if(this.motion&&this.phaseMode==='origin'){
      if(phase<17)pose=phase*.56;
      else if(phase<23)pose=17*.56;
      else if(phase>=36&&phase<53)pose=(phase-36)/6.4166665;
      else if(phase>=53&&phase<59)pose=17/6.4166665;
    }
    const frame=(pose%1)*this.frameCount;
    const first=Math.floor(frame),next=(first+1)%this.frameCount,part=frame-first;
    const animate=part>.001&&blend>.001;
    const scale=Math.min(w*.88,h*(indoor?.68:.64))*(1+this.musicPulse*.025);
    const travel=!indoor&&this.motion&&this.phaseMode==='origin'&&phase<23?
      Math.sin(Math.min(phase,17)*.25)*.065:0;
    const yaw=!indoor&&this.motion?Math.sin(t*.12)*.12:0;
    const cosine=Math.cos(yaw),sine=Math.sin(yaw);
    const driftX=this.motion?Math.sin(t*.085)*w*.025:0;
    const driftY=this.motion?Math.cos(t*.07)*h*.012:0;
    const tau=Math.PI*2;
    const edges=indoor?[0,2300,3000,3900,4200]:[0,1050,2100,3150,4200];
    const colors=indoor?['#C4DAEB','#8AAACC','#9EC7B7','#778FB4']:
      ['#B4D1E8','#8DB3D6','#D7E7F5','#9CC2DE'];
    const formed=indoor?[.59,.36,.55,.20]:[.51,.43,.64,.49];
    const scattered=[.30,.21,.38,.24];
    for(let band=0;band<4;band++){
      ctx.beginPath();ctx.fillStyle=colors[band];
      ctx.globalAlpha=scattered[band]*(1-blend)+formed[band]*blend+this.musicPulse*.02;
      for(let i=edges[band];i<edges[band+1];i+=this.stride){
        const flow=this.motion?Math.sin(t*.23+i*.037)*.014:0;
        const looseX=(this.scatterX[i]+flow)*w+driftX;
        const looseY=(this.scatterY[i]+flow*.32)*h+driftY;
        let x=looseX,y=looseY,perspective=1;
        if(blend>.001&&data!==null){
          const offset=16+(first*this.pointCount+i)*6;
          let u=data.getInt16(offset,true),v=data.getInt16(offset+2,true);
          let depth=data.getInt16(offset+4,true);
          if(animate){
            const other=16+(next*this.pointCount+i)*6;
            u=u*(1-part)+data.getInt16(other,true)*part;
            v=v*(1-part)+data.getInt16(other+2,true)*part;
            depth=depth*(1-part)+data.getInt16(other+4,true)*part;
          }
          u/=32767;v/=32767;depth/=32767;
          const turned=u*cosine+depth*sine;
          const turnedDepth=depth*cosine-u*sine;
          perspective=1/(1-turnedDepth*.58);
          const formedX=w*(.55+travel)+turned*scale*perspective+driftX;
          const formedY=h*(indoor?.44:.47)+v*scale*perspective+driftY;
          const curl=Math.sin(t*.45+i*.071)*.025*blend*(1-blend);
          x=formedX*blend+looseX*(1-blend)+curl*w;
          y=formedY*blend+looseY*(1-blend)+curl*.40*h;
        }
        const r=(i%73===0?3.15:band===2?1.85:1.55)*perspective;
        if(this.glow!==null&&i%69===0)ctx.drawImage(this.glow,x-14,y-14,28,28);
        ctx.moveTo(x+r,y);ctx.arc(x,y,r,0,tau);
      }
      ctx.fill();
    }
  }
  private draw():void {
    const ctx=this.drawing,w=ctx.width,h=ctx.height;
    if(w<=0||h<=0)return;
    this.prepare();
    const started=Date.now();
    ctx.clearRect(0,0,w,h);
    const t=this.motion?this.elapsed:0;
    this.ambient(ctx,w,h,t);
    this.drawSky(ctx,w,h,t);
    this.drawMemory(ctx,w,h,t);
    ctx.globalAlpha=1;
    const spent=Date.now()-started;
    if(this.clock%120===0)console.info(`SELF_PARTICLES_FRAME mode=${this.phaseMode} phase=${Math.floor(t%72)} count=${Math.ceil(this.pointCount/this.stride)} ms=${spent}`);
    if(spent>32){this.slowFrames++;if(this.slowFrames>=4&&this.stride<3){this.stride++;this.slowFrames=0;}}
    else if(spent<19){this.slowFrames=Math.max(0,this.slowFrames-1);if(this.clock%200===0)this.stride=1;}
  }
  aboutToDisappear():void {
    if(this.timer>=0)clearInterval(this.timer);this.timer=-1;
    if(this.glow!==null){this.glow.close();this.glow=null;}
    this.prepared=false;this.walker=null;this.windowScene=null;this.loadStarted=false;
  }
  build(){
    Canvas(this.drawing).width('100%').height('100%').hitTestBehavior(HitTestMode.None)
      .onReady(()=>{
        this.prepare();this.loadScenes();this.draw();this.lastTick=Date.now();
        if(this.timer<0)this.timer=setInterval(()=>{
          const now=Date.now(),delta=Math.min(.12,(now-this.lastTick)/1000);this.lastTick=now;
          if(this.active){if(this.motion)this.elapsed+=delta;this.clock++;this.draw();}
        },33);
      })
  }
}

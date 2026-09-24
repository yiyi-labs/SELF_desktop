import { common } from '@kit.AbilityKit';

/** Fictional surface-particle memories gathered from one moving nebula. Personal portraits never enter the origin. */
@Component
export struct NightSkySurface {
  @Prop formation:number=0;
  @Prop musicPulse:number=0;
  @Prop motion:boolean=true;
  @Prop active:boolean=true;
  @Prop phaseMode:string='origin';
  onSceneChange:(index:number)=>void=()=>{};
  private readonly skyCount:number=180;
  private skyX:Float32Array=new Float32Array(180);
  private skyY:Float32Array=new Float32Array(180);
  private skyZ:Float32Array=new Float32Array(180);
  private scatterX:Float32Array=new Float32Array(4200);
  private scatterY:Float32Array=new Float32Array(4200);
  private drawing:CanvasRenderingContext2D=new CanvasRenderingContext2D(new RenderingContextSettings(true));
  private glow:ImageBitmap|null=null;
  private prepared:boolean=false;
  private scenes:Array<DataView|null>=[null,null,null,null,null];
  private frameCount:number=20;
  private pointCount:number=4200;
  private loadStarted:boolean=false;
  private clock:number=0;
  private elapsed:number=0;
  private lastTick:number=0;
  private timer:number=-1;
  private stride:number=1;
  private slowFrames:number=0;
  private touchX:number=-10000;
  private touchY:number=-10000;
  private touchHeld:boolean=false;
  private touchReleasedAt:number=0;
  private touchLastUpdateAt:number=0;
  private announcedScene:number=0;
  private layoutWidth:number=1;
  private layoutHeight:number=1;

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
        context.resourceManager.getRawFileContent('origin-window.bin'),
        context.resourceManager.getRawFileContent('origin-bridge.bin'),
        context.resourceManager.getRawFileContent('origin-horizon.bin'),
        context.resourceManager.getRawFileContent('origin-threshold.bin')]);
      const scenes:DataView[]=[];
      for(const bytes of assets){
        const view=new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength);
        const frames=view.getUint16(6,true),points=view.getUint16(8,true),stride=view.getUint16(10,true);
        if(view.getUint32(0,true)!==0x4d554853||view.getUint16(4,true)!==1||
          frames!==20||points!==4200||stride!==6||bytes.byteLength!==16+frames*points*stride)
          throw new Error('origin motion asset format mismatch');
        scenes.push(view);
      }
      for(let i=0;i<scenes.length;i++)this.scenes[i]=scenes[i];
      this.frameCount=20;this.pointCount=4200;
      let bytes=0;for(const asset of assets)bytes+=asset.byteLength;
      console.info(`SELF_ORIGIN_SCENES_READY count=5 frames=20 points=4200 bytes=${bytes}`);
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
    // Five memories over 220 seconds: a clear pause without a long wait.
    const phase=t%220;
    const segment=Math.floor(phase/44),local=phase%44;
    const sceneIndex=local>=37?(segment+1)%5:segment;
    if(this.phaseMode!=='origin')this.announcedScene=-1;
    if(this.phaseMode==='origin'&&sceneIndex!==this.announcedScene&&(local>=40||local<22)){
      this.announcedScene=sceneIndex;this.onSceneChange(sceneIndex);
    }
    const data=this.scenes[sceneIndex];
    let blend=local<22?1:local<29?(1+Math.cos((local-22)*Math.PI/7))*.5:
      local<37?0:(1-Math.cos((local-37)*Math.PI/7))*.5;
    if(this.phaseMode==='sky')blend=0;
    if(this.phaseMode==='forming')blend=Math.max(0,Math.min(1,this.formation));
    if(!this.motion&&this.phaseMode==='origin')blend=1;
    if(data===null)blend=0;

    // Pose, geometry and color meet at exactly equal endpoints. At the scene
    // switch the shared nebula is fully diffuse, so no new points can flash in.
    let pose=0;
    if(this.motion&&this.phaseMode==='origin'){
      const speed=sceneIndex===0?.56:sceneIndex===1?.156:sceneIndex===2?.46:.10;
      if(local<22)pose=(local*speed)%1;
      else if(local<29)pose=(22*speed)%1;
    }
    const frame=(pose%1)*this.frameCount;
    const first=Math.floor(frame),next=(first+1)%this.frameCount,part=frame-first;
    const animate=part>.001&&blend>.001;
    const scale=Math.min(w*.88,h*(sceneIndex===1?.68:.64))*(1+this.musicPulse*.025);
    const travel=sceneIndex===0&&this.motion&&this.phaseMode==='origin'&&local<29?
      Math.sin(Math.min(local,22)*.25)*.065:0;
    const yaw=this.motion?Math.sin(t*.12)*.12:0;
    const cosine=Math.cos(yaw),sine=Math.sin(yaw);
    const driftX=this.motion?Math.sin(t*.085)*w*.025:0;
    const driftY=this.motion?Math.cos(t*.07)*h*.012:0;
    const tau=Math.PI*2;
    const edges=[0,1050,2100,3150,4200];
    const colors=['#B9D1EB','#90B1D3','#D2E4F5','#A1C7D1'];
    const formed=[.55,.45,.61,.44];
    const scattered=[.30,.21,.38,.24];
    const touchAge=Date.now()-this.touchLastUpdateAt;
    const touchFade=this.touchHeld?Math.max(0,1-Math.max(0,touchAge-900)/440):
      Math.max(0,1-(Date.now()-this.touchReleasedAt)/440);
    const attraction=this.phaseMode==='origin'&&this.motion?touchFade:0;
    const touchX=this.touchX*w/Math.max(1,this.layoutWidth);
    const touchY=this.touchY*h/Math.max(1,this.layoutHeight);
    const radius=Math.min(w,h)*.09;
    const radiusSquared=radius*radius;
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
          const targetPerspective=1/(1-turnedDepth*.58);
          perspective=1+(targetPerspective-1)*blend;
          const formedX=w*(.55+travel)+turned*scale*targetPerspective+driftX;
          const formedY=h*(sceneIndex===1?.44:.47)+v*scale*targetPerspective+driftY;
          const curl=Math.sin(t*.45+i*.071)*.025*blend*(1-blend);
          x=formedX*blend+looseX*(1-blend)+curl*w;
          y=formedY*blend+looseY*(1-blend)+curl*.40*h;
        }
        if(attraction>0&&Math.abs(x-touchX)<radius&&Math.abs(y-touchY)<radius){
          const dx=touchX-x,dy=touchY-y,distanceSquared=dx*dx+dy*dy;
          if(distanceSquared<radiusSquared){
            const falloff=1-distanceSquared/radiusSquared;
            const pull=falloff*falloff*.42*attraction;
            x+=dx*pull;y+=dy*pull;
            if(this.glow!==null&&i%11===0)ctx.drawImage(this.glow,x-9,y-9,18,18);
          }
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
    if(this.clock%120===0)console.info(`SELF_PARTICLES_FRAME mode=${this.phaseMode} phase=${Math.floor(t%220)} scene=${Math.floor((t%220)/44)} count=${Math.ceil(this.pointCount/this.stride)} ms=${spent}`);
    if(spent>32){this.slowFrames++;if(this.slowFrames>=4&&this.stride<3){this.stride++;this.slowFrames=0;}}
    else if(spent<19){this.slowFrames=Math.max(0,this.slowFrames-1);if(this.clock%200===0)this.stride=1;}
  }
  aboutToDisappear():void {
    if(this.timer>=0)clearInterval(this.timer);this.timer=-1;
    if(this.glow!==null){this.glow.close();this.glow=null;}
    this.prepared=false;this.scenes=[null,null,null,null,null];this.loadStarted=false;
  }
  private touch(event:TouchEvent):void {
    if(this.phaseMode!=='origin'||!this.motion)return;
    const point=event.touches[0];
    if((event.type===TouchType.Down||event.type===TouchType.Move)&&point){
      this.touchX=point.x;this.touchY=point.y;this.touchHeld=true;this.touchLastUpdateAt=Date.now();
      if(event.type===TouchType.Down)console.info('SELF_ORIGIN_TOUCH local-attraction-start');
    }else if(event.type===TouchType.Up||event.type===TouchType.Cancel){
      this.touchHeld=false;this.touchReleasedAt=Date.now();
      console.info('SELF_ORIGIN_TOUCH local-attraction-release');
    }
  }
  build(){
    Canvas(this.drawing).width('100%').height('100%').hitTestBehavior(HitTestMode.Transparent)
      .onAreaChange((_old:Area,area:Area)=>{this.layoutWidth=Number(area.width);this.layoutHeight=Number(area.height);})
      .onTouch((event:TouchEvent)=>this.touch(event))
      .onReady(()=>{
        this.prepare();this.loadScenes();this.draw();this.lastTick=Date.now();
        if(this.timer<0)this.timer=setInterval(()=>{
          const now=Date.now(),delta=Math.min(.12,(now-this.lastTick)/1000);this.lastTick=now;
          if(this.active){if(this.motion)this.elapsed+=delta;this.clock++;this.draw();}
        },33);
      })
  }
}

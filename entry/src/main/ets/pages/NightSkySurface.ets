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
  private sceneReadyAt:number=0;
  private wasForming:boolean=false;
  private orbTime:number=0;
  private orbLastStepAt:number=0;
  private orbHeight:number=3.4;
  private orbVelocity:number=0;
  private orbFirstImpactAt:number=-1;
  private orbImpactAt:number=-1;
  private orbImpactIndex:number=0;
  private orbImpactStrength:number=0;
  private memoryPhaseOffset:number=0;
  private clock:number=0;
  private elapsed:number=0;
  private lastTick:number=0;
  private timer:number=-1;
  // A fixed, deterministic subset avoids whole bands flashing as load changes.
  private readonly stride:number=2;
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
      this.sceneReadyAt=Date.now();
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
  private formationAge():number{return this.wasForming?(this.motion?this.orbTime:3):0;}
  private advanceOrbPhysics():void {
    const now=Date.now();
    if(this.orbLastStepAt===0){this.orbLastStepAt=now;return;}
    const elapsed=Math.max(0,Math.min(.12,(now-this.orbLastStepAt)/1000));
    this.orbLastStepAt=now;
    if(!this.motion||elapsed===0)return;
    const steps=Math.max(1,Math.ceil(elapsed/.008));
    const step=elapsed/steps;
    for(let i=0;i<steps;i++){
      this.orbVelocity-=5.5*step;
      this.orbHeight+=this.orbVelocity*step;
      this.orbTime+=step;
      if(this.orbHeight<=0&&this.orbVelocity<0){
        const impactSpeed=-this.orbVelocity;
        this.orbHeight=0;
        // A faint ambient impulse at each contact sustains the motion. The
        // next arc still obeys gravity; only its launch speed changes gently.
        const next=this.orbImpactIndex+1;
        const targetSpeed=5.62+.19*Math.sin(next*1.61)+.08*Math.sin(next*.57);
        this.orbVelocity=this.orbImpactIndex===0?impactSpeed*.91:
          Math.max(5.25,Math.min(5.95,impactSpeed*.58+targetSpeed*.42));
        if(this.orbFirstImpactAt<0)this.orbFirstImpactAt=this.orbTime;
        this.orbImpactAt=this.orbTime;
        this.orbImpactIndex++;
        this.orbImpactStrength=Math.min(1,impactSpeed/6.2);
      }
    }
  }
  private drawFormationParticles(ctx:CanvasRenderingContext2D,w:number,h:number):void {
    const age=this.formationAge();
    if(this.motion&&this.orbImpactIndex===0)return;
    const sinceImpact=this.motion?Math.max(0,age-this.orbFirstImpactAt):3;
    const cx=w*.5,ground=h*.50,extent=Math.min(w,h);
    const spread=1-Math.exp(-sinceImpact*2.25);
    const visible=Math.min(1,sinceImpact*2.4);
    const orbRadius=extent*.030;
    const impactIndex=this.orbImpactIndex;
    const rippleAge=age-this.orbImpactAt;
    const waveActive=this.motion&&impactIndex>0&&rippleAge>=0&&rippleAge<1.35;
    const wavePhase=waveActive?rippleAge/1.35:0;
    const waveReach=orbRadius*(2.5+wavePhase*5.3);
    const waveEnergy=waveActive?(1-Math.exp(-rippleAge*18))*
      Math.exp(-rippleAge*2.8)*this.orbImpactStrength:0;
    const colors=['#B9D1EB','#90B1D3','#D2E4F5','#A1C7D1'];
    for(let band=0;band<4;band++){
      ctx.beginPath();ctx.fillStyle=colors[band];ctx.globalAlpha=[.27,.19,.33,.22][band];
      for(let i=band*1050;i<(band+1)*1050;i+=this.stride){
        if(this.unit(i*13+83)>visible)continue;
        const angle=this.unit(i*7+311)*Math.PI*2;
        const near=extent*(.008+this.unit(i*7+317)*.016);
        const startX=cx+Math.cos(angle)*near;
        const startY=ground+Math.sin(angle)*near*.24;
        const targetX=this.scatterX[i]*w;
        const targetY=this.scatterY[i]*h;
        const depth=.65+this.unit(i*17+29)*.7;
        const lift=Math.sin(Math.min(1,sinceImpact)*Math.PI)*extent*.025/depth;
        let x=startX+(targetX-startX)*spread;
        let y=startY+(targetY-startY)*spread-lift;
        let shimmer=0;
        const dx=x-cx,dy=y-ground;
        if(waveActive&&Math.abs(dx)<waveReach&&Math.abs(dy)<waveReach*.43){
          const planeY=dy/.39;
          const distance=Math.sqrt(dx*dx+planeY*planeY);
          const nearby=Math.exp(-distance*distance/(orbRadius*orbRadius*5.5));
          // Nearby stars leave the impact plane on a short ballistic arc;
          // their outward displacement then feeds the wider, fading wave.
          const lift=Math.max(0,4.0*rippleAge-7.0*rippleAge*rippleAge);
          y-=orbRadius*1.15*nearby*this.orbImpactStrength*lift;
          x+=dx/(distance+1)*orbRadius*.20*nearby*waveEnergy;
          shimmer+=nearby*lift*this.orbImpactStrength*.22;
          const direction=Math.atan2(planeY,dx);
          const uneven=1+.15*Math.sin(direction*3+impactIndex*1.91)+
            .09*Math.sin(direction*7-impactIndex*.83);
          const front=orbRadius*(.8+wavePhase*5.2)*uneven;
          const offset=(distance-front)/(orbRadius*.76);
          if(Math.abs(offset)<2.4){
            shimmer+=Math.exp(-offset*offset*1.05)*waveEnergy*
              (.85+this.unit(i*29+impactIndex*131)*.55);
            const push=orbRadius*.42*shimmer*Math.cos(offset*1.2);
            x+=dx/(distance+1)*push;
            y+=planeY/(distance+1)*push*.39;
          }
        }
        const radius=(band===2?1.9:1.55)*depth*(1+shimmer*.88);
        if(shimmer>.30&&i%17===0&&this.glow!==null)
          ctx.drawImage(this.glow,x-8,y-8,16,16);
        ctx.moveTo(x+radius,y);ctx.arc(x,y,radius,0,Math.PI*2);
      }
      ctx.fill();
    }
  }
  private drawFormationOrb(ctx:CanvasRenderingContext2D,w:number,h:number):void {
    const cx=w*.5,ground=h*.50;
    const radius=Math.min(w,h)*.019;
    const rise=this.motion?this.orbHeight*radius:0;
    const flightStretch=this.motion?Math.min(.028,Math.abs(this.orbVelocity)*.007):0;
    const collisionAge=this.orbTime-this.orbImpactAt;
    // Deformation begins at zero on contact, peaks after compression, and
    // springs back; the ring outline therefore never jumps between frames.
    const squash=this.motion&&this.orbImpactIndex>0&&collisionAge<.42?
      this.orbImpactStrength*Math.exp(-collisionAge*11)*Math.sin(collisionAge*22):0;
    const horizontal=radius*(1+squash*.13-flightStretch);
    const vertical=radius*(1-squash*.14+flightStretch);
    const cy=ground-vertical-rise;
    const light=ctx.createLinearGradient(cx-horizontal,cy-vertical,cx+horizontal,cy);
    light.addColorStop(0,'#8FAFD2');light.addColorStop(.30,'#F0F6FF');
    light.addColorStop(.65,'#B8D3E9');light.addColorStop(1,'#7898C3');
    ctx.globalAlpha=.88;
    ctx.strokeStyle=light;ctx.lineWidth=Math.max(2.4,radius*.093);
    ctx.shadowColor='#B6D6F0';ctx.shadowBlur=radius*.21;
    ctx.beginPath();ctx.ellipse(cx,cy,horizontal,vertical,0,0,Math.PI*2);ctx.stroke();
    ctx.shadowBlur=0;
    ctx.globalAlpha=.48;ctx.strokeStyle='#F7FBFF';ctx.lineWidth=Math.max(1,radius*.028);
    ctx.beginPath();ctx.ellipse(cx,cy,horizontal,vertical,0,-2.45,-1.48);ctx.stroke();
    ctx.globalAlpha=1;
  }
  private drawMemory(ctx:CanvasRenderingContext2D,w:number,h:number,t:number):void {
    if(this.phaseMode==='forming'){this.drawFormationParticles(ctx,w,h);return;}
    // Five memories over 220 seconds: a clear pause without a long wait.
    const phase=(t+this.memoryPhaseOffset)%220;
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
    if(this.phaseMode==='intro')blend=Math.max(0,Math.min(1,this.formation));
    if(!this.motion&&this.phaseMode==='origin')blend=1;
    if(data===null)blend=0;
    if(this.phaseMode==='origin'&&this.sceneReadyAt>0)
      blend*=Math.min(1,Math.max(0,(Date.now()-this.sceneReadyAt)/1200));

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
    if(this.phaseMode==='forming'&&this.active&&!this.wasForming){
      this.wasForming=true;this.orbTime=0;
      this.orbLastStepAt=0;this.orbHeight=3.4;this.orbVelocity=0;
      this.orbFirstImpactAt=-1;this.orbImpactAt=-1;this.orbImpactIndex=0;
      this.orbImpactStrength=0;
    }
    else if(this.phaseMode!=='forming'&&this.wasForming){
      this.memoryPhaseOffset=(29-this.elapsed%220+220)%220;this.wasForming=false;
    }
    if(this.phaseMode==='forming'&&this.active)this.advanceOrbPhysics();
    const started=Date.now();
    ctx.clearRect(0,0,w,h);
    const t=this.motion?this.elapsed:0;
    this.ambient(ctx,w,h,t);
    this.drawSky(ctx,w,h,t);
    this.drawMemory(ctx,w,h,t);
    if(this.phaseMode==='forming')this.drawFormationOrb(ctx,w,h);
    ctx.globalAlpha=1;
    const spent=Date.now()-started;
    if(this.clock%120===0)console.info(`SELF_PARTICLES_FRAME mode=${this.phaseMode} phase=${Math.floor(t%220)} scene=${Math.floor((t%220)/44)} count=${Math.ceil(this.pointCount/this.stride)} ms=${spent}`);
    if(spent>32&&this.clock%120===0)console.warn(`SELF_PARTICLES_SLOW ms=${spent}`);
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

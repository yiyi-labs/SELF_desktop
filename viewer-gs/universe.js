import { Application, Asset, Entity, Color, Vec3, Quat, FILLMODE_FILL_WINDOW, RESOLUTION_AUTO } from 'playcanvas';
import {clamp,smooth,position,cameraPosition,placeLabels} from './universe-layout.js';
import {galaxyTexture,planetTexture,drawSpace,galaxyStyles} from './universe-art.js';

const canvas=document.getElementById('universe'),starCanvas=document.getElementById('stars');
const brush=starCanvas.getContext('2d'),names=document.getElementById('names'),hint=document.getElementById('hint');
const travelText=document.getElementById('travel-text');
const report=(kind,message='')=>console.log('SELF_GALAXY_'+kind+(message?' '+message:''));
const finite3=v=>Array.isArray(v)&&v.length===3&&v.every(Number.isFinite);
const items=[],textures=[];
let app,camera,planet,selectedId='',track=0,wantTrack=0,clock=0,drawClock=0,loadClock=1;
let dragging=false,lastX=0,lastY=0,downX=0,downY=0,moved=false,lastNotify=0;
let motion=!matchMedia('(prefers-reduced-motion: reduce)').matches,language='zh',travel=null,booted=false,paused=false;
let currentCamera={x:0,y:0,z:12},visible=[],pendingManifest=null,pendingTravel='';
const aspect=()=>canvas.clientWidth/Math.max(1,canvas.clientHeight);
const center=index=>{const p=position(index,aspect());return new Vec3(p.x,p.y,p.z);};

function valid(record){
  return record&&/^[a-f0-9]{32}$/.test(record.id)&&typeof record.name==='string'&&record.name.length<=24&&
    record.view?.schemaVersion===1&&finite3(record.view.target)&&finite3(record.view.camera)&&finite3(record.view.up);
}
function remove(record){
  record.pivot?.destroy();record.pivot=null;
  if(record.asset){const asset=record.asset;record.asset=null;asset.unload();app.assets.remove(asset);}
  record.loading=false;
}
function load(record){
  if(!record.ready||record.asset||record.loading||!app||record.retryAt>performance.now())return;
  record.loading=true;
  const asset=new Asset('Memory '+record.id,'gsplat',{url:'https://self.local/galaxy/'+record.id+'.ply'});
  record.asset=asset;app.assets.add(asset);
  const failed=error=>{
    if(record.asset!==asset)return;
    record.retryAt=performance.now()+30000;remove(record);
    report('ASSET_ERROR',record.id+' '+String(error));
  };
  asset.on('error',failed);
  asset.on('load',()=>{
    if(record.asset!==asset)return;
    try{
      const view=record.view,target=new Vec3(...view.target),eye=new Vec3(...view.camera);
      const offset=eye.clone().sub(target),distance=offset.length();
      if(!Number.isFinite(distance)||distance<.01)throw new Error('invalid view distance');
      const backward=offset.normalize(),up=new Vec3(...view.up).normalize();
      up.sub(backward.clone().mulScalar(up.dot(backward))).normalize();
      const qFacing=new Quat().setFromDirections(backward,new Vec3(0,0,1));
      const qUp=new Quat().setFromDirections(qFacing.transformVector(up),new Vec3(0,1,0));
      const pivot=new Entity('Memory '+record.id),model=new Entity('Unmodified memory reconstruction');
      pivot.setPosition(center(record.index));pivot.setRotation(qUp.mul(qFacing));
      model.addComponent('gsplat',{asset});
      const centers=asset.resource.gsplatData.getCenters(),radii=[];
      for(let i=0;i<centers.length;i+=3){
        const radius=Math.hypot(centers[i]-target.x,centers[i+1]-target.y,centers[i+2]-target.z);
        if(Number.isFinite(radius))radii.push(radius);
      }
      radii.sort((a,b)=>a-b);
      const sceneRadius=radii[Math.floor(radii.length*.97)]||distance;
      // Presentation transform only; the source PLY, covariances and reconstruction remain untouched.
      const scale=clamp(.82/sceneRadius,.001,1.1);
      model.setLocalScale(scale,scale,scale);
      model.setLocalPosition(-target.x*scale,-target.y*scale,-target.z*scale);
      pivot.addChild(model);app.root.addChild(pivot);record.pivot=pivot;record.loadedAt=clock;record.loading=false;
      report('ASSET_READY',record.id+' '+asset.resource.gsplatData.numSplats);
    }catch(error){failed(error);}
  });
  app.assets.load(asset);
}
function goTo(id){
  if(travel)return;
  const item=items.find(x=>x.id===id);if(!item)return;
  selectedId=id;wantTrack=item.index;
  if(!motion)track=wantTrack;
  report('SELECT',id);
}
function travelTo(id){
  if(!booted){pendingTravel=id;return;}
  const item=items.find(x=>x.id===id);if(!item||travel)return;
  selectedId=id;wantTrack=item.index;
  travel={id,start:clock,from:{...currentCamera},sent:false};
  document.body.classList.add('travelling');
  travelText.textContent=language==='en'?'Following your light, back to this moment':'循着星光，回到那一刻';
  report('INTERACTION');
}
function cancelTravel(){
  pendingTravel='';if(!travel)return;
  travel=null;document.body.classList.remove('travelling');
}
function configure(options={}){
  if(typeof options.paused==='boolean'){paused=options.paused;if(app)app.autoRender=!paused;}
  if(typeof options.motion==='boolean')motion=options.motion;
  if(options.language==='en'||options.language==='zh')language=options.language;
  if(typeof options.embedded==='boolean')document.body.classList.toggle('embedded',options.embedded);
  document.documentElement.lang=language==='en'?'en':'zh-CN';
  hint.textContent=language==='en'?'Drift gently · follow a memory':'轻轻滑动 · 循光寻回一段记忆';
  document.getElementById('depth-far').textContent=language==='en'?'DISTANT MEMORIES':'更远的回忆';
  document.getElementById('depth-near').textContent=language==='en'?'CLOSER TO YOU':'此刻，近一些';
}
function sync(manifest){
  if(!manifest||!Array.isArray(manifest.items))return;
  if(!booted){pendingManifest=manifest;return;}
  const seen=new Set();
  const incoming=manifest.items.filter(record=>valid(record)&&!seen.has(record.id)&&seen.add(record.id)).slice(0,200);
  for(const old of items)if(!incoming.some(x=>x.id===old.id)){remove(old);old.label.remove();}
  let previousTheme=-1;
  const next=incoming.map((source,index)=>{
    let item=items.find(x=>x.id===source.id);
    if(!item){
      const label=document.createElement('button');label.type='button';label.className='galaxy-name';
      const title=document.createElement('span'),meta=document.createElement('small');label.append(title,meta);
      label.addEventListener('click',()=>goTo(source.id));names.append(label);
      const seed=parseInt(source.id.slice(-7),16);
      let theme=seed%galaxyStyles.length;
      // Stable per-memory colours, with a varied cadence instead of identical adjacent envelopes.
      if(theme===previousTheme)theme=(theme+1+Math.floor(seed/7)%4)%galaxyStyles.length;
      item={...source,index,theme,variant:seed%2,asset:null,pivot:null,loading:false,label,title,meta,retryAt:0,loadedAt:0};
    }else{
      if(item.ready&&!source.ready)remove(item);
      Object.assign(item,{name:source.name,view:source.view,ready:source.ready,index});
    }
    item.title.textContent=source.name;
    item.meta.textContent=String(index+1).padStart(2,'0')+' / '+String(incoming.length).padStart(2,'0');
    previousTheme=item.theme;
    item.label.setAttribute('aria-label',source.name);item.width=Math.min(320,Math.max(110,[...source.name].length*19+32));
    item.pivot?.setPosition(center(index));return item;
  });
  items.splice(0,items.length,...next);
  if(!items.some(x=>x.id===selectedId)){
    selectedId='';goTo(items.find(x=>x.id===manifest.selectedId)?.id||items[0]?.id);track=wantTrack;
  }else wantTrack=items.find(x=>x.id===selectedId).index;
  document.body.classList.toggle('empty',!items.length);
  report('READY',String(items.length));
  if(pendingTravel){const id=pendingTravel;pendingTravel='';travelTo(id);}
}
window.selfGalaxy={sync,goTo,travelTo,cancelTravel,configure};

function project(item){
  const p=center(item.index),screen=camera.camera.worldToScreen(p);
  const edge=camera.camera.worldToScreen(new Vec3(p.x+2.45,p.y,p.z));
  // CameraComponent already returns CSS pixels, independent of the backing store's pixel ratio.
  return {item,x:screen.x,y:screen.y,
    radius:Math.abs(edge.x-screen.x)*clamp(aspect()/.67,.75,1)/
      (1+Math.max(0,item.index-track)*.45),depth:screen.z};
}
function draw(){
  const width=canvas.clientWidth,height=canvas.clientHeight,dpr=Math.min(devicePixelRatio||1,1.6);
  if(starCanvas.width!==Math.round(width*dpr)||starCanvas.height!==Math.round(height*dpr)){
    starCanvas.width=Math.round(width*dpr);starCanvas.height=Math.round(height*dpr);
  }
  brush.setTransform(dpr,0,0,dpr,0,0);
  const flight=travel?smooth((clock-travel.start-.55)/1.65):0;
  const lower=Math.floor(track),blend=smooth(track-lower);
  const near=galaxyStyles[items[lower]?.theme??0],far=galaxyStyles[items[lower+1]?.theme??items[lower]?.theme??0];
  const mix=(a,b)=>a.map((value,index)=>Math.round(value+(b[index]-value)*blend));
  const theme={space:mix(near.space,far.space),light:mix(near.light,far.light)};
  drawSpace(brush,width,height,currentCamera,clock,motion?flight:0,motion,planet,theme);
  visible=items.filter(item=>item.index>=Math.floor(track)-1&&item.index-track<6||item.id===selectedId).map(project)
    .filter(p=>p.depth>.15&&p.radius>5&&p.x+p.radius>0&&p.x-p.radius<width&&p.y+p.radius>0&&p.y-p.radius<height);
  const masks=[];
  for(const p of [...visible].sort((a,b)=>b.depth-a.depth)){
    const selected=p.item.id===selectedId;
    const alpha=clamp(16/p.depth,.2,1)*smooth((p.depth-.6)/3)*clamp((6-(p.item.index-track))/2,0,1)*
      (travel?(selected?1-smooth((flight-.4)/.6):1-flight):1);
    const seed=p.item.theme*2+p.item.variant;
    brush.globalAlpha=alpha;
    brush.drawImage(textures[seed],p.x-p.radius,p.y-p.radius,p.radius*2,p.radius*2);
    if(p.item.pivot){
      const core=brush.createRadialGradient(p.x,p.y,0,p.x,p.y,p.radius*.39);
      core.addColorStop(0,`rgba(2,4,13,${.72*smooth((clock-p.item.loadedAt)/.8)})`);
      core.addColorStop(.5,'rgba(2,4,13,.25)');core.addColorStop(1,'rgba(2,4,13,0)');
      brush.fillStyle=core;brush.fillRect(p.x-p.radius*.4,p.y-p.radius*.4,p.radius*.8,p.radius*.8);
    }
    brush.globalAlpha=1;
    if(p.item.pivot){
      const fade=smooth((clock-p.item.loadedAt)/.8)*alpha*(travel?1-smooth((clock-travel.start-.55)/1.05):1);
      // Keep outlying preview splats inside this memory's core; the surrounding dust stays behind it.
      masks.push(`radial-gradient(circle ${p.radius*.5}px at ${p.x}px ${p.y}px,rgba(0,0,0,${fade}) 0%,rgba(0,0,0,${fade}) 45%,transparent 100%)`);
    }
  }
  canvas.style.maskImage=canvas.style.webkitMaskImage=masks.length?masks.join(','):'linear-gradient(transparent,transparent)';
  const candidates=visible.filter(p=>p.depth>4&&p.depth<45&&(!travel||p.item.id===selectedId)).map(p=>({
    id:p.item.id,x:p.x,y:p.y+p.radius*.49+10,width:p.item.width,depth:p.depth,selected:p.item.id===selectedId}));
  const obstacles=visible.map(p=>({id:p.item.id,x:p.x-p.radius*.72,y:p.y-p.radius*.48,width:p.radius*1.44,height:p.radius*.96}));
  const placed=placeLabels(candidates,width,height,obstacles);
  for(const item of items){
    const p=placed.find(x=>x.id===item.id),selected=item.id===selectedId;
    item.label.style.opacity=p&&!travel?String(selected?1:clamp(20/p.depth,.46,.8)):'0';
    item.label.style.visibility=p&&!travel?'visible':'hidden';item.label.tabIndex=p&&!travel?0:-1;
    item.label.classList.toggle('chosen',selected);item.label.setAttribute('aria-pressed',String(selected));
    if(p){item.label.style.left=p.x+'px';item.label.style.top=p.y+'px';item.label.style.width=p.width+'px';}
  }
}
function update(dt){
  if(paused)return;
  dt=Math.min(dt,.05);clock+=dt;drawClock+=dt;loadClock+=dt;
  const gain=motion?1-Math.exp(-dt*3.6):1;
  track+=(wantTrack-track)*gain;
  let target=cameraPosition(track,aspect());
  if(travel){
    const item=items.find(x=>x.id===travel.id);
    if(!item){cancelTravel();return;}
    const p=position(item.index,aspect()),progress=smooth((clock-travel.start)/(motion?2.35:.15));
    const t=motion?progress:0;
    target={x:travel.from.x+(p.x-travel.from.x)*t,y:travel.from.y+(p.y-travel.from.y)*t,
      z:travel.from.z+(p.z+.95-travel.from.z)*t};
    if(!travel.sent&&progress>=1){travel.sent=true;report('APPROACH_COMPLETE',travel.id);}
  }
  if(travel)currentCamera=target;
  else for(const axis of ['x','y','z'])currentCamera[axis]+=(target[axis]-currentCamera[axis])*gain;
  camera.setPosition(currentCamera.x,currentCamera.y,currentCamera.z);
  camera.setEulerAngles(0,0,0);
  if(loadClock>.4){
    loadClock=0;
    const nearby=items.filter(item=>item.ready&&Math.abs(item.index-wantTrack)<1.6)
      .sort((a,b)=>Math.abs(a.index-wantTrack)-Math.abs(b.index-wantTrack)).slice(0,3);
    const keep=new Set(nearby.map(item=>item.id));
    for(const item of items)if(item.asset&&!keep.has(item.id))remove(item);
    for(const item of nearby)load(item);
  }
  if(drawClock>1/30){drawClock=0;draw();}
}

async function start(){
  if(!canvas.getContext('webgl2',{antialias:false,alpha:true}))throw new Error('WebGL2 unavailable');
  app=new Application(canvas,{graphicsDeviceOptions:{antialias:false,alpha:true}});
  app.graphicsDevice.maxPixelRatio=Math.min(devicePixelRatio||1,1.6);
  app.setCanvasFillMode(FILLMODE_FILL_WINDOW);app.setCanvasResolution(RESOLUTION_AUTO);
  app.scene.ambientLight=new Color(1,1,1);
  camera=new Entity('Memory journey camera');
  camera.addComponent('camera',{clearColor:new Color(0,0,0,0),fov:52,nearClip:.03,farClip:3000});
  app.root.addChild(camera);
  const photographs=await Promise.all(['memory-galaxy-blue','memory-galaxy-violet','memory-galaxy'].map(name=>new Promise(resolve=>{
    const texture=new Image();texture.onload=()=>resolve(texture);texture.onerror=()=>resolve(null);
    texture.src='galaxy-assets/'+name+'.png';
  })));
  for(let i=0;i<galaxyStyles.length;i++)for(let variant=0;variant<2;variant++)
    textures.push(galaxyTexture(12+i*2+variant,photographs[galaxyStyles[i].photo],galaxyStyles[i]));
  planet=planetTexture();
  booted=true;configure();
  if(pendingManifest){sync(pendingManifest);pendingManifest=null;}
  currentCamera=cameraPosition(track,aspect());
  app.on('update',update);app.start();
  report('RENDER_READY');
  // A native sync can arrive before fetch completes; do not overwrite its newer manifest.
  if(!items.length){
    try{const response=await fetch('https://self.local/galaxies.json');
      if(!response.ok)throw new Error('history manifest unavailable');
      const manifest=await response.json();if(!items.length)sync(manifest);
    }catch(error){report('ERROR',String(error));}
  }
  canvas.addEventListener('pointerdown',event=>{
    if(travel)return;dragging=true;moved=false;downX=lastX=event.clientX;downY=lastY=event.clientY;
    report('INTERACTION');lastNotify=performance.now();
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener('pointermove',event=>{
    if(!dragging||travel)return;
    const dx=event.clientX-lastX,dy=event.clientY-lastY;lastX=event.clientX;lastY=event.clientY;
    if(Math.hypot(event.clientX-downX,event.clientY-downY)>7)moved=true;
    if(!moved)return;
    wantTrack=clamp(wantTrack+(dy*.85-dx*.45)/Math.max(260,canvas.clientHeight*.56),0,Math.max(0,items.length-1));
    if(performance.now()-lastNotify>1600){report('INTERACTION');lastNotify=performance.now();}
  });
  canvas.addEventListener('pointerup',event=>{
    if(!dragging)return;dragging=false;
    if(moved){goTo(items[Math.round(wantTrack)]?.id);return;}
    const rect=canvas.getBoundingClientRect(),x=event.clientX-rect.left,y=event.clientY-rect.top;
    const closest=visible.filter(p=>Math.hypot((p.x-x),(p.y-y)*1.45)<Math.max(28,p.radius*.8))
      .sort((a,b)=>Math.hypot(a.x-x,a.y-y)-Math.hypot(b.x-x,b.y-y))[0];
    if(closest)goTo(closest.item.id);
  });
  canvas.addEventListener('pointercancel',()=>{
    if(!dragging)return;dragging=false;
    // An OS-interrupted gesture still settles on a memory; keep its name and native controls in sync.
    goTo(items[Math.round(wantTrack)]?.id);
  });
  canvas.addEventListener('wheel',event=>{
    event.preventDefault();if(travel)return;
    if(performance.now()-lastNotify>800){report('INTERACTION');lastNotify=performance.now();}
    wantTrack=clamp(wantTrack+clamp(event.deltaY*.002,-.65,.65),0,Math.max(0,items.length-1));
    const item=items[Math.round(wantTrack)];if(item&&item.id!==selectedId){selectedId=item.id;report('SELECT',selectedId);}
  },{passive:false});
  canvas.addEventListener('keydown',event=>{
    if(!['ArrowUp','ArrowRight','ArrowDown','ArrowLeft'].includes(event.key)||travel)return;
    event.preventDefault();goTo(items[clamp(Math.round(wantTrack)+(event.key==='ArrowUp'||event.key==='ArrowRight'?1:-1),0,items.length-1)]?.id);
  });
  window.addEventListener('resize',()=>{
    app.resizeCanvas();for(const item of items)item.pivot?.setPosition(center(item.index));
  });
  canvas.addEventListener('webglcontextlost',event=>{event.preventDefault();report('ERROR','星光暂时中断，请返回后重试');});
  window.addEventListener('pagehide',()=>{for(const item of items)remove(item);app.destroy();});
}
start().catch(error=>report('ERROR',String(error)));

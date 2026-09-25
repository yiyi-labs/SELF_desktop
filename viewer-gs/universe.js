import { Application, Asset, Entity, Color, Vec3, Quat, FILLMODE_FILL_WINDOW, RESOLUTION_AUTO } from 'playcanvas';

const canvas=document.getElementById('universe');
const starCanvas=document.getElementById('stars');
const starBrush=starCanvas.getContext('2d');
const names=document.getElementById('names');
const hint=document.getElementById('hint');
const report=(kind,message='')=>console.log('SELF_GALAXY_'+kind+(message?' '+message:''));
const finite3=v=>Array.isArray(v)&&v.length===3&&v.every(Number.isFinite);
const clamp=(v,min,max)=>Math.max(min,Math.min(max,v));
const lanes=[0,-2.65,2.65,-1.4,1.45];
const heights=[-.2,.62,-.55,.85,-.78];
const depths=[-.4,-1.55,-2.75,-4.1,-5.35];
const items=[];
let app,camera,selectedId='',camX=0,camY=.25,camZ=8.6,wantX=0,wantY=.25,wantZ=8.6;
let dragging=false,lastX=0,lastY=0,moved=false,lastNotify=0;
let starClock=0;
const stars=Array.from({length:76},(_,index)=>{
  const hash=n=>{const x=Math.sin(n*127.1+78.233)*43758.5453;return x-Math.floor(x);};
  return {x:(hash(index*7+1)-.5)*38,y:(hash(index*7+2)-.5)*21,
    z:-18-hash(index*7+3)*16,brightness:.16+hash(index*7+4)*.35,
    radius:.55+hash(index*7+5)*1.1};
});

function valid(record){
  return record&&/^[a-f0-9]{32}$/.test(record.id)&&typeof record.name==='string'&&record.name.length<=24&&
    record.view?.schemaVersion===1&&finite3(record.view.target)&&finite3(record.view.camera)&&finite3(record.view.up);
}
function center(index){
  // Alternate left and right, then move gently into depth. No central sun or straight row.
  const lane=index%lanes.length,layer=Math.floor(index/lanes.length);
  return new Vec3(lanes[lane]+Math.sin(layer*1.3+lane*.7)*.18,
    heights[lane]+Math.sin(layer*.9)*.25,depths[lane]-layer*5.8);
}
function remove(record){
  if(record.pivot){record.pivot.destroy();record.pivot=null;}
  if(record.asset){record.asset.unload();app.assets.remove(record.asset);record.asset=null;}
  record.loading=false;
}
function load(record){
  if(!record.ready||record.asset||record.loading||!app)return;
  record.loading=true;
  const asset=new Asset('Galaxy '+record.id,'gsplat',{url:'https://self.local/galaxy/'+record.id+'.ply'});
  record.asset=asset;
  app.assets.add(asset);
  asset.on('error',error=>{report('ERROR','星辰暂时无法展开：'+String(error));remove(record);});
  asset.on('load',()=>{
    if(record.asset!==asset)return;
    try{
      const view=record.view,target=new Vec3(...view.target),eye=new Vec3(...view.camera);
      const offset=eye.clone().sub(target),distance=offset.length();
      if(!Number.isFinite(distance)||distance<.01)throw new Error('invalid view distance');
      const backward=offset.normalize();
      const up=new Vec3(...view.up).normalize();
      up.sub(backward.clone().mulScalar(up.dot(backward))).normalize();
      const qFacing=new Quat().setFromDirections(backward,new Vec3(0,0,1));
      const qUp=new Quat().setFromDirections(qFacing.transformVector(up),new Vec3(0,1,0));
      const pivot=new Entity('Galaxy '+record.id);
      pivot.setPosition(center(record.index));
      pivot.setRotation(qUp.mul(qFacing));
      const model=new Entity('Whole reconstructed scene');
      model.addComponent('gsplat',{asset});
      const centers=asset.resource.gsplatData.getCenters(),radii=[];
      for(let i=0;i<centers.length;i+=3){
        const r=Math.hypot(centers[i]-target.x,centers[i+1]-target.y,centers[i+2]-target.z);
        if(Number.isFinite(r))radii.push(r);
      }
      radii.sort((a,b)=>a-b);
      const sceneRadius=radii[Math.floor(radii.length*.94)]||distance;
      // Fit the complete reconstruction into a miniature, not merely its face.
      const scale=clamp(1.18/sceneRadius,.012,1.1);
      model.setLocalScale(scale,scale,scale);
      model.setLocalPosition(-target.x*scale,-target.y*scale,-target.z*scale);
      pivot.addChild(model);app.root.addChild(pivot);record.pivot=pivot;
      report('ASSET_READY',record.id+' '+asset.resource.gsplatData.numSplats);
      if(record.id===selectedId)report('RENDER_READY',record.id);
      hint.classList.add('quiet');
    }catch(error){report('ERROR','星辰绘制暂不可用：'+String(error));remove(record);}
  });
  app.assets.load(asset);
}
function chooseNearest(){
  if(!items.length)return;
  let best=items[0],distance=Infinity;
  const focus=new Vec3(wantX,wantY-.22,wantZ-8.6);
  for(const item of items){const d=center(item.index).distance(focus);if(d<distance){best=item;distance=d;}}
  if(best.id!==selectedId){selectedId=best.id;report('SELECT',selectedId);}
}
function goTo(id){
  const item=items.find(x=>x.id===id);if(!item)return;
  selectedId=id;const p=center(item.index);wantX=p.x;wantY=p.y+.22;wantZ=p.z+8.6;
  report('SELECT',id);
}
function tapGalaxy(x,y){
  let closest=null,best=Infinity;
  for(const item of items){
    if(!item.ready)continue;
    const p=camera.camera.worldToScreen(center(item.index));
    if(p.z<=0)continue;
    const dx=(p.x/canvas.width*canvas.clientWidth)-x;
    const dy=(p.y/canvas.height*canvas.clientHeight)-y;
    const distance=Math.hypot(dx,dy);
    if(distance<best){best=distance;closest=item;}
  }
  if(closest&&best<Math.min(canvas.clientWidth*.19,220))goTo(closest.id);
}
function drawStars(){
  if(starCanvas.width!==canvas.width||starCanvas.height!==canvas.height){
    starCanvas.width=canvas.width;starCanvas.height=canvas.height;
  }
  starBrush.clearRect(0,0,starCanvas.width,starCanvas.height);
  for(const star of stars){
    const p=camera.camera.worldToScreen(new Vec3(star.x,star.y,star.z));
    if(p.z<=0||p.x<0||p.y<0||p.x>starCanvas.width||p.y>starCanvas.height)continue;
    starBrush.beginPath();starBrush.arc(p.x,p.y,star.radius,0,Math.PI*2);
    starBrush.fillStyle=`rgba(190,211,245,${star.brightness})`;starBrush.fill();
  }
}
function sync(manifest){
  if(!manifest||!Array.isArray(manifest.items))return;
  const incoming=manifest.items.filter(valid).slice(0,200);
  for(const old of items){if(!incoming.some(x=>x.id===old.id)){remove(old);old.label?.remove();}}
  const next=[];
  for(let i=0;i<incoming.length;i++){
    const source=incoming[i];let item=items.find(x=>x.id===source.id);
    if(!item){
      const label=document.createElement('span');label.className='galaxy-name';label.textContent=source.name;
      label.addEventListener('click',()=>goTo(source.id));names.append(label);
      item={...source,index:i,asset:null,pivot:null,loading:false,label};
    }else{
      item.name=source.name;item.label.textContent=source.name;item.view=source.view;item.index=i;
      if(item.ready&&!source.ready)remove(item);
      item.ready=source.ready;
      if(item.pivot)item.pivot.setPosition(center(i));
    }
    next.push(item);
  }
  items.splice(0,items.length,...next);
  if(!items.some(x=>x.id===selectedId))goTo(manifest.selectedId||items[0]?.id);
  if(items.length)report('READY',String(items.length));
}
window.selfGalaxy={sync,goTo};

function update(dt){
  const gain=1-Math.exp(-Math.min(dt,.05)*5.5);
  camX+=(wantX-camX)*gain;camY+=(wantY-camY)*gain;camZ+=(wantZ-camZ)*gain;
  camera.setPosition(camX,camY,camZ);
  camera.lookAt(camX,camY-.18,camZ-8.6);
  starClock+=dt;if(starClock>.06){starClock=0;drawStars();}
  const focus=new Vec3(camX,camY-.22,camZ-8.6);
  const nearest=items.map(item=>({item,d:center(item.index).distance(focus)})).sort((a,b)=>a.d-b.d).slice(0,3);
  const keep=new Set(nearest.map(x=>x.item.id));
  for(const item of items){if(!keep.has(item.id)&&item.asset)remove(item);}
  for(const entry of nearest)load(entry.item);
  for(const item of items){
    const p=center(item.index),screen=camera.camera.worldToScreen(new Vec3(p.x,p.y+1.75,p.z));
    const visible=screen.z>0&&screen.x>-90&&screen.x<canvas.width+90&&screen.y>-40&&screen.y<canvas.height+40;
    item.label.style.opacity=visible?String(clamp(1-Math.abs(p.x-camX)/11,.3,1)):'0';
    item.label.style.left=(screen.x/canvas.width*100)+'%';
    item.label.style.top=(screen.y/canvas.height*100)+'%';
    item.label.classList.toggle('chosen',item.id===selectedId);
  }
}

async function start(){
  if(!canvas.getContext('webgl2',{antialias:false,alpha:true}))throw new Error('WebGL2 unavailable');
  app=new Application(canvas,{graphicsDeviceOptions:{antialias:false,alpha:true}});
  app.setCanvasFillMode(FILLMODE_FILL_WINDOW);app.setCanvasResolution(RESOLUTION_AUTO);
  app.scene.ambientLight=new Color(1,1,1);
  app.scene.fog='linear';app.scene.fogColor=new Color(.04,.07,.14);app.scene.fogStart=9.8;app.scene.fogEnd=19;
  app.start();
  camera=new Entity('Universe camera');
  camera.addComponent('camera',{clearColor:new Color(0,0,0,0),fov:58,nearClip:.03,farClip:1000});
  app.root.addChild(camera);app.on('update',update);
  const response=await fetch('https://self.local/galaxies.json');
  if(!response.ok)throw new Error('history manifest unavailable');
  sync(await response.json());
  canvas.addEventListener('pointerdown',event=>{dragging=true;moved=false;lastX=event.clientX;lastY=event.clientY;canvas.setPointerCapture(event.pointerId);});
  canvas.addEventListener('pointermove',event=>{
    if(!dragging)return;
    const dx=event.clientX-lastX,dy=event.clientY-lastY;lastX=event.clientX;lastY=event.clientY;
    if(Math.abs(dx)+Math.abs(dy)>1)moved=true;
    wantX=clamp(wantX-dx*.018,-5.2,5.2);
    wantY=clamp(wantY+dy*.006,-2.3,2.5);
    const depth=Math.floor(Math.max(0,items.length-1)/5)*5.8;
    wantZ=clamp(wantZ+dy*.011,1.8-depth,15);
    if(performance.now()-lastNotify>1600){report('INTERACTION');lastNotify=performance.now();}
  });
  const release=event=>{
    if(!dragging)return;dragging=false;
    if(moved)chooseNearest();
    else tapGalaxy(event.clientX-canvas.getBoundingClientRect().left,event.clientY-canvas.getBoundingClientRect().top);
  };
  canvas.addEventListener('pointerup',release);canvas.addEventListener('pointercancel',release);
  canvas.addEventListener('wheel',event=>{
    const depth=Math.floor(Math.max(0,items.length-1)/5)*5.8;
    wantZ=clamp(wantZ+event.deltaY*.012,1.8-depth,15);event.preventDefault();
  },{passive:false});
  window.addEventListener('resize',()=>app.resizeCanvas());
}
start().catch(error=>report('ERROR',String(error)));

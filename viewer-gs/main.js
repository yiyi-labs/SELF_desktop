import { Application, Asset, Entity, FILLMODE_FILL_WINDOW, RESOLUTION_AUTO, Color } from 'playcanvas';

const canvas=document.getElementById('portrait');
const status=document.getElementById('status');
const report=(kind,message)=>{status.textContent=message;console.log(`SELF_GS_VIEWER_${kind} ${message}`);};
const finite3=(v)=>Array.isArray(v)&&v.length===3&&v.every(Number.isFinite);
const normal=(v)=>{const n=Math.hypot(...v);return v.map(x=>x/n);};
const rotate=(v,a,t)=>{
  const c=Math.cos(t),s=Math.sin(t),d=v[0]*a[0]+v[1]*a[1]+v[2]*a[2];
  return [v[0]*c+(a[1]*v[2]-a[2]*v[1])*s+a[0]*d*(1-c),
    v[1]*c+(a[2]*v[0]-a[0]*v[2])*s+a[1]*d*(1-c),
    v[2]*c+(a[0]*v[1]-a[1]*v[0])*s+a[2]*d*(1-c)];
};

async function start() {
  const gl=canvas.getContext('webgl2',{antialias:false,alpha:true});
  if(!gl)throw new Error('这台设备没有提供 WebGL2 绘制能力');
  const response=await fetch('https://self.local/portrait.view.json');
  if(!response.ok)throw new Error('个人模型视角尚未就绪');
  const view=await response.json();
  if(view.schemaVersion!==1||!finite3(view.target)||!finite3(view.camera)||!finite3(view.up)||
     !Number.isFinite(view.fovDegrees)||view.fovDegrees<10||view.fovDegrees>90)
    throw new Error('个人模型视角内容不正确');

  const app=new Application(canvas,{graphicsDeviceOptions:{antialias:false,alpha:true}});
  app.setCanvasFillMode(FILLMODE_FILL_WINDOW);
  app.setCanvasResolution(RESOLUTION_AUTO);
  app.scene.ambientLight=new Color(1,1,1);
  app.start();
  const camera=new Entity('Portrait camera');
  camera.addComponent('camera',{clearColor:new Color(.04,.06,.11,0),fov:view.fovDegrees,nearClip:.01,farClip:10000});
  app.root.addChild(camera);

  const asset=new Asset('Personal 3DGS','gsplat',{url:'https://self.local/portrait.gaussian.ply'});
  app.assets.add(asset);
  asset.on('error',error=>report('ERROR','立体面容暂时无法打开：'+String(error)));
  asset.on('load',()=>{
    try {
      const model=new Entity('Personal 3DGS');
      model.addComponent('gsplat',{asset});
      app.root.addChild(model);
      const target=view.target,up=normal(view.up),original=view.camera.map((x,i)=>x-target[i]);
      const radius=Math.hypot(...original);
      if(!Number.isFinite(radius)||radius<.01)throw new Error('个人模型相机参数不完整');
      const openingZoom=view.targetFaceFraction===.5?1:1.36;
      let yaw=0,pitch=0,zoom=openingZoom,targetYaw=0,targetPitch=0,targetZoom=openingZoom;
      const update=()=>{
        yaw+=(targetYaw-yaw)*.2;pitch+=(targetPitch-pitch)*.2;zoom+=(targetZoom-zoom)*.2;
        const afterYaw=rotate(original,up,yaw);
        const forward=normal(afterYaw.map(x=>-x));
        const right=normal([forward[1]*up[2]-forward[2]*up[1],
          forward[2]*up[0]-forward[0]*up[2],forward[0]*up[1]-forward[1]*up[0]]);
        const offset=rotate(afterYaw,right,pitch);
        camera.setPosition(...offset.map((x,i)=>target[i]+x*zoom));
        camera.lookAt(...target,...up);
      };
      app.on('update',update);update();
      let touching=false,lastX=0,lastY=0;
      let lastInteraction=-2000;
      const interaction=()=>{if(performance.now()-lastInteraction>1800){lastInteraction=performance.now();console.log('SELF_GS_VIEWER_INTERACTION');}};
      canvas.addEventListener('pointerdown',event=>{interaction();touching=true;lastX=event.clientX;lastY=event.clientY;canvas.setPointerCapture(event.pointerId);});
      canvas.addEventListener('pointermove',event=>{if(!touching)return;interaction();targetYaw+=(event.clientX-lastX)*.008;targetPitch=Math.max(-.9,Math.min(.9,targetPitch+(event.clientY-lastY)*.008));lastX=event.clientX;lastY=event.clientY;});
      canvas.addEventListener('pointerup',()=>touching=false);
      canvas.addEventListener('pointercancel',()=>touching=false);
      canvas.addEventListener('wheel',event=>{targetZoom=Math.max(.35,Math.min(4,targetZoom*Math.exp(event.deltaY*.001)));event.preventDefault();},{passive:false});
      report('READY',`已载入 ${asset.resource.gsplatData.numSplats} 个立体细节点，可拖动观察`);
      setTimeout(()=>status.classList.add('quiet'),2200);
      console.log(`SELF_GS_VIEWER_VIEW ${view.sourceFrame} ${view.faceTrackCount} ${view.fovDegrees}`);
    } catch(error) { report('ERROR','立体面容绘制失败：'+String(error)); }
  });
  app.assets.load(asset);
  window.addEventListener('resize',()=>app.resizeCanvas());
}
start().catch(error=>report('ERROR','立体面容绘制不可用：'+String(error)));

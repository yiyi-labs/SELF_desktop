import { Application, Asset, Entity, FILLMODE_FILL_WINDOW, RESOLUTION_AUTO, WORKBUFFER_UPDATE_ONCE, Color, Vec3 } from 'playcanvas';
import { selectVisibleSplats, normalizeLasso, selectionSlot, shouldRecordLassoPoint, makeOriginalColors, applyDigitalTint, applyDigitalLayers, DIGITAL_PRESETS } from './gs-edit.js';

const canvas=document.getElementById('portrait'), outline=document.getElementById('lasso'), status=document.getElementById('status');
const preview=document.body.dataset.preview==='true';
const report=(kind,message)=>{status.textContent=message;console.log(`SELF_GS_VIEWER_${kind} ${message}`);};
const finite3=v=>Array.isArray(v)&&v.length===3&&v.every(Number.isFinite);
const normal=v=>{const n=Math.hypot(...v);return v.map(x=>x/n);};
const rotate=(v,a,t)=>{const c=Math.cos(t),s=Math.sin(t),d=v[0]*a[0]+v[1]*a[1]+v[2]*a[2];
  return [v[0]*c+(a[1]*v[2]-a[2]*v[1])*s+a[0]*d*(1-c),
    v[1]*c+(a[2]*v[0]-a[0]*v[2])*s+a[1]*d*(1-c),
    v[2]*c+(a[0]*v[1]-a[1]*v[0])*s+a[2]*d*(1-c)];};

let port,identity,modelReady=false,command=()=>{};
const send=(type,payload={})=>{if(port&&identity)port.postMessage(JSON.stringify({schemaVersion:1,...identity,requestId:'',type,payload}));};
const sendBytes=(kind,bytes)=>{const transferId=`gs-${Date.now()}-${Math.floor(Math.random()*100000)}`;
  send('TRANSFER_BEGIN',{transferId,kind,length:bytes.byteLength});
  for(let offset=0;offset<bytes.byteLength;offset+=65536)
    port.postMessage(bytes.buffer.slice(bytes.byteOffset+offset,bytes.byteOffset+Math.min(offset+65536,bytes.byteLength)));
  send('TRANSFER_END',{transferId});};
window.addEventListener('message',event=>{
  if(event.data!=='SELF_PORT_V1'||event.ports.length!==1||port)return;
  port=event.ports[0];
  port.onmessage=e=>{if(typeof e.data!=='string')return;
    try{const frame=JSON.parse(e.data);
      if(frame.schemaVersion!==1)return;
      if(frame.type==='INIT'){identity={sessionId:frame.sessionId,assetId:frame.assetId,assetVersion:frame.assetVersion,revision:frame.revision};return;}
      if(!identity||frame.sessionId!==identity.sessionId||frame.assetId!==identity.assetId)return;
      if(frame.type==='GS_COMMAND')command(frame.payload);
    }catch(error){send('GS_FAILED',{message:String(error)});}};
  if(modelReady)port.postMessage(JSON.stringify({schemaVersion:1,type:'READY',payload:{webgl2:true}}));
});
const pngBytes=dataUrl=>Uint8Array.from(atob(dataUrl.split(',')[1]),c=>c.charCodeAt(0));

async function start(){
  if(!canvas.getContext('webgl2',{antialias:false,alpha:true,preserveDrawingBuffer:true}))throw Error('这台设备没有提供 WebGL2 绘制能力');
  const response=await fetch('https://self.local/portrait.view.json');
  if(!response.ok)throw Error('个人模型视角尚未就绪');
  const view=await response.json();
  if(view.schemaVersion!==1||!finite3(view.target)||!finite3(view.camera)||!finite3(view.up)||
    !Number.isFinite(view.fovDegrees)||view.fovDegrees<10||view.fovDegrees>90)throw Error('个人模型视角内容不正确');
  const app=new Application(canvas,{graphicsDeviceOptions:{antialias:false,alpha:true,preserveDrawingBuffer:true}});
  app.setCanvasFillMode(FILLMODE_FILL_WINDOW);app.setCanvasResolution(RESOLUTION_AUTO);app.scene.ambientLight=new Color(1,1,1);app.start();
  const camera=new Entity('Portrait camera');
  camera.addComponent('camera',{clearColor:new Color(.04,.06,.11,0),fov:view.fovDegrees,nearClip:.01,farClip:10000});
  app.root.addChild(camera);
  const asset=new Asset('Personal 3DGS','gsplat',{url:'https://self.local/portrait.gaussian.ply'});
  app.assets.add(asset);asset.on('error',error=>report('ERROR','立体面容暂时无法打开：'+String(error)));
  asset.on('load',()=>{
    try{
      const model=new Entity('Personal 3DGS');model.addComponent('gsplat',{asset});app.root.addChild(model);
      const resource=asset.resource,data=resource.gsplatData,originalColors=makeOriginalColors(data);
      const target=view.target,up=normal(view.up),original=view.camera.map((x,i)=>x-target[i]);
      const radius=Math.hypot(...original);if(!Number.isFinite(radius)||radius<.01)throw Error('个人模型相机参数不完整');
      const openingZoom=preview?.9:view.targetFaceFraction===.5?1:1.36;
      let yaw=0,pitch=0,zoom=openingZoom,targetYaw=0,targetPitch=0,targetZoom=openingZoom;
      let mode='move',touching=false,lastX=0,lastY=0,polygon=[],selectedPolygon=[],selectionYaw=0,selectionPitch=0,
        selectionWidth=0,selectionHeight=0,mask=null,selected=0,appendNext=false;
      let appliedRecipe=null,historyLayers=[],selections=[];
      const decodeMask=value=>{
        const decoded=atob(value||'');
        if(decoded.length!==data.numSplats)throw Error('圈选和个人模型不匹配');
        return Uint8Array.from(decoded,c=>c.charCodeAt(0));
      };
      const drawHistory=layers=>{applyDigitalLayers(resource,originalColors,layers);model.gsplat.workBufferUpdate=WORKBUFFER_UPDATE_ONCE;app.renderNextFrame=true;};
      const resizeOutline=()=>{const r=canvas.getBoundingClientRect();outline.width=Math.round(r.width*devicePixelRatio);outline.height=Math.round(r.height*devicePixelRatio);};
      const xs=data.getProp('x'),ys=data.getProp('y'),zs=data.getProp('z');
      const sampleMask=weights=>{
        let count=0;for(const weight of weights)if(weight>32)count++;
        const stride=Math.max(1,Math.ceil(count/120)),points=[];let seen=0;
        for(let i=0;i<weights.length;i++)if(weights[i]>32&&seen++%stride===0)points.push([xs[i],ys[i],zs[i]]);
        return points;
      };
      const hull=points=>{
        const sorted=points.slice().sort((a,b)=>a.x-b.x||a.y-b.y),cross=(a,b,c)=>(b.x-a.x)*(c.y-a.y)-(b.y-a.y)*(c.x-a.x);
        const lower=[],upper=[];
        for(const point of sorted){while(lower.length>1&&cross(lower[lower.length-2],lower[lower.length-1],point)<=0)lower.pop();lower.push(point);}
        for(let i=sorted.length-1;i>=0;i--){const point=sorted[i];while(upper.length>1&&cross(upper[upper.length-2],upper[upper.length-1],point)<=0)upper.pop();upper.push(point);}
        return lower.slice(0,-1).concat(upper.slice(0,-1));
      };
      const projectedContour=(entry,width,height)=>{
        if(Math.cos(yaw-entry.yaw)<.28||Math.abs(pitch-entry.pitch)>1.05)return [];
        const points=[];
        for(const pos of entry.samples){const p=camera.camera.worldToScreen(new Vec3(...pos));
          if(Number.isFinite(p.x)&&Number.isFinite(p.y)&&p.x>=0&&p.y>=0&&p.x<width&&p.y<height)points.push({x:p.x,y:p.y});}
        if(points.length<9)return [];
        const sortedX=points.map(p=>p.x).sort((a,b)=>a-b),sortedY=points.map(p=>p.y).sort((a,b)=>a-b);
        const low=Math.floor(points.length*.04),high=Math.ceil(points.length*.96)-1;
        return hull(points.filter(p=>p.x>=sortedX[low]&&p.x<=sortedX[high]&&p.y>=sortedY[low]&&p.y<=sortedY[high]));
      };
      let sparks=[],sparkFrame=0;
      const trace=(ctx,points,color,closed=false)=>{
        if(points.length<2)return;
        ctx.beginPath();ctx.moveTo(points[0].x,points[0].y);
        for(let i=1;i<points.length;i++)ctx.lineTo(points[i].x,points[i].y);
        if(closed)ctx.closePath();
        ctx.strokeStyle=color;ctx.lineWidth=1.6;ctx.shadowColor=color;ctx.shadowBlur=7;ctx.stroke();ctx.shadowBlur=0;
      };
      const drawOutline=()=>{
        const ctx=outline.getContext('2d');ctx.clearRect(0,0,outline.width,outline.height);
        const r=canvas.getBoundingClientRect();ctx.save();ctx.scale(devicePixelRatio,devicePixelRatio);
        const colors=['rgba(204,226,255,.88)','rgba(221,197,255,.88)','rgba(177,240,225,.86)','rgba(255,220,190,.86)'];
        selections.forEach((entry,index)=>{
          const sameView=Math.abs(yaw-entry.yaw)<.055&&Math.abs(pitch-entry.pitch)<.055&&
            Math.abs(r.width-entry.width)<1&&Math.abs(r.height-entry.height)<1;
          const points=sameView?entry.polygon:projectedContour(entry,r.width,r.height);
          trace(ctx,points,colors[index],true);
          if(!sameView&&points.length>2){ctx.fillStyle=colors[index];for(let i=0;i<points.length;i+=Math.max(1,Math.floor(points.length/12))){
            ctx.beginPath();ctx.arc(points[i].x,points[i].y,1.3,0,Math.PI*2);ctx.fill();}}
        });
        trace(ctx,polygon,'rgba(234,218,255,.96)');
        if(polygon.length){const tip=polygon[polygon.length-1];ctx.fillStyle='#F5EDFF';ctx.shadowColor='#CDAAFF';ctx.shadowBlur=12;
          ctx.beginPath();ctx.arc(tip.x,tip.y,2.5,0,Math.PI*2);ctx.fill();ctx.shadowBlur=0;}
        const now=performance.now();sparks=sparks.filter(s=>now-s.time<560);
        for(const s of sparks){const life=(now-s.time)/560,alpha=(1-life)*.8;
          ctx.fillStyle=`rgba(225,213,255,${alpha})`;
          ctx.beginPath();ctx.arc(s.x+s.vx*life,s.y+s.vy*life,s.radius*(1-life*.6),0,Math.PI*2);ctx.fill();}
        ctx.restore();
      };
      const animateSparks=()=>{sparkFrame=0;drawOutline();if(sparks.length)sparkFrame=requestAnimationFrame(animateSparks);};
      const addSparks=(point,burst=false)=>{const now=performance.now(),count=burst?9:2;
        for(let i=0;i<count;i++){const angle=(i*2.399+now*.005)%(Math.PI*2),speed=burst?8+i%3*4:4+i*2;
          sparks.push({x:point.x,y:point.y,vx:Math.cos(angle)*speed,vy:Math.sin(angle)*speed,
            radius:burst?1.7+(i%3)*.35:1.2,time:now});}
        if(sparks.length>70)sparks.splice(0,sparks.length-70);
        if(!sparkFrame)sparkFrame=requestAnimationFrame(animateSparks);
      };
      let firstCamera=true,lastOverlay=0;
      const update=()=>{if(preview&&!touching)targetYaw=Math.sin(performance.now()*.00027)*.23;
        if(!firstCamera&&Math.abs(targetYaw-yaw)<.0002&&Math.abs(targetPitch-pitch)<.0002&&Math.abs(targetZoom-zoom)<.0002)return;
        firstCamera=false;
        yaw+=(targetYaw-yaw)*.2;pitch+=(targetPitch-pitch)*.2;zoom+=(targetZoom-zoom)*.2;
        const afterYaw=rotate(original,up,yaw),forward=normal(afterYaw.map(x=>-x));
        const right=normal([forward[1]*up[2]-forward[2]*up[1],forward[2]*up[0]-forward[0]*up[2],forward[0]*up[1]-forward[1]*up[0]]);
        const offset=rotate(afterYaw,right,pitch);
        camera.setPosition(...offset.map((x,i)=>target[i]+x*zoom));camera.lookAt(...target,...up);app.renderNextFrame=true;
        if(selections.length&&performance.now()-lastOverlay>32){lastOverlay=performance.now();drawOutline();}};
      app.on('update',update);update();resizeOutline();drawOutline();
      app.systems.gsplat.on('frame:request',()=>{app.renderNextFrame=true;});
      app.autoRender=false;app.renderNextFrame=true;
      let lastInteraction=-2000;
      const interaction=()=>{if(performance.now()-lastInteraction>1800){lastInteraction=performance.now();console.log('SELF_GS_VIEWER_INTERACTION');}};
      const pointer=event=>{const r=canvas.getBoundingClientRect();return {x:event.clientX-r.left,y:event.clientY-r.top};};
      canvas.addEventListener('pointerdown',event=>{interaction();touching=true;lastX=event.clientX;lastY=event.clientY;canvas.setPointerCapture(event.pointerId);
        if(mode==='lasso'){polygon=[pointer(event)];drawOutline();}});
      canvas.addEventListener('pointermove',event=>{if(!touching)return;interaction();
        if(mode==='lasso'){const point=pointer(event),previous=polygon[polygon.length-1];
          if(polygon.length<512&&shouldRecordLassoPoint(previous,point)){
            polygon.push(point);if(polygon.length%3===0)addSparks(point);drawOutline();}}
        else{targetYaw+=(event.clientX-lastX)*.008;targetPitch=Math.max(-.9,Math.min(.9,targetPitch+(event.clientY-lastY)*.008));}
        lastX=event.clientX;lastY=event.clientY;});
      canvas.addEventListener('pointerup',()=>{if(!touching)return;touching=false;if(mode!=='lasso')return;
        try{const first=polygon[0],last=polygon[polygon.length-1];
          if(first&&last&&Math.hypot(first.x-last.x,first.y-last.y)>5)polygon.push(first);
          polygon=normalizeLasso(polygon);
          const r=canvas.getBoundingClientRect();
          const result=selectVisibleSplats({data,polygon,target,cameraPosition:camera.getPosition().toArray(),
            project:(x,y,z)=>camera.camera.worldToScreen(new Vec3(x,y,z)),width:r.width,height:r.height});
          const slot=selectionSlot(selections.length,appendNext);
          const regionId=selections[slot]?.regionId||`gs-selected-${slot+1}`;
          mask=result.mask;selected=result.selected;selectedPolygon=polygon.slice();selectionYaw=yaw;selectionPitch=pitch;
          selectionWidth=r.width;selectionHeight=r.height;
          const entry={regionId,mask:mask.slice(),polygon:polygon.slice(),yaw,pitch,width:r.width,height:r.height,
            samples:sampleMask(mask)};
          if(slot===selections.length)selections.push(entry);else selections[slot]=entry;
          appendNext=false;
          send('GS_SELECTION',{regionId,count:selected,total:data.numSplats,x:polygon.reduce((s,p)=>s+p.x,0)/polygon.length/r.width,
            y:polygon.reduce((s,p)=>s+p.y,0)/polygon.length/r.height});
          sendBytes('gs-mask',mask);if(last)addSparks(last,true);
          report('SELECTED',`已圈出 ${selections.length} 处；再画可替换当前范围`);
        }catch(error){send('GS_FAILED',{message:String(error)});report('SELECTION_FAILED',String(error));}
        polygon=[];drawOutline();});
      canvas.addEventListener('pointercancel',()=>{touching=false;polygon=[];drawOutline();});
      canvas.addEventListener('wheel',event=>{targetZoom=Math.max(.35,Math.min(4,targetZoom*Math.exp(event.deltaY*.001)));event.preventDefault();},{passive:false});
      command=payload=>{
        if(payload.action==='TOOL'){mode=payload.tool==='lasso'?'lasso':'move';appendNext=false;return;}
        if(payload.action==='ARM_APPEND'){mode='lasso';appendNext=true;return;}
        if(payload.action==='CLEAR_SELECTION'){selections=[];polygon=[];selectedPolygon=[];mask=null;selected=0;appendNext=false;drawOutline();return;}
        if(payload.action==='SET_HISTORY'){
          const incoming=payload.layers;
          if(!Array.isArray(incoming)||incoming.length>16)throw Error('编辑记录过多');
          const next=incoming.map(layer=>({mask:decodeMask(layer.maskBase64),preset:layer.preset,strength:layer.strength}));
          drawHistory(next);historyLayers=next;appliedRecipe=null;
          send('GS_APPLIED',{action:'SET_HISTORY',count:next.length});return;
        }
        if(payload.action==='RESTORE'){
          const decoded=atob(payload.maskBase64||'');
          if(decoded.length!==data.numSplats)throw Error('已存编辑与模型不匹配');
          mask=Uint8Array.from(decoded,c=>c.charCodeAt(0));selected=mask.reduce((n,v)=>n+(v>0?1:0),0);
          if(selected<80)throw Error('已存圈选范围不完整');
          if(!Object.hasOwn(DIGITAL_PRESETS,payload.preset)||![.18,.32,.5].includes(payload.strength))throw Error('已存颜色参数不正确');
          applyDigitalTint(resource,originalColors,mask,DIGITAL_PRESETS[payload.preset],payload.strength);
          model.gsplat.workBufferUpdate=WORKBUFFER_UPDATE_ONCE;app.renderNextFrame=true;
          appliedRecipe={mask:mask.slice(),preset:payload.preset,strength:payload.strength};
          send('GS_APPLIED',{action:'RESTORE',count:selected});return;}
        if(payload.action==='RESET'){applyDigitalTint(resource,originalColors,new Uint8Array(data.numSplats),[.5,.5,.5],0);
          model.gsplat.workBufferUpdate=WORKBUFFER_UPDATE_ONCE;app.renderNextFrame=true;appliedRecipe=null;send('GS_APPLIED',{action:'RESET'});return;}
        if(payload.action==='COMPARE_ORIGINAL'||payload.action==='COMPARE_EDIT'){
          if(!appliedRecipe)throw Error('还没有可对比的变化');
          if(payload.action==='COMPARE_ORIGINAL')applyDigitalTint(resource,originalColors,new Uint8Array(data.numSplats),[.5,.5,.5],0);
          else applyDigitalTint(resource,originalColors,appliedRecipe.mask,DIGITAL_PRESETS[appliedRecipe.preset],appliedRecipe.strength);
          model.gsplat.workBufferUpdate=WORKBUFFER_UPDATE_ONCE;app.renderNextFrame=true;
          send('GS_APPLIED',{action:payload.action});return;}
        if(payload.action==='APPLY'){
          if(!mask||selected<80)throw Error('请先圈出想试的地方');
          if(!Object.hasOwn(DIGITAL_PRESETS,payload.preset)||![.18,.32,.5].includes(payload.strength))throw Error('这次的颜色建议还不能使用');
          applyDigitalTint(resource,originalColors,mask,DIGITAL_PRESETS[payload.preset],payload.strength);
          model.gsplat.workBufferUpdate=WORKBUFFER_UPDATE_ONCE;app.renderNextFrame=true;
          appliedRecipe={mask:mask.slice(),preset:payload.preset,strength:payload.strength};
          send('GS_APPLIED',{action:'APPLY',count:selected});return;}
        if(payload.action==='CAPTURE'){
          const r=canvas.getBoundingClientRect(),scale=Math.min(1,1024/Math.max(r.width,r.height));
          const image=document.createElement('canvas');image.width=Math.max(8,Math.round(r.width*scale));image.height=Math.max(8,Math.round(r.height*scale));
          const ctx=image.getContext('2d');ctx.drawImage(canvas,0,0,image.width,image.height);
          send('GS_CAPTURE',{width:image.width,height:image.height,images:2});sendBytes('gs-clean',pngBytes(image.toDataURL('image/png')));
          // Reproject the selected 3D points into this camera. The annotation
          // stays aligned after orbiting, unlike reusing the old screen lasso.
          if(selections.length){
            const xs=data.getProp('x'),ys=data.getProp('y'),zs=data.getProp('z'),eye=camera.getPosition().toArray();
            const forward=normal(target.map((v,i)=>v-eye[i])),distance=Math.hypot(...target.map((v,i)=>v-eye[i]));
            const front=new Map();
            for(let i=0;i<data.numSplats;i++){
              const p=camera.camera.worldToScreen(new Vec3(xs[i],ys[i],zs[i]));
              if(p.x<0||p.y<0||p.x>=r.width||p.y>=r.height)continue;
              const depth=(xs[i]-eye[0])*forward[0]+(ys[i]-eye[1])*forward[1]+(zs[i]-eye[2])*forward[2];
              const key=`${Math.floor(p.x/14)},${Math.floor(p.y/14)}`;
              front.set(key,Math.min(front.get(key)??Infinity,depth));
            }
            for(let region=0;region<selections.length;region++){
              const selectedMask=selections[region].mask;
              let hit=0,markX=0,markY=0,marks=0;
              const stride=Math.max(1,Math.floor(selectedMask.reduce((n,v)=>n+(v>0),0)/350));
              ctx.save();ctx.fillStyle=['rgba(185,229,255,.75)','rgba(215,189,255,.75)','rgba(167,241,221,.75)','rgba(255,218,181,.75)'][region];
              for(let i=0;i<selectedMask.length;i++){
                if(!selectedMask[i]||++hit%stride!==0)continue;
                const p=camera.camera.worldToScreen(new Vec3(xs[i],ys[i],zs[i]));
                const key=`${Math.floor(p.x/14)},${Math.floor(p.y/14)}`;
                const depth=(xs[i]-eye[0])*forward[0]+(ys[i]-eye[1])*forward[1]+(zs[i]-eye[2])*forward[2];
                if(depth>(front.get(key)??Infinity)+distance*.075)continue;
                const px=p.x*image.width/r.width,py=p.y*image.height/r.height;
                ctx.beginPath();ctx.arc(px,py,1.7,0,Math.PI*2);ctx.fill();
                markX+=px;markY+=py;marks++;
              }
              if(marks){ctx.font='bold 20px sans-serif';ctx.fillText(String(region+1),markX/marks,markY/marks);}
              ctx.restore();
            }
          }
          if(selectedPolygon.length>=3&&Math.abs(yaw-selectionYaw)<.04&&Math.abs(pitch-selectionPitch)<.04&&
            Math.abs(r.width-selectionWidth)<1&&Math.abs(r.height-selectionHeight)<1){ctx.save();ctx.scale(image.width/r.width,image.height/r.height);ctx.beginPath();ctx.moveTo(selectedPolygon[0].x,selectedPolygon[0].y);
            for(let i=1;i<selectedPolygon.length;i++)ctx.lineTo(selectedPolygon[i].x,selectedPolygon[i].y);ctx.closePath();ctx.strokeStyle='#D7EAFF';ctx.lineWidth=3;ctx.stroke();ctx.restore();}
          sendBytes('gs-annotated',pngBytes(image.toDataURL('image/png')));return;}
      };
      modelReady=true;if(port)port.postMessage(JSON.stringify({schemaVersion:1,type:'READY',payload:{webgl2:true}}));
      report('READY',`已载入 ${data.numSplats} 个立体细节点，可拖动观察`);
      setTimeout(()=>status.classList.add('quiet'),2200);
      console.log(`SELF_GS_VIEWER_VIEW ${view.sourceFrame} ${view.faceTrackCount} ${view.fovDegrees}`);
      window.addEventListener('resize',()=>{app.resizeCanvas();resizeOutline();drawOutline();app.renderNextFrame=true;});
    }catch(error){report('ERROR','立体面容绘制失败：'+String(error));}
  });app.assets.load(asset);
}
start().catch(error=>report('ERROR','立体面容绘制不可用：'+String(error)));

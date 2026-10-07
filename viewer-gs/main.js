import { snapshotCamera,applyTransferCamera,validTransferCamera,savedFrontCamera } from './transfer-camera.js';
import { Application, Asset, Entity, FILLMODE_FILL_WINDOW, RESOLUTION_AUTO, WORKBUFFER_UPDATE_ONCE, Color, Vec3 } from 'playcanvas';
import { selectVisibleSplats, normalizeLasso, selectionSlot, shouldRecordLassoPoint, makeOriginalColors, applyDigitalTint, applyDigitalLayers, applyCareScenario, DIGITAL_PRESETS, mortonOrderOf, editableSetFromOrder } from './gs-edit.js';

// The engine Morton-reorders an uncompressed PLY while loading, so the first
// view.editableSplats rows of the LOADED data are not the portrait points.
// Compute the exact order the engine will apply from the FILE bytes (the port
// is element-identical to playcanvas 2.22.4 calcMortonOrder) and keep the
// editable identity in loaded order. Falls back to the legacy prefix only if
// the pre-fetch fails; masks stay in the loaded domain either way, so
// previously saved edits remain valid.
async function editableSetForUrl(url, editableSplats, numSplatsHint) {
  try {
    const response = await fetch(url);
    if (!response.ok) throw Error(`status ${response.status}`);
    const buffer = await response.arrayBuffer();
    const bytes = new Uint8Array(buffer);
    let end = 0;
    while (end < bytes.length) {
      const nl = bytes.indexOf(10, end);
      const line = String.fromCharCode(...bytes.subarray(end, nl));
      end = nl + 1;
      if (line.trim() === 'end_header') break;
    }
    const header = String.fromCharCode(...bytes.subarray(0, end));
    const count = parseInt(header.match(/element vertex (\d+)/)[1]);
    const fields = [...header.matchAll(/property float (\S+)/g)].map(m => m[1]);
    const ix = fields.indexOf('x'), iy = fields.indexOf('y'), iz = fields.indexOf('z');
    const stride = fields.length * 4;
    const view = new DataView(buffer);
    const px = new Float32Array(count), py = new Float32Array(count), pz = new Float32Array(count);
    for (let i = 0; i < count; i++) {
      const base = end + i * stride;
      px[i] = view.getFloat32(base + ix * 4, true);
      py[i] = view.getFloat32(base + iy * 4, true);
      pz[i] = view.getFloat32(base + iz * 4, true);
    }
    const order = mortonOrderOf({numSplats: count, getProp: n => ({x: px, y: py, z: pz})[n]});
    return {set: editableSetFromOrder(order, Math.min(editableSplats, count)), order};
  } catch (error) {
    report('WARN', 'editable identity pre-fetch failed, legacy prefix in use: ' + String(error));
    return {set: Uint32Array.from({length: Math.min(editableSplats, numSplatsHint || editableSplats)}, (_, i) => i), order: null};
  }
}
import { upperLeftLuma, createToneTracker } from './tone.js';
import { add, twoFingerPanDelta, composeOrbitCamera } from './portrait-camera-math.js';

const canvas=document.getElementById('portrait'), outline=document.getElementById('lasso'), status=document.getElementById('status');
const preview=document.body.dataset.preview==='true';
const report=(kind,message)=>{status.textContent=message;console.log(`SELF_GS_VIEWER_${kind} ${message}`);};
const TEXT={
  loading:{zh:'循着光，慢慢看见你…',en:'Following the light, slowly seeing you…',ja:'光をたどって、ゆっくりあなたに会いに…',ko:'빛을 따라, 천천히 당신을 만나요…'},
  aria:{zh:'个人立体面容',en:'Your 3D portrait',ja:'あなたの立体フェース',ko:'나의 입체 얼굴'},
  ariaPreview:{zh:'星辰立体预览',en:'Starlight 3D preview',ja:'星辰の立体プレビュー',ko:'별빛 입체 미리보기'},
  webgl:{zh:'这台设备没有提供 WebGL2 绘制能力',en:'This device does not offer WebGL2 rendering',ja:'この端末は WebGL2 描画に対応していません',ko:'이 기기는 WebGL2 렌더링을 지원하지 않습니다'},
  viewMissing:{zh:'个人模型视角尚未就绪',en:'The portrait view is not ready yet',ja:'モデル視点の準備がまだです',ko:'모델 시점이 아직 준비되지 않았습니다'},
  viewInvalid:{zh:'个人模型视角内容不正确',en:'The portrait view content is invalid',ja:'モデル視点の内容が正しくありません',ko:'모델 시점 내용이 올바르지 않습니다'},
  openFail:{zh:'立体面容暂时无法打开：',en:'The portrait cannot open right now: ',ja:'立体フェースを開けません：',ko:'입체 얼굴을 열 수 없습니다: '},
  cameraParams:{zh:'个人模型相机参数不完整',en:'The portrait camera parameters are incomplete',ja:'モデルのカメラパラメータが不完全です',ko:'모델 카메라 파라미터가 불완전합니다'},
  selectMismatch:{zh:'圈选和个人模型不匹配',en:'The selection does not match the portrait',ja:'選択範囲がモデルと一致しません',ko:'선택 영역이 모델과 일치하지 않습니다'},
  selected:{zh:'已圈出 {count} 处；再画可替换当前范围',en:'{count} area(s) circled; draw again to replace',ja:'{count}か所を選択しました。もう一度描くと範囲を変更できます',ko:'{count}군데를 선택했어요. 다시 그리면 범위를 바꿀 수 있습니다'},
  viewNotDrawn:{zh:'当前视角尚未绘制完成',en:'The current view has not finished rendering',ja:'現在の視点の描画がまだ完了していません',ko:'현재 시점이 아직 렌더링되지 않았습니다'},
  weekInvalid:{zh:'观察时段不正确',en:'Invalid observation week',ja:'観察期間が正しくありません',ko:'관찰 기간이 올바르지 않습니다'},
  needSelection:{zh:'请先圈选一处',en:'Please circle an area first',ja:'先に一か所を囲んでください',ko:'먼저 한 곳을 선택해 주세요'},
  tooManyLayers:{zh:'编辑记录过多',en:'Too many edit records',ja:'編集記録が多すぎます',ko:'편집 기록이 너무 많습니다'},
  layerMismatch:{zh:'已存编辑与模型不匹配',en:'Saved edits do not match the model',ja:'保存済みの編集がモデルと一致しません',ko:'저장된 편집이 모델과 일치하지 않습니다'},
  layerIncomplete:{zh:'已存圈选范围不完整',en:'The saved selection is incomplete',ja:'保存済みの選択範囲が不完全です',ko:'저장된 선택 범위가 불완전합니다'},
  colorInvalid:{zh:'已存颜色参数不正确',en:'Saved colour parameters are invalid',ja:'保存済みの色パラメータが正しくありません',ko:'저장된 색상 파라미터가 올바르지 않습니다'},
  noCompare:{zh:'还没有可对比的变化',en:'Nothing to compare yet',ja:'比較できる変化がまだありません',ko:'비교할 변화가 아직 없습니다'},
  needCircle:{zh:'请先圈出想试的地方',en:'Circle the spot you want to try first',ja:'試したい場所を先に囲んでください',ko:'먼저 시도할 곳을 선택해 주세요'},
  colorUnavailable:{zh:'这次的颜色建议还不能使用',en:'This colour suggestion cannot be used yet',ja:'この色の提案はまだ使えません',ko:'이 색상 제안은 아직 사용할 수 없습니다'},
  ready:{zh:'已载入 {count} 个立体细节点，可拖动观察',en:'{count} detail points loaded; drag to look around',ja:'{count}個の立体ポイントを読み込みました。ドラッグで観察できます',ko:'입체 포인트 {count}개를 불러왔어요. 드래그해서 살펴보세요'},
  drawFail:{zh:'立体面容绘制失败：',en:'Portrait rendering failed: ',ja:'立体フェースの描画に失敗しました：',ko:'입체 얼굴 렌더링 실패: '},
  drawUnavailable:{zh:'立体面容绘制不可用：',en:'Portrait rendering unavailable: ',ja:'立体フェースの描画を利用できません：',ko:'입체 얼굴 렌더링 불가: '}
};
let language='zh';
const LANG_TAG={zh:'zh-CN',en:'en',ja:'ja',ko:'ko'};
const t=(key,count)=>{const row=TEXT[key]||{};const s=row[language]||row.en||row.zh||key;return count===undefined?s:s.replace('{count}',count);};
window.selfViewerLanguage=lang=>{if(!LANG_TAG[lang])return;language=lang;
  document.documentElement.lang=LANG_TAG[lang];
  canvas.setAttribute('aria-label',preview?t('ariaPreview'):t('aria'));
  if(!status.classList.contains('quiet'))status.textContent=t('loading');};
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
      if(frame.type==='INIT'){identity={sessionId:frame.sessionId,assetId:frame.assetId,assetVersion:frame.assetVersion,revision:frame.revision};window.__selfTransferPresent?.();return;}
      if(!identity||frame.sessionId!==identity.sessionId||frame.assetId!==identity.assetId)return;
      if(frame.type==='GS_COMMAND')command(frame.payload);
    }catch(error){send('GS_FAILED',{message:String(error)});}};
  if(modelReady)port.postMessage(JSON.stringify({schemaVersion:1,type:'READY',payload:{webgl2:true}}));
});
const pngBytes=dataUrl=>Uint8Array.from(atob(dataUrl.split(',')[1]),c=>c.charCodeAt(0));

async function start(){
  if(!canvas.getContext('webgl2',{antialias:false,alpha:true,preserveDrawingBuffer:true}))throw Error(t('webgl'));
  const response=await fetch('https://self.local/portrait.view.json');
  if(!response.ok)throw Error(t('viewMissing'));
  const view=await response.json();
  const rect=canvas.getBoundingClientRect(),front=savedFrontCamera(view,rect.width,rect.height);
  if(front)applyTransferCamera(view,front);
  if(!preview&&applyTransferCamera(view,view.transferArrivalView))console.info('SELF_TRANSFER_ARRIVAL_CAMERA_APPLIED');
  if(view.schemaVersion!==1||!finite3(view.target)||!finite3(view.camera)||!finite3(view.up)||
    !Number.isFinite(view.fovDegrees)||view.fovDegrees<10||view.fovDegrees>90)throw Error(t('viewInvalid'));
  const app=new Application(canvas,{graphicsDeviceOptions:{antialias:false,alpha:true,preserveDrawingBuffer:true}});
  app.setCanvasFillMode(FILLMODE_FILL_WINDOW);app.setCanvasResolution(RESOLUTION_AUTO);app.scene.ambientLight=new Color(1,1,1);app.start();
  const camera=new Entity('Portrait camera');
  camera.addComponent('camera',{clearColor:new Color(.04,.06,.11,0),fov:view.fovDegrees,nearClip:.01,farClip:10000});
  if(Number.isFinite(view.transferNearClip))camera.camera.nearClip=view.transferNearClip;
  if(Number.isFinite(view.transferFarClip))camera.camera.farClip=view.transferFarClip;
  app.root.addChild(camera);
  const asset=new Asset('Personal 3DGS','gsplat',{url:'https://self.local/portrait.gaussian.ply'});
  app.assets.add(asset);asset.on('error',error=>report('ERROR',t('openFail')+String(error)));
  asset.on('load',()=>{
    try{
      const model=new Entity('Personal 3DGS');model.addComponent('gsplat',{asset});app.root.addChild(model);
      const resource=asset.resource,data=resource.gsplatData,originalColors=makeOriginalColors(data);
      // Real editable identity (see editableSetForUrl). Resolved from the
      // file bytes before the engine's reorder; the selection then scans the
      // true portrait points instead of an arbitrary Morton prefix.
      let editableSet=Uint32Array.from({length:Math.min(Number.isInteger(view.editableSplats)?view.editableSplats:data.numSplats,data.numSplats)},(_,i)=>i);
      editableSetForUrl('https://self.local/portrait.gaussian.ply',
        Number.isInteger(view.editableSplats)?view.editableSplats:data.numSplats,data.numSplats)
        .then(result=>{editableSet=result.set;})
        .catch(()=>{});
      let target=view.target.slice();
      let pivotGoal=target.slice();
      const up=normal(view.up),original=view.camera.map((x,i)=>x-target[i]);
      const radius=Math.hypot(...original);if(!Number.isFinite(radius)||radius<.01)throw Error(t('cameraParams'));
      const recordedFov=Number.isFinite(view.captureHorizontalFovDegrees)&&view.captureHorizontalFovDegrees>=20&&view.captureHorizontalFovDegrees<=120;
      const hasYawBounds=Array.isArray(view.safeYawDegrees)&&view.safeYawDegrees.length===2&&view.safeYawDegrees.every(Number.isFinite)&&view.safeYawDegrees[0]<=0&&view.safeYawDegrees[1]>=0;
      const hasPitchBounds=Array.isArray(view.safePitchDegrees)&&view.safePitchDegrees.length===2&&view.safePitchDegrees.every(Number.isFinite)&&view.safePitchDegrees[0]<=0&&view.safePitchDegrees[1]>=0;
      const yawBounds=hasYawBounds?view.safeYawDegrees.map(value=>value*Math.PI/180):[-Math.PI,Math.PI];
      // Pitch is a viewing control, not a claim that unrecorded surfaces were reconstructed.
      // Keep the source coverage as metadata, but allow looking above and below the face.
      const pitchBounds=hasPitchBounds?
        [Math.min(-85,view.safePitchDegrees[0])*Math.PI/180,
          Math.max(85,view.safePitchDegrees[1])*Math.PI/180]:[-85*Math.PI/180,85*Math.PI/180];
      let openingZoom=preview?.9:view.targetFaceFraction===.5?1:1.36;
      let yaw=0,pitch=0,zoom=openingZoom,targetYaw=0,targetPitch=0,targetZoom=openingZoom;
      // Keep the face sharp when still; reduce fill rate only during camera motion.
      // On high-resolution tablets the transparent splats overdraw millions of pixels.
      const movingPixelRatio=()=>{
        const r=canvas.getBoundingClientRect();
        return Math.min(1,Math.max(.55,Math.sqrt(2200000/Math.max(1,r.width*r.height))));
      };
      let reducedResolution=false;
      const setMotionResolution=moving=>{
        if(reducedResolution===moving)return;
        reducedResolution=moving;
        app.graphicsDevice.maxPixelRatio=moving?movingPixelRatio():1;
        app.resizeCanvas();app.renderNextFrame=true;
      };
      let motionFrames=0,motionStarted=0;
      app.on('frameend',()=>{
        if(!reducedResolution){motionFrames=0;motionStarted=0;return;}
        const now=performance.now();if(!motionStarted)motionStarted=now;
        motionFrames++;
        if(now-motionStarted>=3000){
          console.info(`SELF_GS_VIEWER_MOTION_FPS ${Math.round(motionFrames*1000/(now-motionStarted))} ${canvas.width}x${canvas.height}`);
          motionFrames=0;motionStarted=now;
        }
      });
      const zoomMax=recordedFov?openingZoom*1.2:Math.max(4,Number.isFinite(view.sceneRadius)?view.sceneRadius/Math.max(.01,radius)*2.2:4);
      const clampZoom=value=>Math.max(.04,Math.min(zoomMax,value));
      const adjustRecordedFraming=()=>{if(!recordedFov)return;
        const rect=canvas.getBoundingClientRect(),aspect=rect.width/Math.max(1,rect.height);
        const horizontal=Math.min(58,view.captureHorizontalFovDegrees*1.12);
        const vertical=2*Math.atan(Math.tan(horizontal*Math.PI/360)/aspect)*180/Math.PI;
        const nextFov=Math.min(view.fovDegrees,vertical);
        const nextOpening=preview?.9:nextFov<view.fovDegrees-1?1.3:1;
        const ratio=nextOpening/openingZoom;openingZoom=nextOpening;
        zoom=clampZoom(zoom*ratio);targetZoom=clampZoom(targetZoom*ratio);
        camera.camera.fov=nextFov;app.renderNextFrame=true;};
      adjustRecordedFraming();
      let mode='move',touching=false,lastX=0,lastY=0,polygon=[],selectedPolygon=[],selectionYaw=0,selectionPitch=0,
        selectionWidth=0,selectionHeight=0,selectionTarget=target.slice(),selectionZoom=zoom,mask=null,selected=0,appendNext=false;
      let appliedRecipe=null,historyLayers=[],selections=[],carePreviewActive=false;
      const decodeMask=value=>{
        const decoded=atob(value||'');
        if(decoded.length!==data.numSplats)throw Error(t('selectMismatch'));
        return Uint8Array.from(decoded,c=>c.charCodeAt(0));
      };
      let editRevision=0,cameraRevision=0,renderFrame=0,lastRenderedView=null;
      const viewSnapshot=()=>{const pos=camera.getPosition(),q=camera.getRotation(),rect=canvas.getBoundingClientRect();
        return {snapshotId:`gs-view-${renderFrame}`,assetId:identity?.assetId||'',capturedAt:Date.now(),frame:renderFrame,
          cameraRevision,editRevision,position:[pos.x,pos.y,pos.z],rotation:[q.x,q.y,q.z,q.w],target:target.slice(),
          yaw,pitch,distance:Math.hypot(pos.x-target[0],pos.y-target[1],pos.z-target[2]),
          fovDegrees:camera.camera.fov,nearClip:camera.camera.nearClip,farClip:camera.camera.farClip,
          viewportWidth:rect.width,viewportHeight:rect.height,mirrored:false,crop:'fill-window'};};
      let transferPresented=false;
      const presentTransferView=()=>{if(transferPresented||!lastRenderedView||!port||!identity)return;transferPresented=true;send('GS_PRESENTABLE');};
      window.__selfTransferPresent=presentTransferView;
      app.on('postrender',()=>{renderFrame++;lastRenderedView=viewSnapshot();presentTransferView();});
      window.selfTransferCurrentView=()=>snapshotCamera(lastRenderedView);
      const drawHistory=layers=>{applyDigitalLayers(resource,originalColors,layers);editRevision++;
        model.gsplat.workBufferUpdate=WORKBUFFER_UPDATE_ONCE;app.renderNextFrame=true;};
      const toneTracker=createToneTracker(),toneCanvas=document.createElement('canvas');
      toneCanvas.width=24;toneCanvas.height=16;
      const sampleTone=()=>{if(!port||!identity||preview)return;
        try{const context=toneCanvas.getContext('2d',{willReadFrequently:true});
          context.drawImage(canvas,0,0,toneCanvas.width,toneCanvas.height);
          const pixels=context.getImageData(0,0,toneCanvas.width,toneCanvas.height).data;
          const light=toneTracker(upperLeftLuma(pixels,toneCanvas.width,toneCanvas.height));
          if(light!==null)send('GS_TONE',{light});
        }catch(error){console.warn('SELF_GS_TONE_UNAVAILABLE '+String(error));}};
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
          const sameView=entry.target.every((value,i)=>Math.abs(value-target[i])<radius*1e-6)&&
            Math.abs(zoom-entry.zoom)<1e-6&&Math.abs(yaw-entry.yaw)<.055&&Math.abs(pitch-entry.pitch)<.055&&
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
      const dissolveSelections=()=>{for(const entry of selections){
        const r=canvas.getBoundingClientRect();
        const points=entry.target.every((value,i)=>Math.abs(value-target[i])<radius*1e-6)&&
          Math.abs(zoom-entry.zoom)<1e-6&&Math.abs(yaw-entry.yaw)<.055&&Math.abs(pitch-entry.pitch)<.055&&
          Math.abs(r.width-entry.width)<1&&Math.abs(r.height-entry.height)<1?
          entry.polygon:projectedContour(entry,r.width,r.height);
        for(let i=0;i<points.length;i+=Math.max(1,Math.floor(points.length/8)))addSparks(points[i]);
      }};
      let firstCamera=true,lastOverlay=0,aimPoint=target;
      const movePointers=new Map();let twoFinger=null;
      const update=(dt=1/60)=>{if(preview&&!touching)targetYaw=Math.max(yawBounds[0],Math.min(yawBounds[1],Math.sin(performance.now()*.00027)*.23));
        // Two-finger gestures are consumed ONCE per rendered frame from the
        // latest pointer table (never per pointermove event): the two arrival
        // orders of the fingers cannot produce transient zoom/pan jumps.
        if(twoFinger&&twoFinger.dirty){
          twoFinger.dirty=false;
          const pts=twoFinger.ids.map(id=>movePointers.get(id)).filter(Boolean);
          if(pts.length===2){
            const rectNow=canvas.getBoundingClientRect();
            const gapNow=Math.hypot(pts[0].x-pts[1].x,pts[0].y-pts[1].y);
            const nextZoom=clampZoom(twoFinger.zoom0*twoFinger.gap0/Math.max(1,gapNow));
            // Logical camera under the GOAL state (pivotGoal/yaw/pitch/next r):
            // pan rays must use the full composed camera, never the world up.
            const logical=composeOrbitCamera(pivotGoal,original,up,targetYaw,targetPitch,radius*nextZoom);
            if(logical){
              const delta=twoFingerPanDelta({
                mPrev:{x:twoFinger.mPrev.x-rectNow.left,y:twoFinger.mPrev.y-rectNow.top},
                mNow:{x:(pts[0].x+pts[1].x)/2-rectNow.left,y:(pts[0].y+pts[1].y)/2-rectNow.top},
                camBasis:logical.basis,fovY:camera.camera.fov,
                aspect:rectNow.width/Math.max(1,rectNow.height),
                width:rectNow.width,height:rectNow.height,pivot:pivotGoal});
              if(delta&&delta.every(Number.isFinite))pivotGoal=add(pivotGoal,delta);
            }
            targetZoom=nextZoom;
            twoFinger.mPrev={x:(pts[0].x+pts[1].x)/2,y:(pts[0].y+pts[1].y)/2};
          }
        }
        const pivotMoving=pivotGoal?Math.abs(pivotGoal[0]-target[0])+Math.abs(pivotGoal[1]-target[1])+Math.abs(pivotGoal[2]-target[2])>.001*Math.max(.01,radius):false;
        const settling=Math.abs(targetYaw-yaw)>.002||Math.abs(targetPitch-pitch)>.002||Math.abs(targetZoom-zoom)>.002||pivotMoving;
        setMotionResolution(touching||settling);
        if(!firstCamera&&!settling)return;
        firstCamera=false;
        // Preserve the 60 Hz response without letting a slow or resumed frame snap the camera.
        const elapsed=Number.isFinite(dt)?Math.max(0,Math.min(dt,.05)):1/60;
        const blend=1-Math.pow(.8,elapsed*60);
        yaw+=(targetYaw-yaw)*blend;pitch+=(targetPitch-pitch)*blend;zoom+=(targetZoom-zoom)*blend;
        if(pivotGoal)target=target.map((value,i)=>value+(pivotGoal[i]-value)*blend);
        const afterYaw=rotate(original,up,yaw),forward=normal(afterYaw.map(x=>-x));
        const right=normal([forward[1]*up[2]-forward[2]*up[1],forward[2]*up[0]-forward[0]*up[2],forward[0]*up[1]-forward[1]*up[0]]);
        const offset=rotate(afterYaw,right,pitch);
        camera.setPosition(...offset.map((x,i)=>target[i]+x*zoom));
        // Preserve the destination recorded-FOV framing while panning.
        aimPoint=recordedFov?target.map((value,i)=>value-up[i]*radius*zoom*.075):target;
        camera.lookAt(...aimPoint,...up);cameraRevision++;app.renderNextFrame=true;
        if(selections.length&&performance.now()-lastOverlay>32){lastOverlay=performance.now();drawOutline();}};
      app.on('update',update);update();resizeOutline();drawOutline();
      app.systems.gsplat.on('frame:request',()=>{app.renderNextFrame=true;});
      app.autoRender=false;app.renderNextFrame=true;
      let lastInteraction=-2000;
      const interaction=()=>{if(performance.now()-lastInteraction>1800){lastInteraction=performance.now();console.log('SELF_GS_VIEWER_INTERACTION');}};
      const pointer=event=>{const r=canvas.getBoundingClientRect();return {x:event.clientX-r.left,y:event.clientY-r.top};};
      const endTwoFinger=()=>{twoFinger=null;};
      const freezeOnRelease=()=>{ // last finger gone: stop exactly where the screen is
        targetYaw=yaw;targetPitch=pitch;targetZoom=zoom;
        if(pivotGoal)pivotGoal=target.slice();
      };
      canvas.addEventListener('pointerdown',event=>{interaction();touching=true;lastX=event.clientX;lastY=event.clientY;canvas.setPointerCapture(event.pointerId);
        if(mode==='move'){
          movePointers.set(event.pointerId,{x:event.clientX,y:event.clientY});
          // Two-finger start: rebase the gesture to the CURRENT live state and
          // freeze rotation targets; the third+ finger never disturbs the
          // tracked pair (fixed earliest two IDs).
          if(movePointers.size>=2&&!twoFinger){
            const ids=[...movePointers.keys()].slice(0,2);
            const pts=ids.map(id=>movePointers.get(id));
            twoFinger={ids,dirty:false,gap0:Math.max(1,Math.hypot(pts[0].x-pts[1].x,pts[0].y-pts[1].y)),
              zoom0:targetZoom,mPrev:{x:(pts[0].x+pts[1].x)/2,y:(pts[0].y+pts[1].y)/2}};
          }
          return;
        }
        if(mode==='lasso'){polygon=[pointer(event)];drawOutline();}});
      canvas.addEventListener('pointermove',event=>{if(!touching)return;interaction();
        if(mode==='lasso'){const point=pointer(event),previous=polygon[polygon.length-1];
          if(polygon.length<512&&shouldRecordLassoPoint(previous,point)){
            polygon.push(point);if(polygon.length%3===0)addSparks(point);drawOutline();}}
        else{
          if(!movePointers.has(event.pointerId))return;
          movePointers.set(event.pointerId,{x:event.clientX,y:event.clientY});
          if(twoFinger){
            // Two-finger state is only marked dirty here; the update loop
            // consumes the LATEST pair once per rendered frame.
            if(twoFinger.ids.includes(event.pointerId))twoFinger.dirty=true;
          }else if(movePointers.size===1){
            targetYaw=Math.max(yawBounds[0],Math.min(yawBounds[1],targetYaw+(event.clientX-lastX)*.008));
            targetPitch=Math.max(pitchBounds[0],Math.min(pitchBounds[1],targetPitch+(event.clientY-lastY)*.008));
          }
        }
        lastX=event.clientX;lastY=event.clientY;});
      canvas.addEventListener('pointerup',event=>{if(mode==='move'){
        movePointers.delete(event.pointerId);
        if(twoFinger&&twoFinger.ids.includes(event.pointerId))endTwoFinger(); // 2->1: rebase the survivor's orbit anchor
        touching=movePointers.size>0;
        if(!touching)freezeOnRelease(); // stop exactly where the screen is
        else if(movePointers.size===1){const remaining=movePointers.values().next().value;lastX=remaining.x;lastY=remaining.y;}
        return;
      }if(!touching)return;touching=false;if(mode!=='lasso')return;
        try{const first=polygon[0],last=polygon[polygon.length-1];
          if(first&&last&&Math.hypot(first.x-last.x,first.y-last.y)>5)polygon.push(first);
          polygon=normalizeLasso(polygon);
          const r=canvas.getBoundingClientRect();
          const result=selectVisibleSplats({data,polygon,target,cameraPosition:camera.getPosition().toArray(),
            editableIndices:editableSet,
            project:(x,y,z)=>camera.camera.worldToScreen(new Vec3(x,y,z)),width:r.width,height:r.height});
          const slot=selectionSlot(selections.length,appendNext);
          const regionId=selections[slot]?.regionId||`gs-selected-${slot+1}`;
          mask=result.mask;selected=result.selected;selectedPolygon=polygon.slice();selectionYaw=yaw;selectionPitch=pitch;
          selectionWidth=r.width;selectionHeight=r.height;selectionTarget=target.slice();selectionZoom=zoom;
          const entry={regionId,mask:mask.slice(),polygon:polygon.slice(),yaw,pitch,target:target.slice(),zoom,width:r.width,height:r.height,
            samples:sampleMask(mask)};
          if(slot===selections.length)selections.push(entry);else selections[slot]=entry;
          appendNext=false;
          const selectionBounds={left:Math.min(...polygon.map(p=>p.x))/r.width,top:Math.min(...polygon.map(p=>p.y))/r.height,
            right:Math.max(...polygon.map(p=>p.x))/r.width,bottom:Math.max(...polygon.map(p=>p.y))/r.height};
          send('GS_SELECTION',{regionId,count:selected,total:data.numSplats,selectionBounds,x:polygon.reduce((s,p)=>s+p.x,0)/polygon.length/r.width,
            y:polygon.reduce((s,p)=>s+p.y,0)/polygon.length/r.height});
          sendBytes('gs-mask',mask);if(last)addSparks(last,true);
          report('SELECTED',t('selected',selections.length));
        }catch(error){send('GS_FAILED',{message:String(error)});report('SELECTION_FAILED',String(error));}
        polygon=[];drawOutline();});
      canvas.addEventListener('pointercancel',event=>{
        movePointers.delete(event.pointerId);
        if(twoFinger&&twoFinger.ids.includes(event.pointerId))endTwoFinger();
        touching=movePointers.size>0;
        if(!touching)freezeOnRelease();
        else if(movePointers.size===1){const remaining=movePointers.values().next().value;lastX=remaining.x;lastY=remaining.y;}
        polygon=[];drawOutline();});
      canvas.addEventListener('wheel',event=>{targetZoom=clampZoom(targetZoom*Math.exp(event.deltaY*.001));event.preventDefault();},{passive:false});
      command=payload=>{
        if(payload.action==='VIEW_SNAPSHOT'){
          if(!lastRenderedView){send('GS_FAILED',{message:t('viewNotDrawn')});return;}
          send('GS_VIEW',{gsView:lastRenderedView});return;
        }
        if(payload.action==='TOOL'){mode=payload.tool==='lasso'?'lasso':'move';appendNext=false;return;}
        if(payload.action==='ARM_APPEND'){mode='lasso';appendNext=true;return;}
        if(payload.action==='CLEAR_SELECTION'){
          dissolveSelections();selections=[];polygon=[];selectedPolygon=[];mask=null;selected=0;appendNext=false;
          if(carePreviewActive){drawHistory(historyLayers);carePreviewActive=false;}
          drawOutline();return;}
        if(payload.action==='CARE_PREVIEW'){
          const week=payload.strength;
          if(!Number.isInteger(week)||week<0||week>8)throw Error(t('weekInvalid'));
          if(selections.length<1)throw Error(t('needSelection'));
          applyCareScenario(resource,originalColors,historyLayers,selections.map(item=>item.mask),week/8);editRevision++;
          carePreviewActive=week>0;model.gsplat.workBufferUpdate=WORKBUFFER_UPDATE_ONCE;app.renderNextFrame=true;return;
        }
        if(payload.action==='SET_HISTORY'){
          const incoming=payload.layers;
          if(!Array.isArray(incoming)||incoming.length>16)throw Error(t('tooManyLayers'));
          const next=incoming.map(layer=>({mask:decodeMask(layer.maskBase64),preset:layer.preset,strength:layer.strength}));
          drawHistory(next);historyLayers=next;appliedRecipe=null;carePreviewActive=false;
          send('GS_APPLIED',{action:'SET_HISTORY',count:next.length});return;
        }
        if(payload.action==='RESTORE'){
          const decoded=atob(payload.maskBase64||'');
          if(decoded.length!==data.numSplats)throw Error(t('layerMismatch'));
          mask=Uint8Array.from(decoded,c=>c.charCodeAt(0));selected=mask.reduce((n,v)=>n+(v>0?1:0),0);
          if(selected<80)throw Error(t('layerIncomplete'));
          if(!Object.hasOwn(DIGITAL_PRESETS,payload.preset)||![.18,.32,.5].includes(payload.strength))throw Error(t('colorInvalid'));
          applyDigitalTint(resource,originalColors,mask,DIGITAL_PRESETS[payload.preset],payload.strength);editRevision++;
          model.gsplat.workBufferUpdate=WORKBUFFER_UPDATE_ONCE;app.renderNextFrame=true;
          appliedRecipe={mask:mask.slice(),preset:payload.preset,strength:payload.strength};
          send('GS_APPLIED',{action:'RESTORE',count:selected});return;}
        if(payload.action==='RESET'){applyDigitalTint(resource,originalColors,new Uint8Array(data.numSplats),[.5,.5,.5],0);editRevision++;
          model.gsplat.workBufferUpdate=WORKBUFFER_UPDATE_ONCE;app.renderNextFrame=true;appliedRecipe=null;send('GS_APPLIED',{action:'RESET'});return;}
        if(payload.action==='COMPARE_ORIGINAL'||payload.action==='COMPARE_EDIT'){
          if(!appliedRecipe)throw Error(t('noCompare'));
          if(payload.action==='COMPARE_ORIGINAL')applyDigitalTint(resource,originalColors,new Uint8Array(data.numSplats),[.5,.5,.5],0);
          else applyDigitalTint(resource,originalColors,appliedRecipe.mask,DIGITAL_PRESETS[appliedRecipe.preset],appliedRecipe.strength);
          editRevision++;
          model.gsplat.workBufferUpdate=WORKBUFFER_UPDATE_ONCE;app.renderNextFrame=true;
          send('GS_APPLIED',{action:payload.action});return;}
        if(payload.action==='APPLY'){
          if(!mask||selected<28)throw Error(t('needCircle'));
          if(!Object.hasOwn(DIGITAL_PRESETS,payload.preset)||![.18,.32,.5].includes(payload.strength))throw Error(t('colorUnavailable'));
          applyDigitalTint(resource,originalColors,mask,DIGITAL_PRESETS[payload.preset],payload.strength);editRevision++;
          model.gsplat.workBufferUpdate=WORKBUFFER_UPDATE_ONCE;app.renderNextFrame=true;
          appliedRecipe={mask:mask.slice(),preset:payload.preset,strength:payload.strength};
          send('GS_APPLIED',{action:'APPLY',count:selected});return;}
        if(payload.action==='CAPTURE'){
          const r=canvas.getBoundingClientRect(),scale=Math.min(1,1024/Math.max(r.width,r.height));
          const image=document.createElement('canvas');image.width=Math.max(8,Math.round(r.width*scale));image.height=Math.max(8,Math.round(r.height*scale));
          const ctx=image.getContext('2d');ctx.drawImage(canvas,0,0,image.width,image.height);
          send('GS_CAPTURE',{width:image.width,height:image.height,images:2,gsView:lastRenderedView||viewSnapshot()});sendBytes('gs-clean',pngBytes(image.toDataURL('image/png')));
          // Reproject the selected 3D points into this camera. The annotation
          // stays aligned after orbiting, unlike reusing the old screen lasso.
          if(selections.length){
            const xs=data.getProp('x'),ys=data.getProp('y'),zs=data.getProp('z'),eye=camera.getPosition().toArray();
            const forward=normal(aimPoint.map((v,i)=>v-eye[i])),distance=Math.hypot(...target.map((v,i)=>v-eye[i]));
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
          if(selectedPolygon.length>=3&&selectionTarget.every((value,i)=>Math.abs(value-target[i])<radius*1e-6)&&
            Math.abs(zoom-selectionZoom)<1e-6&&Math.abs(yaw-selectionYaw)<.04&&Math.abs(pitch-selectionPitch)<.04&&
            Math.abs(r.width-selectionWidth)<1&&Math.abs(r.height-selectionHeight)<1){ctx.save();ctx.scale(image.width/r.width,image.height/r.height);ctx.beginPath();ctx.moveTo(selectedPolygon[0].x,selectedPolygon[0].y);
            for(let i=1;i<selectedPolygon.length;i++)ctx.lineTo(selectedPolygon[i].x,selectedPolygon[i].y);ctx.closePath();ctx.strokeStyle='#D7EAFF';ctx.lineWidth=3;ctx.stroke();ctx.restore();}
          sendBytes('gs-annotated',pngBytes(image.toDataURL('image/png')));return;}
      };
      modelReady=true;if(port)port.postMessage(JSON.stringify({schemaVersion:1,type:'READY',payload:{webgl2:true}}));
      if(!preview){setTimeout(sampleTone,450);setInterval(sampleTone,3200);}
      report('READY',t('ready',data.numSplats));
      setTimeout(()=>status.classList.add('quiet'),2200);
      console.log(`SELF_GS_VIEWER_VIEW ${view.sourceFrame} ${view.faceTrackCount} ${view.fovDegrees}`);
      window.addEventListener('resize',()=>{app.resizeCanvas();adjustRecordedFraming();resizeOutline();drawOutline();app.renderNextFrame=true;});
    }catch(error){report('ERROR',t('drawFail')+String(error));}
  });app.assets.load(asset);
}
start().catch(error=>report('ERROR',t('drawUnavailable')+String(error)));

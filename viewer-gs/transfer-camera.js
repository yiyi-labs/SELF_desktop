import { fitOpeningDistance } from './transfer-camera-math.js';
// Same portable camera contract on phone and tablet. No analysis or persistence here.
const vector=v=>Array.isArray(v)&&v.length===3&&v.every(Number.isFinite);
export function validTransferCamera(v){
  if(!v||v.schema!=='self.transfer.viewer'||v.version!==1||!vector(v.camera)||!vector(v.target)||!vector(v.up)||
    !Number.isFinite(v.fovDegrees)||v.fovDegrees<10||v.fovDegrees>90)return false;
  const forward=v.target.map((n,i)=>n-v.camera[i]);
  return Math.hypot(...forward)>1e-9&&Math.hypot(...v.up)>1e-9&&Math.hypot(
    forward[1]*v.up[2]-forward[2]*v.up[1],forward[2]*v.up[0]-forward[0]*v.up[2],forward[0]*v.up[1]-forward[1]*v.up[0])>1e-9;
}
export function snapshotCamera(s){
  if(!s||s.frame<1||!vector(s.position)||!Array.isArray(s.rotation)||s.rotation.length!==4||!s.rotation.every(Number.isFinite)||!(s.distance>1e-9))throw Error('Current camera is not rendered');
  const norm=Math.hypot(...s.rotation);if(norm<1e-9)throw Error('Invalid camera rotation');
  const [x,y,z,w]=s.rotation.map(n=>n/norm);
  const up=[2*(x*y-z*w),1-2*(x*x+z*z),2*(y*z+x*w)];
  const forward=[-2*(x*z+y*w),-2*(y*z-x*w),-(1-2*(x*x+y*y))];
  const v={schema:'self.transfer.viewer',version:1,camera:s.position.slice(),target:s.position.map((n,i)=>n+forward[i]*s.distance),up,fovDegrees:s.fovDegrees};
  v.nearClip=s.nearClip;v.farClip=s.farClip;
  if(!validTransferCamera(v))throw Error('Invalid current camera');return v;
}
export function applyTransferCamera(view,v){
  if(!validTransferCamera(v))return false;
  view.camera=v.camera.slice();view.target=v.target.slice();view.up=v.up.slice();view.fovDegrees=v.fovDegrees;view.transferNearClip=v.nearClip;view.transferFarClip=v.farClip;
  view.targetFaceFraction=.5;
  delete view.captureHorizontalFovDegrees;delete view.safeYawDegrees;delete view.safePitchDegrees;
  return true;
}
/** Fit saved face geometry to the new screen using the same projected box as the phone. */
export function savedFrontCamera(view,width,height){
  const p=view.portraitView||view.portraitFallback;
  if(!p||!(p.verified===true||p.verified===false&&p.pitchLimited===true&&p.confidence==='visible-face-pitch-limited')||p.version!==2||p.resolverVersion!==2||p.assetHash!==view.assetSha256||
    p.sourceKind!=='self-transfer'||!vector(p.pivot)||!vector(p.front)||!vector(p.up)||!p.headHalf||
    !(p.fitDistance>0)||!(p.fitFovY>=10&&p.fitFovY<=90))return undefined;
  const aspect=width/Math.max(1,height);
  let distance=p.fitDistance;
  if(Math.abs(aspect-p.fitAspect)>.001){
    const fit=fitOpeningDistance({pivot:p.pivot,front:p.front,up:p.up,half:p.headHalf,
      viewport:{width,height},fovY:p.fitFovY,
      heightFraction:p.framingSource==='face-only'?.55:.67,widthFraction:p.framingSource==='face-only'?.82:.90});
    if(!fit)return undefined;distance=fit.r;
  }
  const v={schema:'self.transfer.viewer',version:1,camera:p.pivot.map((n,i)=>n+p.front[i]*distance),target:p.pivot.slice(),up:p.up.slice(),fovDegrees:p.fitFovY,
    nearClip:Math.max(1e-4,p.headHalf.u*2*.005),farClip:10000};
  return validTransferCamera(v)?v:undefined;
}

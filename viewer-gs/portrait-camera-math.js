// Gesture camera math copied unchanged from olay_harmony.
export const add=(a,b)=>[a[0]+b[0],a[1]+b[1],a[2]+b[2]];
export const sub=(a,b)=>[a[0]-b[0],a[1]-b[1],a[2]-b[2]];
export const scale=(a,k)=>[a[0]*k,a[1]*k,a[2]*k];
export const dot=(a,b)=>a[0]*b[0]+a[1]*b[1]+a[2]*b[2];
export const cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
export const len=a=>Math.hypot(a[0],a[1],a[2]);
export const norm=a=>{const n=len(a);return [a[0]/n,a[1]/n,a[2]/n];};
export const dist=(a,b)=>len(sub(a,b));
const finite=v=>v.every(Number.isFinite);

/** Rodrigues rotation of vector v around unit axis a by angle t (radians). */
export const rotate=(v,a,t)=>{const c=Math.cos(t),s=Math.sin(t),d=dot(v,a);
  return [v[0]*c+(a[1]*v[2]-a[2]*v[1])*s+a[0]*d*(1-c),
    v[1]*c+(a[2]*v[0]-a[0]*v[2])*s+a[1]*d*(1-c),
    v[2]*c+(a[0]*v[1]-a[1]*v[0])*s+a[2]*d*(1-c)];};

/**
 * Camera basis from position + look target + reference up (Gram-Schmidt).
 * forward points from pos toward target; right = forward x up; upCam = right x forward.
 */
export function lookAtBasis(pos,target,up){
  const forward=norm(sub(target,pos));
  let right=cross(forward,up);
  if(len(right)<1e-6)return null; // looking along up: degenerate
  right=norm(right);
  const upCam=cross(right,forward);
  return {pos:[...pos],forward,right,upCam};
}

/**
 * World ray through a pixel. px/px are top-left origin pixels within
 * width x height (CSS pixels or buffer pixels — only the ratio matters).
 */
export function rayFromPixel(basis,fovY,aspect,width,height,px,py){
  const th=Math.tan(fovY*Math.PI/360);
  const ndcX=(px/width)*2-1, ndcY=1-(py/height)*2;
  const dir=norm(add(add(scale(basis.right,ndcX*th*aspect),scale(basis.upCam,ndcY*th)),basis.forward));
  return {origin:[...basis.pos],dir};
}

/** Project a world point: pixel coords + depth (positive in front of camera). */
export function projectPoint(basis,fovY,aspect,width,height,p){
  const rel=sub(p,basis.pos);
  const depth=dot(rel,basis.forward);
  if(depth<=0)return {x:0,y:0,depth,behind:true};
  const th=Math.tan(fovY*Math.PI/360);
  const x=(dot(rel,basis.right)/(th*aspect*depth)*.5+.5)*width;
  const y=(.5-dot(rel,basis.upCam)/(th*depth)*.5)*height;
  return {x,y,depth,behind:false};
}

/**
 * Two-finger pan delta: intersect the pointer rays with the plane through the
 * pivot whose normal is the logical camera forward. delta = Wprev - Wnow so
 * adding it to the pivot (and thus the camera) makes the content follow the
 * fingers. A pure pinch (unchanged centroid) yields delta 0 — zoom is
 * centre-anchored on the pivot by construction.
 */
export function twoFingerPanDelta({mPrev,mNow,camBasis,fovY,aspect,width,height,pivot}){
  const toWorld=m=>{
    const ray=rayFromPixel(camBasis,fovY,aspect,width,height,m.x,m.y);
    const denom=dot(ray.dir,camBasis.forward);
    if(Math.abs(denom)<1e-6)return null;
    const t=dot(sub(pivot,ray.origin),camBasis.forward)/denom;
    if(!Number.isFinite(t)||t<=0)return null;
    return add(ray.origin,scale(ray.dir,t));
  };
  const wPrev=toWorld(mPrev),wNow=toWorld(mNow);
  if(!wPrev||!wNow)return null;
  const delta=sub(wPrev,wNow);
  return finite(delta)?delta:null;
}

/**
 * Compose the orbit camera exactly like the controller: yaw the (pivot->camera)
 * vector around up, pitch around the derived right axis, place at radius r.
 * Returns the camera position plus the lookAt basis used for rendering.
 */
export function composeOrbitCamera(pivot,originalDir,up,yaw,pitch,r){
  const afterYaw=rotate(originalDir,up,yaw);
  const offsetDir=norm(afterYaw);
  const forward=norm(scale(offsetDir,-1));
  let right=cross(forward,up);
  if(len(right)<1e-6)right=cross(forward,[1,0,0]);
  right=norm(right);
  const pitched=rotate(afterYaw,right,pitch);
  const pos=add(pivot,scale(norm(pitched),r));
  const basis=lookAtBasis(pos,pivot,up);
  return {pos,basis,right};
}


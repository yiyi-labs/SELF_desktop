// Projected head fit shared by both transfer viewers.
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

export function fitOpeningDistance({pivot,front,up,half,viewport,fovY=60,heightFraction=.67,widthFraction=.90,margin}){
  const corners=[];
  for(const fs of [-1,1])for(const us of [-1,1])for(const xs of [-1,1])
    corners.push(add(pivot,add(scale(front,fs*half.f),add(scale(up,us*half.u),scale(cross(up,front),xs*half.x)))));
  const headHeight=2*half.u;
  const nearMargin=margin??headHeight*.02;
  const rFloor=Math.max(headHeight*.05,nearMargin*2);
  const measure=r=>{
    const pos=add(pivot,scale(front,r));
    const basis=lookAtBasis(pos,pivot,up);
    if(!basis)return null;
    let minX=1e9,maxX=-1e9,minY=1e9,maxY=-1e9,allFront=true,minDepth=1e9;
    for(const c of corners){
      const p=projectPoint(basis,fovY,viewport.width/viewport.height,viewport.width,viewport.height,c);
      if(p.behind||p.depth<=nearMargin){allFront=false;break;}
      minDepth=Math.min(minDepth,p.depth);
      minX=Math.min(minX,p.x);maxX=Math.max(maxX,p.x);minY=Math.min(minY,p.y);maxY=Math.max(maxY,p.y);
    }
    if(!allFront)return {feasible:false};
    const hF=(maxY-minY)/viewport.height,wF=(maxX-minX)/viewport.width;
    return {feasible:hF<=heightFraction&&wF<=widthFraction,
      heightFraction:hF,widthFraction:wF,minDepth};
  };
  const seed=headHeight/(2*heightFraction*Math.tan(fovY*Math.PI/360));
  let hi=Math.max(seed,rFloor);
  let ok=null;
  for(let i=0;i<40;i++){
    ok=measure(hi);
    if(ok&&ok.feasible)break;
    hi*=2;
    if(hi>seed*1e4+1e3)return null; // never fits (degenerate extents)
  }
  if(!ok||!ok.feasible)return null;
  let lo=Math.max(rFloor,hi*.25);
  // ensure lo is infeasible (either too-close or clipped) so bisection closes on the boundary
  for(let i=0;i<8&&measure(lo)?.feasible;i++)lo*=.5;
  for(let i=0;i<24;i++){
    const mid=Math.sqrt(lo*hi);
    const m=measure(mid);
    if(m&&m.feasible)hi=mid;else lo=mid;
  }
  const finalMeasure=measure(hi);
  return {r:hi,measured:{heightFraction:finalMeasure.heightFraction,widthFraction:finalMeasure.widthFraction},
    binding:finalMeasure.widthFraction>=widthFraction-.001?'width':'height',minDepth:finalMeasure.minDepth};
}


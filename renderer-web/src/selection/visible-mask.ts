import * as THREE from 'three';
import {inside, type Point} from './polygon.ts';
export type SurfaceSample={u:number,v:number,point:THREE.Vector3};
// Rasterise UV triangles once; test visibility through nearest ray hit. Work is bounded by selected UV candidates,
// never by screen pixels times the entire mesh. This CPU reference prioritises correctness; production budget is measured.
export async function visibleMask(mesh:THREE.Mesh,camera:THREE.Camera,polygon:Point[],width:number,height:number,editable:Uint8Array,size=1024):Promise<Uint8Array>{
  const geo=mesh.geometry,pos=geo.getAttribute('position'),uv=geo.getAttribute('uv'),idx=geo.index;
  if(!idx||!uv||editable.length!==size*size)throw Error('Unregistered geometry');
  mesh.updateMatrixWorld(true);camera.updateMatrixWorld(true);
  const out=new Uint8Array(size*size),ray=new THREE.Raycaster(),ndc=new THREE.Vector2(),q=new THREE.Vector3();
  const vertices=[new THREE.Vector3(),new THREE.Vector3(),new THREE.Vector3()];
  const projected=[new THREE.Vector3(),new THREE.Vector3(),new THREE.Vector3()];
  const minX=Math.min(...polygon.map(p=>p.x)),maxX=Math.max(...polygon.map(p=>p.x)),minY=Math.min(...polygon.map(p=>p.y)),maxY=Math.max(...polygon.map(p=>p.y));
  for(let t=0;t<idx.count;t+=3){
    const ids=[idx.getX(t),idx.getX(t+1),idx.getX(t+2)];
    for(let k=0;k<3;k++){vertices[k].fromBufferAttribute(pos,ids[k]).applyMatrix4(mesh.matrixWorld);projected[k].copy(vertices[k]).project(camera);}
    const screen=projected.map(v=>({x:(v.x+1)*width/2,y:(1-v.y)*height/2}));
    if(Math.max(...screen.map(p=>p.x))<minX||Math.min(...screen.map(p=>p.x))>maxX||Math.max(...screen.map(p=>p.y))<minY||Math.min(...screen.map(p=>p.y))>maxY)continue;
    const us=ids.map(i=>uv.getX(i)*size),vs=ids.map(i=>uv.getY(i)*size);
    const det=(vs[1]-vs[2])*(us[0]-us[2])+(us[2]-us[1])*(vs[0]-vs[2]);if(Math.abs(det)<1e-8)continue;
    for(let y=Math.max(0,Math.floor(Math.min(...vs)));y<Math.min(size,Math.ceil(Math.max(...vs)));y++)for(let x=Math.max(0,Math.floor(Math.min(...us)));x<Math.min(size,Math.ceil(Math.max(...us)));x++){
      const n=y*size+x;if(!editable[n])continue;
      const a=((vs[1]-vs[2])*(x+.5-us[2])+(us[2]-us[1])*(y+.5-vs[2]))/det;
      const b=((vs[2]-vs[0])*(x+.5-us[2])+(us[0]-us[2])*(y+.5-vs[2]))/det,c=1-a-b;
      if(Math.min(a,b,c)<0)continue;
      q.copy(vertices[0]).multiplyScalar(a).addScaledVector(vertices[1],b).addScaledVector(vertices[2],c);
      const projectedPoint=q.clone().project(camera);
      if(projectedPoint.z < -1||projectedPoint.z>1||!inside({x:(projectedPoint.x+1)*width/2,y:(1-projectedPoint.y)*height/2},polygon))continue;
      ndc.set(projectedPoint.x,projectedPoint.y);ray.setFromCamera(ndc,camera);
      const hit=ray.intersectObject(mesh,false)[0];
      // Match primitive triangle AND surface point. No large depth epsilon permitting nose/other cheek leakage.
      if(hit?.faceIndex===t/3&&hit.point.distanceTo(q)<1e-4)out[n]=255;
    }
    if(t%900===0)await new Promise<void>(resolve=>setTimeout(resolve,0));
  }
  return out;
}

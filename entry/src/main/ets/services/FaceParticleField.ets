export interface FaceParticle {x:number;y:number;opacity:number;size:number;}

/** Lightweight depth-cued guide, projected from a canonical curved surface.
 * This is UI only: five observed landmarks cannot recover the user's mesh.
 */
export function faceParticle(index:number,yawDegrees:number,count:number=36):FaceParticle {
 const radius=Math.sqrt((index+.5)/count)*.91;
 const phase=index*2.399963229728653;
 const u=Math.cos(phase)*radius,v=Math.sin(phase)*radius;
 const z=Math.sqrt(Math.max(0,1-u*u-v*v));
 const yaw=Math.max(-55,Math.min(55,yawDegrees))*Math.PI/180;
 const depth=z*Math.cos(yaw)-u*Math.sin(yaw);
 const x=u*Math.cos(yaw)+z*Math.sin(yaw);
 return {x,y:v,opacity:depth>.14?.18+Math.min(.30,depth*.3):0,size:depth>.14?2+depth*1.3:0};
}

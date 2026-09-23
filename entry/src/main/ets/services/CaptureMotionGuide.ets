import { FaceAnchor } from './FaceAnchorTracker';

/** Relative motion of the same tracked face; not an AR pose or reconstruction quality score. */
export class CaptureMotionGuide {
 private origin:FaceAnchor|undefined;
 private previous:FaceAnchor|undefined;
 private lastAt:number=0;
 private movingAt:number=0;
 private direction:number=0;
 private samples:number=0;
 private following:boolean=false;
 private logAt:number=0;
 reset():void{this.origin=undefined;this.previous=undefined;this.lastAt=0;this.movingAt=0;this.direction=0;this.samples=0;this.following=false;}
 update(face:FaceAnchor|undefined,now:number):boolean{
  if(!face?.locked||!face.observed){if(now-this.lastAt>850)this.reset();if(now-this.logAt>=1000){this.logAt=now;console.info('SELF_CAMERA_MOTION '+JSON.stringify({tracked:false,following:this.following}));}return this.following;}
  if(this.previous&&(now-this.lastAt>500||Math.hypot((face.x-this.previous.x)/Math.max(.06,face.width),(face.y-this.previous.y)/Math.max(.06,face.height))>.65))this.reset();
  this.lastAt=now;this.previous=face;
  if(!this.origin){this.origin={x:face.x,y:face.y,width:face.width,height:face.height,roll:face.roll,yaw:face.yaw,locked:face.locked};return false;}
  if(this.following)return true;
  const dx=(face.x-this.origin.x)/Math.max(.06,this.origin.width);
  const yaw=face.yaw-this.origin.yaw;
  if(now-this.logAt>=1000){this.logAt=now;console.info('SELF_CAMERA_MOTION '+JSON.stringify({tracked:true,dx:Math.round(dx*100)/100,yaw:Math.round(yaw),samples:this.samples,following:this.following}));}
  // Horizontal parallax/turn cue. Reject tiny landmark jitter, a single jump,
  // scale-only motion and vertical nodding. Never advance because a timer elapsed.
  const translated=Math.abs(dx)>=.12;
  const turned=Math.abs(yaw)>=7;
  if(!translated&&!turned){this.samples=0;this.movingAt=0;this.direction=0;return false;}
  const direction=Math.sign(translated?dx:yaw);
  if(this.direction!==direction){this.samples=0;this.movingAt=now;this.direction=direction;}
  if(!this.samples)this.movingAt=now;
  this.samples++;
  if(this.samples>=2&&now-this.movingAt>=100)this.following=true;
  return this.following;
 }
}

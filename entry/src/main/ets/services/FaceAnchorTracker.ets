export interface FacePoint {x:number;y:number;}
export interface DetectedFace {confidence:number;x:number;y:number;width:number;height:number;landmarks:FacePoint[];yaw?:number;roll?:number;}
export interface FaceAnchor {x:number;y:number;width:number;height:number;roll:number;yaw:number;locked:boolean;}
/** Geometric association only: not biometric identity or measured 3D pose. */
export class FaceAnchorTracker {
 private last:FaceAnchor|undefined;private at:number=0;private consecutive:number=0;
 reset():void{this.last=undefined;this.at=0;this.consecutive=0;}
 update(faces:DetectedFace[],now:number,aspect:number):FaceAnchor|undefined{
  const valid=faces.filter((f:DetectedFace)=>f.confidence>=.80&&f.landmarks.length===5&&f.width>.06&&f.height>.06&&
   f.x>=0&&f.y>=0&&f.x+f.width<=1&&f.y+f.height<=1&&
   f.landmarks.every((point:FacePoint)=>point.x>=0&&point.x<=1&&point.y>=0&&point.y<=1));
  let face:DetectedFace|undefined;
  if(this.last&&now-this.at<450){
   const previous=this.last;
   const nearby=valid.filter((f:DetectedFace)=>Math.hypot((f.landmarks[2].x-previous.x)*aspect,f.landmarks[2].y-previous.y)<Math.max(.08,previous.height*.65)&&f.height/previous.height>.55&&f.height/previous.height<1.8);
   if(nearby.length===1)face=nearby[0];
  }else if(valid.length===1){face=valid[0];}
  if(!face){if(now-this.at>300)this.reset();return undefined;}
  const nose=face.landmarks[2],e0=face.landmarks[0],e1=face.landmarks[1];
  if(nose.x<0||nose.x>1||nose.y<0||nose.y>1){this.reset();return undefined;}
  const dx=(e1.x-e0.x)*aspect,dy=e1.y-e0.y;
  let roll=Math.atan2(dy,dx)*180/Math.PI;if(roll>90)roll-=180;if(roll< -90)roll+=180;
  if(face.roll!==undefined&&Number.isFinite(face.roll))roll=Math.max(-90,Math.min(90,face.roll));
  const estimatedYaw=(nose.x-(e0.x+e1.x)/2)/Math.max(.02,Math.abs(e1.x-e0.x))*80;
  const yaw=Math.max(-55,Math.min(55,face.yaw!==undefined&&Number.isFinite(face.yaw)?face.yaw:estimatedYaw));
  const previous=this.last;
  const alpha=previous?Math.min(.9,.5+Math.hypot((nose.x-previous.x)*aspect,nose.y-previous.y)*5):1;
  this.consecutive++;
  const anchor:FaceAnchor={x:previous?previous.x+(nose.x-previous.x)*alpha:nose.x,y:previous?previous.y+(nose.y-previous.y)*alpha:nose.y,width:face.width,height:face.height,roll:previous?previous.roll+(roll-previous.roll)*.55:roll,yaw:previous?previous.yaw+(yaw-previous.yaw)*.55:yaw,locked:this.consecutive>=3};
  this.last=anchor;this.at=now;return anchor;
 }
}

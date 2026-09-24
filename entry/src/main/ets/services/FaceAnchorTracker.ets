export interface FacePoint {x:number;y:number;}
export interface DetectedFace {
 confidence:number;x:number;y:number;width:number;height:number;landmarks:FacePoint[];
 yaw?:number;roll?:number;sampleAt?:number;poseSampleAt?:number;
}
export interface FaceAnchor {
 x:number;y:number;width:number;height:number;roll:number;yaw:number;locked:boolean;
 observed?:boolean;confidence?:number;poseYaw?:number;poseSampleAt?:number;
 landmarks?:FacePoint[];
}

/** Single-face association and bounded, speed-adaptive smoothing. No biometric identity. */
export class FaceAnchorTracker {
 private last:FaceAnchor|undefined;
 private at:number=0;private sampleAt:number=-1;private consecutive:number=0;
 private rawX:number=0;private rawY:number=0;private velocityX:number=0;private velocityY:number=0;
 private eyeX:number=0;private eyeY:number=0;private rawYaw:number=0;
 private alpha(cutoff:number,dt:number):number{return 1/(1+1/(2*Math.PI*cutoff*dt));}
 reset():void{this.last=undefined;this.at=0;this.sampleAt=-1;this.consecutive=0;this.velocityX=0;this.velocityY=0;this.eyeX=0;this.eyeY=0;this.rawYaw=0;}
 private plausible(face:DetectedFace):boolean{
  if(face.confidence<.80||face.landmarks.length!==5||face.width<.08||face.height<.08||
   face.x<0||face.y<0||face.x+face.width>1||face.y+face.height>1||
   !face.landmarks.every((p:FacePoint)=>p.x>=0&&p.x<=1&&p.y>=0&&p.y<=1))return false;
  const eyes=(face.landmarks[0].y+face.landmarks[1].y)/2;
  const mouth=(face.landmarks[3].y+face.landmarks[4].y)/2;
  const eyeSpan=Math.abs(face.landmarks[1].x-face.landmarks[0].x);
  return mouth>eyes&&eyeSpan>face.width*.12;
 }
 update(faces:DetectedFace[],now:number,aspect:number):FaceAnchor|undefined{
  if(this.last&&now-this.at>650)this.reset();
  const valid=faces.filter((face:DetectedFace)=>this.plausible(face));
  let face:DetectedFace|undefined;
  if(this.last&&now-this.at<750){
   const previous=this.last;
   const nearby=valid.filter((f:DetectedFace)=>Math.hypot((f.landmarks[2].x-previous.x)*aspect,f.landmarks[2].y-previous.y)<Math.max(.10,previous.height*.5)&&
    f.height/previous.height>.65&&f.height/previous.height<1.55);
   if(nearby.length===1)face=nearby[0];
  }else if(valid.length===1){face=valid[0];}
  // One bad frame must not make a locked marker fly across the face.
  if(!face||face.sampleAt!==undefined&&face.sampleAt===this.sampleAt){
   if(this.last&&now-this.at<=650)return {x:this.last.x,y:this.last.y,width:this.last.width,height:this.last.height,
    roll:this.last.roll,yaw:this.last.yaw,locked:this.last.locked,observed:false,confidence:this.last.confidence,
    poseYaw:this.last.poseYaw,poseSampleAt:this.last.poseSampleAt,landmarks:this.last.landmarks};
   this.reset();return undefined;
  }
  const nose=face.landmarks[2],e0=face.landmarks[0],e1=face.landmarks[1];
  const dx=(e1.x-e0.x)*aspect,dy=e1.y-e0.y;
  let roll=Math.atan2(dy,dx)*180/Math.PI;if(roll>90)roll-=180;if(roll< -90)roll+=180;
  if(face.roll!==undefined&&Number.isFinite(face.roll))roll=Math.max(-90,Math.min(90,face.roll));
  const estimateYaw=(nose.x-(e0.x+e1.x)/2)/Math.max(.02,Math.abs(e1.x-e0.x))*80;
  const yaw=Math.max(-55,Math.min(55,face.yaw!==undefined&&Number.isFinite(face.yaw)?face.yaw:estimateYaw));
  const previous=this.last;
  const dt=Math.max(.016,Math.min(.25,(now-this.at)/1000));
  const stable=previous&&now-this.at<550&&Math.hypot((nose.x-previous.x)*aspect,nose.y-previous.y)<Math.max(.08,previous.width*.34);
  this.consecutive=stable?this.consecutive+1:1;
  const eyeX=(e0.x+e1.x)/2,eyeY=(e0.y+e1.y)/2;
  let x=nose.x,y=nose.y;
  if(previous){
   // Translation is supported by both eyes; a nose-only jump is usually a
   // landmark fit error. Allow real profile changes when the pose also turns.
   const eyeTravel=Math.hypot((eyeX-this.eyeX)*aspect,eyeY-this.eyeY);
   const noseTravel=Math.hypot((nose.x-this.rawX)*aspect,nose.y-this.rawY);
   // A yaw inferred from this same nose point is not independent evidence.
   const poseTurn=face.yaw!==undefined?Math.abs(yaw-this.rawYaw):0;
   const noseOnly=noseTravel>Math.max(.006,eyeTravel*2.5)&&eyeTravel<.012&&poseTurn<4;
   if(previous.locked&&noseOnly){
    x=previous.x+(eyeX-this.eyeX);y=previous.y+(eyeY-this.eyeY);
   }
   const derivativeAlpha=this.alpha(1.2,dt);
   this.velocityX+=derivativeAlpha*((x-this.rawX)/dt-this.velocityX);
   this.velocityY+=derivativeAlpha*((y-this.rawY)/dt-this.velocityY);
   const ax=this.alpha(.65+Math.min(2.5,Math.abs(this.velocityX)*2.3),dt);
   const ay=this.alpha(.65+Math.min(2.5,Math.abs(this.velocityY)*2.3),dt);
   x=previous.x+(x-previous.x)*ax;y=previous.y+(y-previous.y)*ay;
   if(previous.locked){
    const distance=Math.hypot((x-previous.x)*aspect,y-previous.y);
    const limit=.012+dt*.18;
    if(distance>limit){const fraction=limit/distance;x=previous.x+(x-previous.x)*fraction;y=previous.y+(y-previous.y)*fraction;}
    if(Math.hypot((x-previous.x)*aspect,y-previous.y)<.0015){x=previous.x;y=previous.y;}
   }
  }
  this.rawX=nose.x;this.rawY=nose.y;
  this.eyeX=eyeX;this.eyeY=eyeY;this.rawYaw=yaw;
  const locked=!!previous?.locked||this.consecutive>=3;
  const anchor:FaceAnchor={x,y,width:previous?previous.width+(face.width-previous.width)*.18:face.width,
   height:previous?previous.height+(face.height-previous.height)*.18:face.height,
   roll:previous?previous.roll+(roll-previous.roll)*.25:roll,
   yaw:previous?previous.yaw+(yaw-previous.yaw)*.25:yaw,
   locked,observed:true,confidence:face.confidence,poseYaw:face.yaw,poseSampleAt:face.poseSampleAt,landmarks:face.landmarks};
  this.last=anchor;this.at=now;this.sampleAt=face.sampleAt||now;return anchor;
 }
}

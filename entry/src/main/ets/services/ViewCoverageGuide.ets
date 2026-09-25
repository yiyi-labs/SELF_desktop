import { FaceAnchor } from './FaceAnchorTracker';

// Outer two sectors are optional guidance, never required to stop recording.
// They count only when Core Vision supplies a fresh, confident observed pose.
export const VIEW_ANGLES:number[]=[-60,-50,-40,-30,-20,-10,0,10,20,30,40,50,60];
export interface ViewCoverageState {covered:boolean[];active:number;count:number;hint:number;angle:number;}

/** Relative face yaw only; not camera pose or reconstruction proof. */
export class ViewCoverageGuide {
 private covered:boolean[]=VIEW_ANGLES.map(()=>false);
 private active:number=-1;private candidate:number=-1;private candidateAt:number=0;
 private lastPoseAt:number=0;private angle:number=0;private angleReady:boolean=false;
 reset():void{this.covered=VIEW_ANGLES.map(()=>false);this.active=-1;this.candidate=-1;this.candidateAt=0;this.lastPoseAt=0;this.angle=0;this.angleReady=false;}
 private sector(yaw:number):number{return Math.max(0,Math.min(VIEW_ANGLES.length-1,Math.round(yaw/10)+6));}
 private next():number{
  for(const index of [6,5,4,3,2,1,0,7,8,9,10,11,12])if(!this.covered[index])return index;
  return -1;
 }
 state():ViewCoverageState{return {covered:[...this.covered],active:this.active,count:this.covered.filter((value:boolean)=>value).length,hint:this.next(),angle:this.angle};}
 update(face:FaceAnchor|undefined,recording:boolean,mirrored:boolean):ViewCoverageState{
  if(!face?.locked||!face.observed||face.poseYaw===undefined||face.poseSampleAt===undefined||
   face.confidence===undefined||face.confidence<.80||face.width<.12||face.height<.12||Math.abs(face.roll)>20||
   face.x-face.width*.55<.03||face.x+face.width*.55>.97||face.y-face.height*.55<.03||face.y+face.height*.55>.97){
   this.active=-1;this.candidate=-1;return this.state();
  }
  // A cached official pose is never counted twice, even if local tracking runs faster.
  const poseAt=face.poseSampleAt;
  if(poseAt<=this.lastPoseAt)return this.state();
  this.lastPoseAt=poseAt;
  const yaw=(mirrored?-1:1)*face.poseYaw;
  if(!Number.isFinite(yaw)||Math.abs(yaw)>65){this.active=-1;this.candidate=-1;return this.state();}
  // Only the visual pointer is smoothed; coverage uses each fresh pose sample.
  this.angle=this.angleReady?Math.round(this.angle+Math.max(-12,Math.min(12,(yaw-this.angle)*.6))):Math.round(yaw);
  this.angleReady=true;
  let sector=this.sector(yaw);
  // Hold the current cell through a 2-degree boundary margin.
  if(this.active>=0&&Math.abs(yaw-VIEW_ANGLES[this.active])<=7)sector=this.active;
  this.active=sector;
  if(!recording){this.candidate=-1;return this.state();}
  if(sector!==this.candidate){this.candidate=sector;this.candidateAt=poseAt;}
  else if(poseAt-this.candidateAt>=250&&Math.abs(yaw-VIEW_ANGLES[sector])<=5)this.covered[sector]=true;
  return this.state();
 }
}

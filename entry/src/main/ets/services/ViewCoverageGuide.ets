import { FaceAnchor } from './FaceAnchorTracker';

export interface ViewCoverageState {covered:boolean[];active:number;count:number;hint:number;angle:number;}

/** A five-sector, relative face-view guide. It is not camera pose or reconstruction proof. */
export class ViewCoverageGuide {
 private covered:boolean[]=[false,false,false,false,false];
 private active:number=-1;private candidate:number=-1;private candidateAt:number=0;
 private lastPoseAt:number=0;private angle:number=0;
 reset():void{this.covered=[false,false,false,false,false];this.active=-1;this.candidate=-1;this.candidateAt=0;this.lastPoseAt=0;this.angle=0;}
 private sector(yaw:number):number{
  if(yaw< -28)return 0;
  if(yaw< -10)return 1;
  if(yaw<=10)return 2;
  if(yaw<=28)return 3;
  return 4;
 }
 private next():number{
  for(const index of [2,1,0,3,4])if(!this.covered[index])return index;
  return -1;
 }
 state():ViewCoverageState{return {covered:[...this.covered],active:this.active,count:this.covered.filter((value:boolean)=>value).length,hint:this.next(),angle:this.angle};}
 update(face:FaceAnchor|undefined,recording:boolean,mirrored:boolean):ViewCoverageState{
  if(!recording){this.active=-1;this.candidate=-1;return this.state();}
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
  if(!Number.isFinite(yaw)||Math.abs(yaw)>50){this.active=-1;this.candidate=-1;return this.state();}
  this.angle=Math.round(yaw);
  const sector=this.sector(yaw);this.active=sector;
  if(sector!==this.candidate){this.candidate=sector;this.candidateAt=poseAt;}
  else if(poseAt-this.candidateAt>=250)this.covered[sector]=true;
  return this.state();
 }
}
